# Monitor Observability — retail/backoffice

App desktop (pywebview), **somente leitura**, para acompanhar a esteira em uma janela só, com seletor de abas:

- **Deploys (GitHub Actions)** — runs dos 6 workflows de deploy (`dbt-*`, `prefect-dbt-*`, `prefect-*`): histórico, falhas, commit/PR de cada run e, nos runs com falha, o job/step e o final do log. Run verde de view = view no ar; run verde de tabela/flow = só deployment registrado.
- **Execuções (Prefect)** — flow runs com tags `retail` + `backoffice` (mesmo filtro da tela Runs do Prefect UI).
- **KPIs (CUSD)** — os dois KPIs da CUSD das usinas, por mês, com a lista do que puxou cada um para baixo:
  - **KPI 1 · % do valor das NFFs lançadas pela automação** (meta ≥ 90%): NFF do Oracle cruzada com o log do quickinvoices (`app/quick_invoices_log.py`). Automação = está no log com o mesmo valor; ajustada = está no log com outro valor; manual = não está em log nenhum. Meses antes do primeiro log aparecem como "sem log".
  - **KPI 2 · faturas não pagas no prazo** (meta ≤ 2): pagas depois do vencimento da distribuidora + vencidas sem pagamento, pelo mês do vencimento. Cada atraso vem com a causa (NFF lançada após o vencimento, vencimento do Oracle diferente do FattureWeb, sem NFF, pago parcial).

GitHub e Prefect têm um badge com o nº de deployments cujo **último run falhou**, mesmo com a aba fechada, e carregam na abertura; um erro de uma (ex.: Prefect sem VPN) aparece só no painel dela. A aba **KPIs só carrega quando é aberta** (o login do Snowflake abre no navegador) e o badge dela é o nº de faturas vencidas sem pagamento.

## Como rodar

```powershell
python main.py            # abre a janela
python main.py --debug    # abre com DevTools
```

Requisitos: `pywebview` instalado.

| Aba | Acesso |
| --- | ------ |
| GitHub | `GITHUB_TOKEN`/`GH_TOKEN` com leitura em Actions **ou** GitHub CLI logado (`gh auth login` uma vez) |
| Prefect | VPN (FortiClient) conectada. Sem autenticação |
| KPIs | VPN + `requirements.txt` da raiz + `jobs_backoffice/.env` (Snowflake por SSO no navegador; Graph para ler os logs no SharePoint) |

GitHub e Prefect rodam só com `pywebview` + stdlib: os imports de dados da aba KPIs ficam dentro dos métodos, para que a falta deles não impeça as outras abas de abrir.

O `monitor_prefect.py` também roda sozinho como CLI (só stdlib):

```powershell
python monitor_prefect.py --mes 2026-11
python monitor_prefect.py --watch 5      # atualiza a cada 5 min, bipa em falha nova
```

## Estrutura

```text
main.py              cria a janela e injeta Api
api.py               Api com dois sub-objetos: api.github e api.prefect
github_api.py        consulta a API REST do GitHub Actions
prefect_api.py       ponte para monitor_prefect.py
monitor_prefect.py   busca na API do Prefect (também é o CLI)
kpi_api.py           aba KPIs: carregar_base() do monitor_nff_app + logs do SharePoint, em cache
kpis.py              regra dos KPIs, pura (testes em jobs_backoffice/tests/test_kpis_cusd.py)
ui/
  index.html         abas + um <main> por monitor
  app.js             shell: abas, badges, tooltip global, boot (abas LAZY só no 1º clique)
  github.js          módulo da aba Deploys
  prefect.js         módulo da aba Execuções
  kpis.js            módulo da aba KPIs
  styles.css         estilo compartilhado
```

## Para quem for mexer

- **API aninhada:** os dois monitores têm `config` e `get_runs`, então no JS são chamados como `window.pywebview.api.github.*` e `window.pywebview.api.prefect.*`. Método novo vai na classe `Api` do monitor correspondente.
- **IDs prefixados:** tudo na aba GitHub usa `gh-…` e na Prefect `pf-…` (cada módulo tem seu `$ = id => document.getElementById('gh-' + id)`). Não use `document.getElementById` direto dentro dos módulos.
- **Escopo:** cada `.js` é uma IIFE e se registra em `window.Monitors.<nome>`; o `app.js` chama `init()` de cada um. O tooltip (`data-tip`) e o badge (`window.setBadge`) ficam no shell.
- **Aba nova:** crie `<main class="view" id="view-xx">` e o `.tab` no `index.html`, um `xx.js` registrando em `window.Monitors`, e inclua o prefixo em `TABS` no `app.js` (e em `LAZY`, se ela não puder carregar na abertura).
- **KPIs — a base é a do monitor de NFF, sem query própria.** O `kpi_api` chama `monitor_nff_app/monitor.carregar_base()` e aplica `monitor.pagamento_efetivo()` em todas as linhas. Universo (`PROJETOS` FW/E-MAIL), NFF, "Pago", data de pagamento, Valor Oracle e fatura zerada são os do painel do monitor — conciliado em 12/11/2026: 850 linhas do painel com NFF (jan–nov/2026), zero diferença. Regra de pagamento mudou? Muda no monitor e vale para os dois. Não crie query paralela: foi a primeira versão e já divergia em caso de borda.
- **KPIs — regra dos indicadores só no `kpis.py`.** O JS só exibe. Mudou definição (ex.: contar "ajustada" como automação, mudar a meta)? É ali, com teste. O header do arquivo descreve cada regra.
- **KPI 2 conta pelo prazo da distribuidora** (vencimento do FattureWeb), não pelo vencimento do Oracle. Em 2026 isso faz diferença: 146 das 181 faturas pagas com atraso estavam dentro do vencimento do Oracle, que ficou depois do da distribuidora. É de propósito — multa e juros vêm do prazo da distribuidora.
