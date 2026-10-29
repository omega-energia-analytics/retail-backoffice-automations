# retail-backoffice-automations

Scripts e automações em Python do **Backoffice de Retail (GD)**: geração de NFF para o Oracle,
acompanhamento de faturas CUSD, consolidação de rateio, extrações de PDF e do CRM, cargas no
Snowflake.

A ideia do repo é simples: **o que hoje mora na máquina de uma pessoa passa a morar aqui**, com
histórico, documentação e um jeito único de rodar — para que qualquer pessoa do time consiga usar,
corrigir e evoluir.

---

## O que tem aqui

| Automação | O que resolve | Onde | Doc |
| --- | --- | --- | --- |
| **Monitor NFF** (app desktop) | Por usina e por mês: a fatura CUSD chegou? no prazo? foi paga? | `scripts/jobs_backoffice/monitor_nff_app/` | [README](scripts/jobs_backoffice/monitor_nff_app/README.md) |
| **NFF de parceiros** | Preenche a planilha ADFDI do Oracle com as NFFs de Débito dos contratos de parceiros | `scripts/jobs_backoffice/faturamento_parceiros/` | [README](scripts/jobs_backoffice/faturamento_parceiros/README.md) |
| **Quick Invoices CUSD** | Preenche a planilha ADFDI com as NFFs CUSD das usinas (respeitando a lista de bloqueio) | `scripts/app/create_quick_invoices.py` | header do arquivo + [`conf`](scripts/conf/conf_cusd_invoices.yml) |
| **HistRateio** | Consolida o rateio do mês de uma distribuidora no histórico, com acrônimo e CC | `scripts/jobs_backoffice/monit_hist_usina.py` | [MONIT_HIST_USINA.md](scripts/jobs_backoffice/MONIT_HIST_USINA.md) |
| **Leitores de rateio** | Um leitor por distribuidora (CPFL Paulista, Equatorial GO), todos no mesmo formato | `scripts/jobs_backoffice/rateio/` | [README](scripts/jobs_backoffice/rateio/README.md) |
| **Diferimento** | Carga histórica e atualização do número da NFe no Snowflake | `scripts/jobs_backoffice/diferimento_historico/` | docstring dos arquivos |
| **Extrator de demonstrativos** | Extrai os dados de demonstrativos de PDF (COELBA) para planilha | `scripts/jobs_backoffice/extrator_livia.py` | — |
| **Jobs ad-hoc** | Extração do CRM, extração de NFF AEGEA em PDF, etc. Ferramentas pontuais | `scripts/jobs_backoffice/jobs_adhoc/` | [README](scripts/jobs_backoffice/jobs_adhoc/README.md) |

> **Antes de rodar ou mexer em qualquer automação, leia o README dela.** Os READMEs das pastas
> explicam o porquê das decisões — várias delas existem porque o jeito "óbvio" já quebrou em produção.

---

## Estrutura

```text
scripts/
├── app/                  # automações de faturamento CUSD (Quick Invoices, controle de pagamento)
├── conf/                 # configuração: queries registradas, de/para, lista de usinas bloqueadas
├── sql/                  # uma query por arquivo; o código chama pelo nome lógico do conf
├── utils/                # conexão Snowflake / Microsoft Graph, logs, helpers compartilhados
├── jobs_backoffice/      # os jobs do time (ver tabela acima)
│   └── tests/            # testes dos jobs
├── notebooks/            # exploração e material de estudo (notebooks não são versionados)
└── paths.py              # resolve conf/ e sql/ a partir de qualquer pasta
```

Dois combinados que valem para o repo todo:

- **Query é arquivo `.sql` em `scripts/sql/`, registrada por nome em `conf/conf_cusd_invoices.yml`.**
  O Python pede `get_query("crm", ...)` e nunca carrega SQL inline. Para mudar o que uma extração
  traz, edite o `.sql`, não o Python.
- **De/para e listas de negócio ficam no `conf`**, não espalhados no código (unidade de negócio,
  fornecedor, usinas que nunca geram NFF).

---

## Primeiro setup

### O que você precisa

- **Windows** com **Excel** instalado (vários jobs escrevem na planilha via `xlwings`).
- **Python 3.11+**.
- **VPN** ligada para tudo que consulta o Snowflake.
- Acesso ao **Snowflake** pelo SSO corporativo — na primeira consulta o navegador abre para você
  logar. É esperado.
- Para os jobs que sobem NFF: **add-in ADFDI do Oracle** instalado e logado no Excel.

### Passo a passo

```powershell
# 1. Clone e entre no repo
git clone <url-do-repo>
cd retail-backoffice-automations

# 2. Crie e ative um ambiente virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Instale as dependências
pip install -r requirements.txt
```

> Se o `Activate.ps1` for bloqueado, rode uma vez:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 4. Arquivo `.env`

As credenciais ficam em **`scripts/jobs_backoffice/.env`**, que **não vai para o git**. Peça os
valores para alguém do time e crie o arquivo com estas chaves:

