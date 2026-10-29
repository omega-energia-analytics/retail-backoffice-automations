# jobs_adhoc

Scripts **standalone e pontuais**: extrações que alguém pediu uma vez, leitura de PDF, análises
de apoio a decisão. Cada um é autocontido, roda sozinho e não é orquestrado
por nada.

Não confunda com os itens de pasta própria ([`monitor_nff_app/`](../monitor_nff_app/),
[`faturamento_parceiros/`](../faturamento_parceiros/)): aqueles são rotina de mês; estes são
ferramenta de mão.

## Convenções

- **O número no nome é ordem histórica**, não sequência de execução. Nunca rode "de 0 a 7".
- **Todos têm `if __name__ == "__main__":`** — importar não dispara. É o que permite testá-los.
- **Nome começando com dígito não é importável** por `import` normal. Em teste, use
  `load_job("jobs_adhoc/7_extracao_nff_aegea.py")` do [`testkit.py`](../tests/testkit.py).
- **Os caminhos partem da home de quem roda** (`Path.home()` / `expanduser("~")`). Alguns ainda
  têm o caminho de outra pessoa comentado acima — é histórico, eles nasceram como script de uma
  pessoa. As seções abaixo dizem onde cada um lê e grava.
- **Para rodar, aponte o `PYTHONPATH` para `scripts/`** (ver o [README raiz](../../../README.md#como-rodar)).
  Os scripts colocam `jobs_backoffice/` no `sys.path`, não `scripts/`, e sem isso o `from utils...`
  não resolve.

## Os scripts

| # | Script | O que faz | Estado |
| --- | --- | --- | --- |
| 0 | [`0_monitoramento_total_nff.py`](0_monitoramento_total_nff.py) | Menu no terminal: registra NFFs da planilha no SQLite, consulta, e lista faturas FW atrasadas | **Substituído** pelo `monitor_nff_app` |
| 1 | [`1_crm_extraction_job.py`](1_crm_extraction_job.py) | Roda a query `crm_extraction` e salva CSV com timestamp | Funcional, genérico |
| 7 | [`7_extracao_nff_aegea.py`](7_extracao_nff_aegea.py) | Extrai ~60 campos de faturas AEGEA em PDF para Excel | Funcional, sem testes neste repo |

> **Os números 2 a 6 não estão aqui.** O RPA de distribuidora, o teste de Playwright, os RPAs de
> login CELPE/COELBA e a análise de expurgo **não vieram para este repo** (ficaram no repo de
> origem, `retail-apps`). Os buracos na numeração são isso, não arquivo perdido. Se algum deles for
> migrado, mantenha o número original e volte com a linha na tabela.

---

### 0 — Monitoramento total de NFF

**Por que existiu:** primeira automação do acompanhamento de fatura CUSD. Menu com 4 opções:
processar a planilha ADFDI para registrar NFFs enviadas (SQLite), buscar NFF, listar o banco, e
apontar faturas FW atrasadas.

**Estado:** o [`monitor_nff_app/`](../monitor_nff_app/README.md) faz tudo isso, com interface e com
muito mais tratamento de fonte de dados. Este ficou como referência histórica.

**Cuidado ao mexer:** a lista `projetos` (~83 usinas com prazo e forma de recebimento) está
**duplicada** aqui e no `monitor.py` do app. A fonte de verdade é a do app. Este script também usa
`format='%d/%m/%Y'` estrito na data de apresentação e cruza só o monitoramento — por isso ele acusa
"atrasada" onde o app já sabe que a fatura chegou por outro caminho. Não use este número em reunião.

Caminhos: `~\Faturas Oracle\` (planilha e SQLite), sobrescrevíveis pelas mesmas env vars do app
(`MONITOR_NFF_ARQUIVO_EXCEL`, `MONITOR_NFF_DB_PATH`). Não lê o `settings.json` do app — se você
trocou o caminho pela UI do Monitor NFF, aqui precisa da env var.

---

### 1 — Extração do CRM

Executa a query `crm_extraction` (registrada no `conf_cusd_invoices.yml`) e grava
`crm_extraction_<timestamp>.csv` **no diretório de onde você chamou o script**.

**Quando usar:** alguém pediu "me manda a base do CRM". Para mudar o que sai, edite o
[`sql/stg_crm_extraction.sql`](../../sql/stg_crm_extraction.sql) — não o Python.

```powershell
python scripts\jobs_backoffice\jobs_adhoc\1_crm_extraction_job.py
```

Precisa de VPN + SSO Snowflake. **O CSV gerado tem dado de cliente** — rode de uma pasta fora do
repo e nunca commite o arquivo.

---

### 7 — Extração de NFF AEGEA (PDF)

**Por que existiu:** as faturas da AEGEA vêm em PDF, várias por arquivo, e o time precisava dos
valores em planilha para conferência.

Varre os PDFs de uma pasta com PyMuPDF, quebra o texto de cada página em blocos por `CLIENTE:`, e
extrai **~60 campos por bloco** via regex: identificação, tributos (ICMS/PIS/COFINS com base,
alíquota e valor), medição, consumo, consumo compensado, devolução de geração.

**Decisões:**

- **Regex por campo, não parser de layout.** O PDF não tem estrutura confiável; cada campo é uma
  regex independente. Campo ausente devolve `""` em vez de estourar — assim uma fatura fora do padrão
  não derruba o lote inteiro, ela só vem com furos.
- **Campos `_SEC`** são a **segunda ocorrência** do campo no bloco (a fatura repete
  endereço/bairro/município na seção da instalação). Quando só há uma ocorrência, o secundário
  **repete o principal** — de propósito, para a coluna nunca vir vazia sem motivo.
- **`_clean()`** remove controle ASCII, zero-width e BOM, e normaliza NBSP: sem isso o
  `to_excel` estoura com "illegal character". Mesma função existe no `gera_nff_parceiros.py`, pela
  mesma razão.
- **Fallback de gravação:** se o `.xlsx` de destino estiver aberto no Excel (`PermissionError`), grava
  com timestamp no nome em vez de perder o processamento.

**Caminhos no `main()`**: lê de `~\Documents\AEGEA\Faturas_Piauí_Abril\Todas as Faturas` e grava
`~\Documents\AEGEA\Faturas_Piauí_Junho.xlsx`. O mês está no nome das duas — ajuste as duas linhas a
cada lote.

**Testes:** o `test_extracao_nff_aegea.py` (que cobria `_clean`, `extract` e `parse_bloco`) **não
veio para este repo**. Hoje este script não tem teste aqui; se for recriar, use o `load_job` do
[`testkit.py`](../tests/testkit.py) para importá-lo.
