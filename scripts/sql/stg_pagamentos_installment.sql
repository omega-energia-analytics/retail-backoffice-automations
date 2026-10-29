-- 2ª evidência de pagamento: a PARCELA do Oracle (AP_INSTALLMENTS), exposta pela
-- ap_oracle_view nas colunas aditivas STATUS_PAGAMENTO_INSTALLMENT / _COD.
--
-- Por que existe: stg_pagamentos.sql descobre pagamento só por PAYMENT_DATE (AP_PAYMENTS).
-- Quando o Oracle quita a parcela mas o pagamento não chega em AP_PAYMENTS, a fatura aparece
-- como "A pagar" mesmo paga. Em junho/2026 isso pegou 4 das 6 faturas de usina do mês.
--
-- Fica em arquivo SEPARADO de propósito: as colunas são novas na view e o monitor.py trata a
-- falha desta query como "degrau desligado" (ver carregar_base). Se estivessem dentro do
-- stg_pagamentos.sql, rodar contra uma view ainda não rebuildada derrubaria o monitor inteiro.
--
-- Filtros: só interessa a evidência POSITIVA de pagamento, e nota 'Cancelada' não conta —
-- pode carregar parcela 'Totalmente paga' de um lançamento anterior (nota relançada), como
-- aconteceu com a NFF 194412037 da GO-MNU-01.
select
    INVOICENUMBER                AS NOTA_FISCAL,
    STATUS_PAGAMENTO_INSTALLMENT AS STATUS_INSTALLMENT,
    UPDATED_AT_INSTALLMENT       AS DATA_STATUS_INSTALLMENT
FROM RETAIL_DEV.BACKOFFICE.AP_ORACLE_VIEW
WHERE STATUS_PAGAMENTO_INSTALLMENT = 'Totalmente paga'
  AND COALESCE(STATUS_INVOICE, '') <> 'Cancelada'
