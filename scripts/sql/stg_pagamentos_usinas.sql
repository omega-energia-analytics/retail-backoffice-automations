-- Pagamentos do Oracle RESTRITOS às notas das usinas, em UMA passada pela view do Oracle.
-- Usado só pelo monitor de NFF (jobs_backoffice/monitor_nff_app).
--
-- POR QUE EXISTE (medido em 05/08/2026):
--   O monitor lia a AP_ORACLE_VIEW (legado) DUAS vezes sem nenhum filtro de escopo:
--     stg_pagamentos.sql             -> 1.004.303 linhas
--     stg_pagamentos_installment.sql ->   975.691 linhas (o WHERE 'Totalmente paga'
--                                         não filtra nada: são 97% da view)
--   Dessas ~2 milhões de linhas, só 1.113 são de nota de usina — 99,9% do tráfego era
--   AP de outras áreas. E a ap_oracle_view era `materialized='view'` sobre três
--   QUALIFY ROW_NUMBER() (AP_INVOICES / AP_INSTALLMENTS / AP_PAYMENTS), ou seja, era
--   recalculada duas vezes por abertura do app. Este arquivo resolve as duas coisas:
--   recorta o escopo no servidor e junta as duas leituras em uma.
--
--   Cortar por data NÃO era a saída: 580.959 das 1.004.303 linhas já eram >= 2025, e
--   INVOICEDATE (legado) era TEXT com formato misto ('2026-05-04 11:31:08' e
--   '2026-07-21T00:00:00Z').
--
-- [migração 09/09/2026] Trocado de RETAIL_DEV.BACKOFFICE.AP_ORACLE_VIEW (legado) para
-- RETAIL_DEV.BACKOFFICE.V_AP_ORACLE_NOVO_PIPE. Só este arquivo migrou — é o caminho
-- PRINCIPAL do monitor (stg_pagamentos.sql/stg_pagamentos_installment.sql continuam
-- lendo o legado e servem de fallback quando esta query falha; são compartilhados com a
-- lambda monitoramento_cusd em PROD e com main_pagamento_usinas.py, fora do escopo desta
-- migração).
--
-- Duas diferenças de contrato exigiram ajuste (validado por amostragem em 09/09/2026,
-- ~1.140 notas de usina comparadas entre as duas views, divergência residual <3,5%):
--
--   1. INVOICENUMBER NÃO é grão único na view nova (o legado escondia isso com
--      QUALIFY ROW_NUMBER()). Uma nota relançada aparece como duas linhas — uma
--      'Cancelada' (valor 0) e outra 'Validada' com o pagamento real (mesmo padrão do
--      caso GO-MNU-01/194412037 comentado em monitor.py::_nf_key). Por isso o CTE
--      NOTAS_DEDUP abaixo, que descarta a 'Cancelada' e fica com a linha mais recente.
--   2. STATUS_PAGAMENTO_INSTALLMENT (texto) não existe na view nova; o equivalente é
--      STATUS_PAGAMENTO_INSTALLMENT_COD, com o MESMO domínio Y/N/P do legado
--      (confirmado via SELECT DISTINCT) — 'Y' equivale a 'Totalmente paga'.
--
-- ADITIVO: o universo de notas abaixo é EXATAMENTE o que o monitor consegue casar no
-- pandas (merge exato + 2º passe por chave normalizada). Nenhuma linha que hoje casa
-- deixa de vir. O único efeito colateral é na direção boa: com menos candidatos por
-- chave, a salvaguarda de ambiguidade de _completar_por_chave_normalizada descarta menos
-- notas, então algum pagamento hoje em branco pode passar a aparecer.

WITH NOTAS_USINAS AS (

    -- Os dois SELECTs replicam de propósito os filtros de stg_query_monitor_usinas_geracao.sql
    -- e stg_fattureweb_usinas.sql — são as duas únicas fontes de nota do monitor. Se um
    -- daqueles arquivos mudar de filtro, mude aqui também (um universo MENOR aqui perderia
    -- pagamento; um MAIOR reintroduz ambiguidade de chave).
    -- [22/10/2026] Trocado de MONITORAMENTO_CUSD_AWS para USINAS_GERACAO, acompanhando a
    -- âncora do monitor. Medido: 0 notas só da CUSD (todas já estão em UG ou FW); UG ∪ FW
    -- traz 19 chaves a mais que CUSD ∪ FW. [28/10/2026] RETAIL_PROD junto com a âncora.
    SELECT NOTA_FISCAL
    FROM RETAIL_PROD.BACKOFFICE.USINAS_GERACAO
    WHERE DISTRIBUIDORA_SIGLA IS NOT NULL

    UNION

    SELECT NOTA_FISCAL
    FROM RETAIL_DEV.BACKOFFICE.FATTUREWEB_USINAS
    WHERE CLIENTE_APELIDO IN (
        'CONSORCIO GD 1',
        'CONSORCIO GD 2',
        'CONSORCIO GD 3',
        'CONSORCIO GD 4',
        'CONSORCIO GD 5',
        'CONSORCIO GD 6',
        'CONSORCIO SERENA GD 6',
        'CONSORCIO GD 7',
        'CONSORCIO GD 8',
        'CONSORCIO GD 9',
        'CONSORCIO GD 10',
        'CONSORCIO GD 11',
        'CONSORCIO GD 12',
        'CONSORCIO GD 13'
    )

),

