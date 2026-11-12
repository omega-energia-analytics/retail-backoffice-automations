# Monitor Observability — retail/backoffice

App desktop (pywebview), **somente leitura**, para acompanhar a esteira em uma janela só, com seletor de abas:

- **Deploys (GitHub Actions)** — runs dos 6 workflows de deploy (`dbt-*`, `prefect-dbt-*`, `prefect-*`): histórico, falhas, commit/PR de cada run e, nos runs com falha, o job/step e o final do log. Run verde de view = view no ar; run verde de tabela/flow = só deployment registrado.
- **Execuções (Prefect)** — flow runs com tags `retail` + `backoffice` (mesmo filtro da tela Runs do Prefect UI).

Cada aba tem um badge com o nº de deployments cujo **último run falhou**, mesmo com a aba fechada. As duas carregam na abertura; um erro de uma (ex.: Prefect sem VPN) aparece só no painel dela.

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
ui/
  index.html         abas + um <main> por monitor
  app.js             shell: abas, badges, tooltip global, boot
  github.js          módulo da aba Deploys
  prefect.js         módulo da aba Execuções
  styles.css         estilo compartilhado
```

## Para quem for mexer

- **API aninhada:** os dois monitores têm `config` e `get_runs`, então no JS são chamados como `window.pywebview.api.github.*` e `window.pywebview.api.prefect.*`. Método novo vai na classe `Api` do monitor correspondente.
- **IDs prefixados:** tudo na aba GitHub usa `gh-…` e na Prefect `pf-…` (cada módulo tem seu `$ = id => document.getElementById('gh-' + id)`). Não use `document.getElementById` direto dentro dos módulos.
- **Escopo:** cada `.js` é uma IIFE e se registra em `window.Monitors.<nome>`; o `app.js` chama `init()` de cada um. O tooltip (`data-tip`) e o badge (`window.setBadge`) ficam no shell.
- **Aba nova:** crie `<main class="view" id="view-xx">` e o `.tab` no `index.html`, um `xx.js` registrando em `window.Monitors`, e inclua o prefixo em `TABS` no `app.js`.
