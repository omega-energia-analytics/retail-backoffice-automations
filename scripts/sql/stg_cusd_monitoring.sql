-- ACRONIMO e NUMERO_DA_INSTALACAO não vão para a planilha (o schema do
-- conf_cusd_invoices.yml só escreve as colunas nomeadas em input_column). Elas existem
-- aqui para o bloqueio de usinas que não podem gerar NFF — ver `nff_bloqueados` no conf
-- e remove_usinas_bloqueadas() em app/create_quick_invoices.py. São as duas únicas
-- chaves que identificam a usina nesta fonte: sem elas o bloqueio não tem em que se
-- apoiar, e o create_quick_invoices aborta se qualquer uma faltar.
--
-- [23/11/2026] Fonte trocada de MONITORAMENTO_CUSD_AWS (lambda legado, que vai ser
-- desligada) para MONITORAMENTO_CUSD_NOVO_PIPE (flow Prefect que replica a lambda).
-- Mesmo schema (28 colunas, mesmos tipos) e mesmas 2061 chaves; nas 9 colunas lidas aqui
-- só 14 linhas divergem, todas emitidas entre 07/2023 e 02/2025 -- nos últimos 60 dias o
-- universo é idêntico (130 x 130). O que mudou na réplica é a fonte de PAGAMENTO (Oracle
-- novo pipe), coluna que o Quick Invoices não usa. Voltar atrás = trocar o nome abaixo.
SELECT
    ACRONIMO,
    NUMERO_DA_INSTALACAO,
    NOTA_FISCAL,
    CLIENTE_APELIDO,
    TO_DATE(DATA_DE_EMISSAO_DA_FATURA, 'DD/MM/YYYY') AS DATA_DE_EMISSAO_DA_FATURA,
    TO_DATE(VENCIMENTO, 'DD/MM/YYYY') AS DATA_DE_VENCIMENTO_DA_FATURA,
    DISTRIBUIDORA AS DISTRIBUIDORA_SIGLA,
    DISTRIBUIDORA_CNPJ,
    FATURA_R$ AS TOTAL_DA_FATURA
FROM RETAIL_PROD.BACKOFFICE.MONITORAMENTO_CUSD_NOVO_PIPE
WHERE TOTAL_DA_FATURA IS NOT NULL
  AND CLIENTE_APELIDO IS NOT NULL
