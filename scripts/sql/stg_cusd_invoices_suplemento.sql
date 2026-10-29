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
-- a NFF, já vêm certas direto do FATTUREWEB_USINAS — só ACRONIMO fica sem valor
-- (só serve para o bloqueio; NUMERO_DA_INSTALACAO do próprio FW cobre esse caso).
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
FROM RETAIL_DEV.BACKOFFICE.FATTUREWEB_USINAS
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