```ini
# Microsoft Graph (SharePoint / OneDrive)
TENANT_ID=
CLIENT_ID=
CLIENT_SECRET=
DRIVE_ID=
API_TOKEN=

# Snowflake
SF_ACCOUNT=
SF_USERNAME=
SF_PASSWORD=
SF_WAREHOUSE=
SF_DATABASE=
SF_SCHEMA=
```

Nunca cole esses valores em código, notebook, print ou mensagem.

### 5. Caminhos locais (só se o seu for diferente)

Os scripts montam os caminhos a partir da **home de quem roda** (`C:\Users\<você>\...`), então em
geral não há nada a fazer. Se a sua pasta estiver em outro lugar, defina a variável de ambiente
correspondente **uma vez** (com `setx`, e reabra o terminal/VSCode):

| Variável | Default | Usada por |
| --- | --- | --- |
| `BACKOFFICE_GD_DIR` | `~\Serena\Comercializadora - OMG\03 - BackOffice\13 - Geração Distribuída\Acompanhamento - Operação GD` | `monit_hist_usina.py`, `extrator_livia.py` |
| `MONITOR_NFF_ARQUIVO_EXCEL` | `~\Faturas Oracle\CreateQuickInvoices.xlsm` | `monitor_nff_app`, `0_monitoramento_total_nff.py` |
| `MONITOR_NFF_DB_PATH` | `~\Faturas Oracle\controle_nff.db` | `monitor_nff_app`, `0_monitoramento_total_nff.py` |

O nome da pasta sincronizada do SharePoint varia conforme a pessoa sincronizou (ex.:
`Comercializadora - Comercializadora\OMG\...`) — esse é o caso típico do `BACKOFFICE_GD_DIR`:

```powershell
setx BACKOFFICE_GD_DIR "C:\Users\<você>\Serena\<sua pasta>\...\Acompanhamento - Operação GD"
```

---

## Como rodar

Todos os scripts importam a partir da pasta `scripts/` (`from utils...`, `from paths...`). Para
isso funcionar de qualquer lugar, aponte o `PYTHONPATH` para ela **uma vez por terminal**:

```powershell
$env:PYTHONPATH = (Resolve-Path .\scripts).Path
```

Depois é só rodar o arquivo:

```powershell
python scripts\jobs_backoffice\monitor_nff_app\main.py
python scripts\jobs_backoffice\faturamento_parceiros\gera_nff_parceiros.py
```

Muitos scripts têm um **bloco de configuração no topo** (mês de referência, distribuidora, pasta de
entrada). Confira esse bloco antes de rodar — e veja a seção abaixo antes de commitar a alteração.
Os caminhos já partem da sua home; se algum não bater, veja [Caminhos locais](#5-caminhos-locais-só-se-o-seu-for-diferente).

### Testes

```powershell
python -m pytest scripts\jobs_backoffice\tests -v
python -m pytest scripts\jobs_backoffice\monitor_nff_app\tests -v
```

Os testes não acessam Snowflake, Graph nem os seus arquivos reais. Rodam offline.

---

## Dados sensíveis: o que nunca vai para o git

Muitos destes jobs leem ou geram **dado de cliente** (CPF/CNPJ, UC, login de portal, valores de
fatura). A regra é: **o repo guarda código e configuração; dados ficam fora.**

Nunca commite:

- o `.env` ou qualquer credencial;
- planilhas (`.xlsx`, `.xlsm`), CSVs, PDFs de fatura e bancos SQLite (`.db`) — insumos e saídas
  ficam no OneDrive/SharePoint ou na sua máquina;
- notebooks com saída de consulta (`.ipynb` já é ignorado).

Antes de cada commit, olhe o que está indo:

```powershell
git status
git diff --staged --stat
```

Se aparecer arquivo de dado na lista, tire com `git restore --staged <arquivo>` e, se for um tipo
novo, adicione ao `.gitignore`.

---

## Contribuindo

1. Crie uma branch a partir da `develop`: `git checkout -b feat/<o-que-voce-esta-fazendo>`.
2. Faça a mudança. Se for automação nova, **crie uma pasta em `jobs_backoffice/` com um README**
   dizendo: o que resolve, de onde lê, onde escreve, como rodar e o que pode dar errado.
3. Rode os testes.
4. Abra um PR para a `develop` e peça revisão de alguém do time.

Script pontual, que vai rodar uma vez só? Vai em `jobs_adhoc/` — mas também com uma linha na
tabela do [README de lá](scripts/jobs_backoffice/jobs_adhoc/README.md).

### Mudou o caminho da sua máquina?

**Não escreva `C:\Users\<seu usuário>\...` no código** — o próximo que puxar vai rodar com o seu
caminho. Monte a partir da home (`Path.home()` / `os.path.expanduser("~")`) e, se a pasta puder
variar entre pessoas, deixe uma variável de ambiente sobrescrever o default
(`os.getenv("X") or <default>`), e registre-a na tabela de [Caminhos locais](#5-caminhos-locais-só-se-o-seu-for-diferente).
