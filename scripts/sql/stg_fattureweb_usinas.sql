SELECT
    FATURA_ID,
    NUMERO_DA_INSTALACAO,
    -- [add] ENDERECO é o de/para de UC quando a distribuidora TROCA o código da
    -- instalação: o endereço da usina não muda, o número muda. Ver o de/para por
    -- endereço em monitor.py (carregar_base).
    ENDERECO,
    MES_DE_REFERENCIA_DA_FATURA,
    CONTRATO,
    DISTRIBUIDORA_SIGLA,
    CLIENTE_APELIDO,
    DATA_DE_EMISSAO_DA_FATURA,
    DATA_DE_VENCIMENTO_DA_FATURA,
    DATA_DA_APRESENTACAO_DA_FATURA,
    TOTAL_DA_FATURA,
    NOTA_FISCAL,
    DISTRIBUIDORA_CNPJ
FROM RETAIL_DEV.BACKOFFICE.FATTUREWEB_USINAS
-- O filtro de apelido sozinho perde usina nova: CLIENTE_APELIDO é enriquecido por
-- JOIN contra um snapshot congelado em 30/12/2025, então quem nasceu depois e não
-- tem NUMERO_ANTIGO (caso das Rio Quente, UC já no padrão ANEEL) chega com apelido
-- NULO -- e NULL nunca entra num IN. A fatura existe, com UC, FATURA_ID e valor,
-- mas era cortada aqui, deixando UC/Competência/Fatura ID/Total/Valor Oracle vazios
-- no painel mesmo com a NFF aparecendo.
--
-- A segunda perna recupera pela UC cadastrada no MAPA_USINAS, que é a definição de
-- "usina nossa" e se atualiza sozinha a cada cadastro novo -- não precisa voltar
-- aqui quando entrar a próxima usina.
--
-- Por que não `OR CLIENTE_APELIDO IS NULL`: traria 48.390 faturas contra as 2.151
-- de hoje (22x), e dessas só 17 são de UC do mapa. Medido em 15/10/2026.
WHERE TRIM(NUMERO_DA_INSTALACAO) IN (
    SELECT DISTINCT TRIM(INSTALACAO)
    FROM RETAIL_PROD.BACKOFFICE.MAPA_USINAS
    WHERE INSTALACAO IS NOT NULL
)
OR CLIENTE_APELIDO IN (
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
);