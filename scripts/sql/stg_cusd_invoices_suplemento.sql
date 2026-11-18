-- Suplemento do cusd_monitoring: faturas de distribuidoras que NÃO sobem para o
-- MONITORAMENTO_CUSD_AWS (COELBA, CELPE, CEMIG — ver monitor_nff_app/README.md,
-- seção "Limitações conhecidas"). Essas notas chegam pelo FattureWeb e o Quick
-- Invoices, lendo só o cusd_monitoring, nunca as via — mesmo elas já aparecendo
-- no monitor de NFF (que tem um degrau supletivo próprio, monitor.py::carregar_base).
--
-- Diferente do monitor, NÃO fazemos de/para de UC->ACRONIMO aqui: o cadastro
-- (MONITORAMENTO_HIST_USINA) usa a UC ANTIGA e o FattureWeb já traz a UC NOVA para
-- COELBA (virada ANEEL, mesmo caso da CPFL — ver CLAUDE.md), então o join por
-- NUMERO_DA_INSTALACAO não casaria essas notas. Não é necessário: CLIENTE_APELIDO
-- e DISTRIBUIDORA_SIGLA, as colunas que o create_quick_invoices.py usa para montar
-- a NFF, vêm direto do FATTUREWEB_USINAS — só ACRONIMO fica sem valor
-- (só serve para o bloqueio; NUMERO_DA_INSTALACAO do próprio FW cobre esse caso).
--
-- USINA NOVA (apelido e distribuidora NULOS no FattureWeb) — caso Rio Quente
-- (NFFs 215844804 e 215844805, 13/11/2026, não apareciam no Quick Invoices):
--   CLIENTE_APELIDO e DISTRIBUIDORA_SIGLA do FattureWeb são enriquecidos por JOIN contra
--   um snapshot congelado em 30/12/2025 (ver stg_fattureweb_usinas.sql), então usina que
--   nasceu depois chega com os dois NULOS — e NULL nunca entra no IN abaixo. A nota estava
--   no monitor de NFF (que acha a usina pela UC no MAPA_USINAS) mas não aqui.
--   A segunda perna do COALESCE recupera, SÓ para esse caso (UC cadastrada no MAPA_USINAS
--   e campo nulo no FW), o consórcio e a sigla pelo CNPJ da distribuidora, aprendidos do
--   próprio MONITORAMENTO_CUSD_AWS. O CNPJ só vale quando aponta para UM único
--   (distribuidora, consórcio) no monitoramento: distribuidora que atende mais de um
--   consórcio fica de fora, porque chutar a unidade de negócio lançaria a NFF na entidade
--   errada no Oracle. Conferido em 18/11/2026: CNPJ 01.543.032/0001-04 -> CELGD ->
--   CONSORCIO GD 8, e as NFFs anteriores do Rio Quente (set/out) estão no Oracle em
--   6071-CONSORCIO SERENA GD 8.
WITH cnpj_para_consorcio AS (
    SELECT
        REGEXP_REPLACE(DISTRIBUIDORA_CNPJ, '[^0-9]', '') AS CNPJ_LIMPO,
        MIN(DISTRIBUIDORA)    AS DISTRIBUIDORA_SIGLA,
        MIN(CLIENTE_APELIDO)  AS CLIENTE_APELIDO
    FROM RETAIL_PROD.BACKOFFICE.MONITORAMENTO_CUSD_AWS
    WHERE DISTRIBUIDORA_CNPJ IS NOT NULL
      AND DISTRIBUIDORA IS NOT NULL
      AND CLIENTE_APELIDO IS NOT NULL
    GROUP BY 1
    HAVING COUNT(DISTINCT DISTRIBUIDORA) = 1
       AND COUNT(DISTINCT CLIENTE_APELIDO) = 1
),
ucs_nossas AS (
    SELECT DISTINCT TRIM(INSTALACAO) AS UC
    FROM RETAIL_PROD.BACKOFFICE.MAPA_USINAS
    WHERE INSTALACAO IS NOT NULL
),
fw AS (
    SELECT
        f.NUMERO_DA_INSTALACAO,
        f.NOTA_FISCAL,
        f.DATA_DE_EMISSAO_DA_FATURA,
        f.DATA_DE_VENCIMENTO_DA_FATURA,
        f.DISTRIBUIDORA_CNPJ,
        f.TOTAL_DA_FATURA,
        COALESCE(
            f.CLIENTE_APELIDO,
            CASE WHEN u.UC IS NOT NULL THEN c.CLIENTE_APELIDO END
        ) AS CLIENTE_APELIDO,
        COALESCE(
            f.DISTRIBUIDORA_SIGLA,
            CASE WHEN u.UC IS NOT NULL THEN c.DISTRIBUIDORA_SIGLA END
        ) AS DISTRIBUIDORA_SIGLA
    FROM RETAIL_DEV.BACKOFFICE.FATTUREWEB_USINAS f
    LEFT JOIN ucs_nossas u
           ON u.UC = TRIM(f.NUMERO_DA_INSTALACAO)
    LEFT JOIN cnpj_para_consorcio c
           ON c.CNPJ_LIMPO = REGEXP_REPLACE(f.DISTRIBUIDORA_CNPJ, '[^0-9]', '')
)
SELECT
    NULL AS ACRONIMO,
    NUMERO_DA_INSTALACAO,
    NOTA_FISCAL,
    CLIENTE_APELIDO,
    TO_DATE(DATA_DE_EMISSAO_DA_FATURA, 'DD/MM/YYYY') AS DATA_DE_EMISSAO_DA_FATURA,
    TO_DATE(DATA_DE_VENCIMENTO_DA_FATURA, 'DD/MM/YYYY') AS DATA_DE_VENCIMENTO_DA_FATURA,
    DISTRIBUIDORA_SIGLA,
    DISTRIBUIDORA_CNPJ,
    TOTAL_DA_FATURA AS TOTAL_DA_FATURA
FROM fw
WHERE TOTAL_DA_FATURA IS NOT NULL
  AND CLIENTE_APELIDO IS NOT NULL
  AND NOTA_FISCAL IS NOT NULL
  -- Mesmo escopo de consórcios GD do stg_fattureweb_usinas.sql — sem isso a query
  -- traz faturamento fora do programa GD (a FATTUREWEB_USINAS não é restrita).
  AND CLIENTE_APELIDO IN (
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
  AND NOTA_FISCAL NOT IN (
      SELECT NOTA_FISCAL
      FROM RETAIL_PROD.BACKOFFICE.MONITORAMENTO_CUSD_AWS
      WHERE NOTA_FISCAL IS NOT NULL
  )
