-- Mesmo papel do stg_query_monitor_cusd_job.sql (ancora nota -> acronimo da usina),
-- lendo a USINAS_GERACAO em vez da MONITORAMENTO_CUSD_AWS.
--
-- Por que trocar: o PAGAMENTO daqui vem da V_AP_ORACLE_NOVO_PIPE casado por NOTA
-- FISCAL, enquanto o da CUSD completa por VALOR da fatura quando a nota nao casa.
-- Nos meses recentes isso inverte a cobertura a favor desta fonte -- ago/2026:
-- 70 pagamentos aqui contra 21 na CUSD; set/2026: 21 contra 1.
--
-- O que se perde (medido em 15/10/2026): ~45 pares nota/acronimo que so a CUSD tem,
-- quase todos de 2024/2025 (2 em set/2026), e ~43 pagamentos de jan-jul/2026 que a
-- CUSD preenche por valor -- jun/2026 sao 14 faturas CPFL com a MESMA data (30/07)
-- e nota que nao existe no Oracle, ou seja, inferencia e nao pagamento conferido.
-- Nada disso atinge o mes vigente nem o anterior.
--
-- UPLOADED_AT nao existe nesta base e nao era usado pelo monitor (a query da CUSD
-- trazia e o pandas descartava), entao saiu.
--
-- DISTRIBUIDORA_SIGLA e o nome da coluna aqui; na CUSD era DISTRIBUIDORA. O filtro
-- tem o mesmo efeito: descarta o par usina/mes sem fatura casada.
--
-- As datas saem como DATE (na CUSD eram texto dd/mm/yyyy). O _to_naive do monitor
-- ja aceita os dois formatos, entao nao ha mudanca no Python.
--
-- [28/10/2026] Apontado para RETAIL_PROD: o build com PAGAMENTO (stg_02/stg_05) subiu.
SELECT ACRONIMO, NOTA_FISCAL, DATA_DA_APRESENTACAO_DA_FATURA, PAGAMENTO
FROM retail_prod.backoffice.usinas_geracao
WHERE DISTRIBUIDORA_SIGLA IS NOT NULL