CHAVES AS (

    -- Mesma normalização do _nf_key() do monitor.py: tira o '.0' que a nota ganha ao passar
    -- por float e os zeros à esquerda da CPFL. Tem que ser por chave normalizada, não por
    -- igualdade: das 1.113 linhas de AP que interessam, 107 só casam depois disso.
    -- O NOT IN espelha o _fmt_nf() — 'nan'/'None' viraram chave VÁLIDA quando a nota nula
    -- passa por astype(str), e chave vazia casaria com qualquer nota só de zeros.
    SELECT DISTINCT
        LTRIM(REGEXP_REPLACE(TRIM(NOTA_FISCAL), '\\.0$', ''), '0') AS CHAVE
    FROM NOTAS_USINAS
    WHERE TRIM(COALESCE(NOTA_FISCAL, '')) NOT IN ('', 'nan', 'None', 'NaN', '<NA>', 'NaT')
      AND LTRIM(REGEXP_REPLACE(TRIM(NOTA_FISCAL), '\\.0$', ''), '0') <> ''

),

-- A V_AP_ORACLE_NOVO_PIPE não tem grão único por INVOICENUMBER (ver header). Deduplica
-- por chave normalizada, priorizando a linha NÃO cancelada e, entre essas, a mais
-- recentemente atualizada — mesmo critério que resolvia o caso GO-MNU-01 no legado.
NOTAS_DEDUP AS (
    SELECT * FROM (
        SELECT
            ap.*,
            LTRIM(REGEXP_REPLACE(TRIM(ap.INVOICENUMBER), '\\.0$', ''), '0') AS CHAVE_NORM,
            ROW_NUMBER() OVER (
                PARTITION BY LTRIM(REGEXP_REPLACE(TRIM(ap.INVOICENUMBER), '\\.0$', ''), '0')
                ORDER BY IFF(COALESCE(ap.STATUS_INVOICE, '') = 'Cancelada', 1, 0),
                         ap.UPDATED_AT_INVOICE DESC
            ) AS RN
        FROM RETAIL_HOMOLOG.BACKOFFICE.V_AP_ORACLE_NOVO_PIPE ap
        WHERE LTRIM(REGEXP_REPLACE(TRIM(ap.INVOICENUMBER), '\\.0$', ''), '0') IN (
            SELECT CHAVE FROM CHAVES
        )
    ) WHERE RN = 1
)

SELECT
    ap.INVOICENUMBER   AS NOTA_FISCAL,
    ap.INVOICEAMOUNT   AS FATURA_VALOR,
    ap.PAYMENT_DATE    AS DATA_DE_PAGAMENTO,
    ap.INVOICEDATE     AS DATA_INVOICE,

    -- Colunas do 3º degrau de pagamento (parcela do Oracle). O CASE reproduz o WHERE do
    -- stg_pagamentos_installment.sql: só interessa a evidência POSITIVA ('Y' ==
    -- 'Totalmente paga' no legado — mesmo domínio Y/N/P, confirmado em 09/09/2026), e
    -- nota 'Cancelada' não conta (pode carregar parcela paga de um lançamento anterior —
    -- NFF 194412037 da GO-MNU-01). Fora dessas condições sai NULL, que é o mesmo que o
    -- monitor via quando a linha não vinha na query separada.
    CASE
        WHEN ap.STATUS_PAGAMENTO_INSTALLMENT_COD = 'Y'
         AND COALESCE(ap.STATUS_INVOICE, '') <> 'Cancelada'
        THEN 'Totalmente paga'
    END                AS STATUS_INSTALLMENT,
    CASE
        WHEN ap.STATUS_PAGAMENTO_INSTALLMENT_COD = 'Y'
         AND COALESCE(ap.STATUS_INVOICE, '') <> 'Cancelada'
        -- UPDATED_AT_INSTALLMENT não existe na view nova; UPDATED_AT_PAYMENTS é o mais
        -- próximo (data do lançamento de pagamento). Não é garantido idêntico ao legado
        -- em todo caso (~5% de divergência medida), mas é a melhor aproximação disponível.
        THEN ap.UPDATED_AT_PAYMENTS
    END                AS DATA_STATUS_INSTALLMENT

FROM NOTAS_DEDUP ap
