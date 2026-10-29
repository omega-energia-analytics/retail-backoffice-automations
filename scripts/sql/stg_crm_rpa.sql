-- Identifica UCs ativas com falha de pagamento recente (2026+),
-- trazendo apenas o registro mais recente por UC.

SELECT 
    s.DATA,
    s.STATUS,
    c.status_uc,
    c.unidade_consumidora,
    c.distribuidora,
    c.produto,
    c.link_da_distribuidora, 
    c.login_distribuidora, 
    c.senha_distribuidora,
    s.VALOR_TOTAL,
    s.BAR_CODE,
    s.PIX_CODE

FROM RETAIL_PROD.BACKOFFICE.CRM c

-- Join com histórico de pagamentos pelo número da UC
INNER JOIN RETAIL_PROD.BACKOFFICE.STATUS_PAGAMENTO_HISTORICO s
    ON s.UNIDADE_CONSUMIDORA = c.unidade_consumidora

WHERE
    -- Apenas falhas de pagamento relevantes para reprocessamento
    s.STATUS IN ('recusado pelo banco', 'sem código de barras')
    -- Ignora UCs canceladas ou inativas
    AND c.STATUS_UC = 'Ativo(a)'
    -- Limita ao ano corrente (DATA está em texto, precisa converter)
    AND YEAR(TRY_TO_DATE(s.DATA, 'DD/MM/YYYY')) >= 2026

-- De todos os registros de falha por UC, mantém só o mais recente
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY s.UNIDADE_CONSUMIDORA
    ORDER BY TRY_TO_DATE(s.DATA, 'DD/MM/YYYY') DESC
) = 1

ORDER BY c.unidade_consumidora, TRY_TO_DATE(s.DATA, 'DD/MM/YYYY') ASC
