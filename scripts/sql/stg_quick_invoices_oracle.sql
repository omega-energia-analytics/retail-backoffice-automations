-- Quais das NFFs da tela "Quick Invoices Usinas" (monitor_nff_app) já estão no Oracle.
-- Usado só por monitor_nff_app/quick_invoices.py, para marcar a linha como "Já no Oracle" e
-- evitar que a mesma nota seja lançada duas vezes quando duas buscas se sobrepõem.
--
-- {CHAVES} é substituído em Python por uma lista de números entre aspas ('123','456'), já
-- normalizados (sem '.0' e sem zeros à esquerda) e validados como só dígitos antes de
-- entrar aqui — nada digitado pelo usuário chega a este SQL.
--
-- Mesma normalização do _nf_key() do monitor.py e do stg_pagamentos_usinas.sql: a NFF passa
-- por float em algum ponto do caminho (ganha '.0') e a CPFL usa zero à esquerda, então a
-- comparação tem que ser pela chave normalizada, não por igualdade.
--
-- A V_AP_ORACLE_NOVO_PIPE não tem grão único por INVOICENUMBER: nota relançada aparece como
-- uma linha 'Cancelada' e outra válida. Por isso o MAX(): a nota conta como "válida" se
-- QUALQUER linha dela não está cancelada. Só fica VALIDA = 0 quando todas estão canceladas.
SELECT
    LTRIM(REGEXP_REPLACE(TRIM(INVOICENUMBER), '\\.0$', ''), '0') AS CHAVE,
    MAX(IFF(COALESCE(STATUS_INVOICE, '') = 'Cancelada', 0, 1))   AS VALIDA
FROM RETAIL_PROD.BACKOFFICE.V_AP_ORACLE_NOVO_PIPE
WHERE LTRIM(REGEXP_REPLACE(TRIM(INVOICENUMBER), '\\.0$', ''), '0') IN ({CHAVES})
GROUP BY 1
