# Testes — Monitor NFF

Testes unitários do app `monitor_nff_app`. Cobrem **lógica pura e a camada
SQLite**, sem rede: nada aqui toca Snowflake, Microsoft Graph nem o
`controle_nff.db`/`settings.json` reais do usuário (tudo é redirecionado pra
`tmp_path`).

## Como rodar

A partir de `scripts/jobs_backoffice/monitor_nff_app/`:

```bash
python -m pytest tests/ -v
```

O `conftest.py` insere o diretório do app no `sys.path` pra suportar os imports
"flat" do app (`import config`, `import db`, `import monitor`).

## O que cada arquivo protege

| Arquivo | Alvo | Invariante protegida |
|---|---|---|
| `test_config.py` | `config.get/set_many/como_dict` | Cascata de prioridade **env > settings.json > default**; valores `""`/`None` ignorados; settings.json corrompido não derruba o app; `set_many` cria pasta e faz merge sem sobrescrever com `None`. |
| `test_db.py` | `db.*` (SQLite) | `INSERT OR IGNORE` não conta nem sobrescreve NFF duplicada; `init_db` cria pasta+tabela; `nffs_existentes` retorna `set`; `listar_todas` ordena por `data_envio` desc. |
| `test_monitor.py` | `monitor._to_naive`, `_fmt_uc`, `_status`, `_dias_para_vencer`, `montar_mes`, `listar_meses`, `_prep_pag`, `_prep_inst`, `_carregar_pagamentos` | `_to_naive`: remove timezone (regressão AP_ORACLE_VIEW tz-aware), `dayfirst`, inválidos viram `NaT`. `_fmt_uc`: tira `.0` de float, preserva string, `NaN`→`None`. `_status`: Chegou / Chegou atrasada / Pendente / Atrasada (incl. limites `<=` e `>=` hoje). `_dias_para_vencer`: sinal correto e `None` se já chegou. `montar_mes`: recorta o mês pedido **pela `DATA_CHEGADA`** (default = corrente), `Data Esperada` relativa ao mês escolhido, status medido contra hoje (fatura de mês passado que não chegou → Atrasada), `Pago` combina as **três** fontes (AP_PAYMENTS + monitoramento + status da parcela do Oracle) com a precedência certa, `Competência`/`Faturas no Mês`/`NFF Adicionais` preenchidas, `Valor Oracle`/`Divergência Valor` expõem as duas pontas do valor (e ficam vazias quando a fatura não está no Oracle), e mês sem nenhuma fatura não estoura. `listar_meses`: inclui o mês corrente e ordena desc. |

### Cascata de pagamento (3 degraus)

`Pago` é um **OR** de três fontes, nunca um AND — elas divergem nos dois sentidos. A precedência
define de qual sai a `Data Pagamento`, e `Fonte Pagamento` registra qual respondeu:

| # | Fonte | Coluna | `Fonte Pagamento` | Data |
|---|---|---|---|---|
| 1 | `AP_PAYMENTS` via ap_oracle_view | `DATA_DE_PAGAMENTO` | `ORACLE_PAYMENTS` | real |
| 2 | `monitoramento_cusd_aws` | `PAGAMENTO` | `MONITORAMENTO` | real |
| 3 | `AP_INSTALLMENTS` via ap_oracle_view | `STATUS_INSTALLMENT` | `ORACLE_INSTALLMENT` | **aproximada** (`UPDATED_AT` da parcela) |

O degrau 3 é o mais novo e cobre o caso em que o Oracle quita a parcela mas o pagamento não
chega em `AP_PAYMENTS` (jun/2026: 2.372 faturas; 4 das 6 usinas do mês apareciam como "A pagar"
já pagas). Os testes cobrem: pago só pela parcela, parcela 'Não paga' segue a pagar, parcela paga
**sem** data ainda conta como pago, aditividade (data real vence a aproximada) e o df chegando
**sem** as colunas do degrau 3 (view ainda não rebuildada → degrau desligado, comportamento
anterior preservado).

### De/para de UC por endereço (`_depara_uc_por_endereco`)

Terceira fonte do de/para `UC → ACRONIMO`, depois de (1) `monitoramento_hist_usina` e (2)
aprendizado do próprio `df_merged`. Resolve **UC que troca de código na distribuidora**: a CPFL
migrou pro padrão ANEEL na competência 06/2026 — as UCs antigas (`4003…`, 10 díg.) param em maio,
as novas (`55x/56x`, 12 díg.) começam em junho. Sem de/para, a fatura não pode ser posicionada no
projeto e a usina aparece como falso "Atrasada" sem NFF.

**Todas as fontes de de/para foram checadas e estão vazias** (28/07/2026):

| fonte | por que não serve |
|---|---|
| `monitoramento_hist_usina` | só tem UC de 7 a 11 dígitos, nenhuma de 12 |
| `FATTUREWEB_INSTALACOES.CODIGO_ANTIGO` | 8.831 instalações CPFL, **zero** preenchidas |
| `CONSUMER_UNIT_ALIAS` (SIGMA, legacy↔canon) | 51.816 canon-codes, mas só UC de **cliente** — nenhuma de geradora |
| `FATTUREWEB_USINAS.CONTRATO` | preenchido só até competência 08/2025 |
| Oracle `UNIDADE_CONSUMIDORA` / `DESCRIPTION` | vazios nessas notas |

O que sobrou e resolve: o **`ENDERECO`** que o FattureWeb já traz. Ele é idêntico antes e depois da
troca — é a mesma usina no mesmo lugar. A UC antiga (que tem acrônimo) empresta o acrônimo pro
endereço, e a UC nova herda. Nenhuma fonte nova entra no pipeline.

Duas salvaguardas — na dúvida a usina segue sem fatura, nunca exibindo a fatura de outra:

1. endereço que aponta pra mais de um acrônimo fica de fora (**SP-ATN-01 e SP-ATN-02 dividem
   literalmente o mesmo endereço** em Morro Agudo);
2. UC cujos endereços levem a acrônimos diferentes também fica de fora.

A normalização é **leve de propósito** (caixa, bordas, espaços repetidos) e **não** toca
pontuação: `TP - TP -` e `TP TP` são endereços de usinas diferentes em Morro Agudo, e achatar isso
colaria as duas. O endereço também desambigua casos finos — em Araraquara, `CRT 166A` é a
SP-ARQ-03 e `CRT 166B` a SP-ARQ-04.

Alcance medido: **24 UCs resgatadas** (CPFL 15 de 16, Equatorial GO 7, EMT 1, CEMIG 1), 4
endereços ambíguos descartados. No painel de julho/2026 isso tira **9 das 11 usinas CPFL** do
falso "Atrasada" — sobram SP-ATN-01 e SP-ATN-02, pela salvaguarda 1.

### Duas cascatas de data (`_cascata_datas`)

`DATA_REFERENCIA` e `DATA_CHEGADA` respondem perguntas **diferentes** e antes compartilhavam a
mesma resposta (`Data Chegada` era literalmente a `DATA_REFERENCIA`):

| | pergunta | ordem dos degraus |
|---|---|---|
| `DATA_REFERENCIA` | de que **mês** é esta fatura? | apres_mon → apres_fw → **competência** → lançamento Oracle |
| `DATA_CHEGADA` | **quando** ela chegou? | apres_mon → apres_fw → **emissão FW** → lançamento Oracle |

- No **mês**, a competência vem antes do `INVOICEDATE` porque este é data de *lançamento
  contábil*. Pra distribuidora com lag de emissão (CELPE: ~40-47 dias) ele jogava a fatura no mês
  seguinte — competências 05 e 06 caíam as duas em julho, o mês de competência ficava vazio (falso
  "Atrasada" sem NFF) e o seguinte recebia duas faturas do mesmo acrônimo, onde o
  `groupby('ACRONIMO').tail(1)` descartava uma. Eram **17 faturas invisíveis** em 2026 (CELPE 12,
  COELBA 4, CEPISA 1).
- Na **chegada** entra a emissão e a competência **não** entra: competência é sempre dia 1º, seria
  data de chegada falsa.

Quem preenche apresentação (CPFL, Equatorial…) para no 1º/2º degrau nas duas cascatas — **nada
muda pra essas distribuidoras**. Impacto medido em 28/07/2026: mudam de mês CELPE 80, COELBA 74,
CEMIG 11; CPFL Paulista **zero**.

### A aba do mês é a de CHEGADA (`montar_mes`)

O recorte de mês usa **`DATA_CHEGADA`**, não `DATA_REFERENCIA`. O painel responde uma pergunta
operacional — "o que eu tinha pra receber neste mês?" — e o `Dia` de `PROJETOS` **sempre foi
calibrado pro mês em que a fatura chega**. Recortar pela `DATA_REFERENCIA` (que para
CELPE/COELBA/CEMIG é a competência) cobrava a fatura no mês da competência, e essas distribuidoras
emitem 31–57 dias depois dela.

Medido nas 205 faturas de histórico das 12 usinas CELPE/COELBA/CEMIG:

| âncora do prazo | no prazo |
|---|---|
| competência | **0 de 205 — 0,0%** |
| chegada | **134 de 205 — 65,4%** |

Os 0,0% eram artefato da âncora, não régua apertada — **o `Dia` não precisa de recalibração**. O
sintoma era a aba do mês corrente sempre vazia e vermelha: em 29/07/2026 julho mostrava 12
"Atrasada" com NFF/UC em branco enquanto as 12 faturas já tinham chegado (01/07 a 17/07), **todas
dentro do prazo** e 8 pagas, arquivadas na aba de junho como "Chegou atrasada".

Validação contra dado real, histórico inteiro (01/2025–07/2026), comparando com o `montar_mes`
anterior sobre a MESMA base:

| verificação | resultado |
|---|---|
| project-meses fora das 12 usinas com qualquer diferença de NFF/Status | **0 de 1.273** (aditivo pra CPFL/Equatorial/Enel) |
| notas rastreadas (linha principal + `NFF Adicionais`) | 1.359 → **1.404** (+45, −0) |
| notas sem rastro nenhum | 45 → **0** |
| project-meses que deixaram de exibir uma nota | 10, **todas** reencontradas no mês de chegada |
| aba de 07/2026 nas 12 usinas | 12 "Atrasada" sem NFF → 12 **"Chegou"** com NFF |
| Status das 12 no histórico | Chegou 0→**128**, Chegou atrasada 186→60, Atrasada 42→40 |

Colunas **aditivas** que entraram junto (no fim da lista, consumidores leem por nome):

- **`Competência`** (MM/AAAA) — identifica *qual* fatura é a linha agora que a aba é por chegada, e
  é comparando competência entre meses que se enxerga uma **pulada** (uma visão por chegada não
  acusa isso sozinha).
- **`Faturas no Mês`** + **`NFF Adicionais`** — o painel é uma linha por projeto/mês, então uma 2ª
  fatura chegando no mesmo mês ficava invisível no `groupby('ACRONIMO').tail(1)`. Acontece de
  verdade: a **BA-BAR-01 recebeu três faturas em maio/2026** (competências 02, 03 e 04, duas delas
  cobrança atrasada emitida 26/05 e ausente do Oracle). A linha exibida continua sendo a de
  competência mais recente; as outras agora deixam rastro.

Caso de referência (PE-VEN-01, competência 06/2026): chegou 10/07, paga 14/07, prazo dia 20.
Aparece em **julho** como **"Chegou"** (10/07 ≤ 20/07) e paga. Antes da troca de âncora caía em
junho como "Chegou atrasada" (10/07 vs 20/06) e julho ficava com uma linha "Atrasada" em branco.

**Limitação pré-existente que isso não resolve:** `PROJETOS` não tem data de entrada em operação da
usina, então mês anterior à 1ª fatura marca "Atrasada" nas duas âncoras (30 → 39 project-meses, todos
em 2025 e concentrados nas usinas que começaram a faturar no meio do ano — PE-GRA-01 só tem fatura
a partir de 12/2025). Some a partir de 12/2025.

### 2º passe de chave (`_nf_key` / `_completar_por_chave_normalizada`)

A NFF passa por float em algum ponto do caminho (ganha `.0`, perde o zero à esquerda) e as pontas
**não sujam igual**, então o merge exato às vezes não acha a nota — ou acha a errada. Caso real
(GO-MNU-01, jun/2026): o monitoramento guarda `194412037`, e no Oracle esse número exato é uma
nota **Cancelada de valor 0**; a nota boa, paga, está como `194412037.0`.

`_nf_key` trata `42937901.0`, `042937901` e `42937901` como a mesma nota. O merge exato continua
mandando — o 2º passe só preenche o que ficou vazio, então é estritamente aditivo. Duas
salvaguardas, ambas testadas:

1. **Só disputa a chave quem informa algo.** Linha de origem sem nenhuma das colunas de interesse
   não candidata. É o que resolve a GO-MNU-01: a nota Cancelada não tem pagamento nem status de
   parcela, sai da disputa, e a chave deixa de ser ambígua.
2. **Chave que ainda aponta pra 2+ notas é descartada inteira.** Ficar sem pagamento é bem menos
   grave que exibir o pagamento de outra fatura.

Medido em 28/07/2026 sobre as 1.772 notas do monitoramento: **5 notas ganham pagamento** (das
quais 2 dependem exclusivamente da normalização — GO-MNU-01 pelo `.0` e SP-ARQ-03 `028315077` →
`28315077` pelo zero à esquerda; as outras 3 já casavam exato) e **nenhuma** chave ambígua chega
a ser usada — as 2.663 ambíguas existem no Oracle inteiro (~1M notas) e nenhuma toca o
monitoramento.

Só as colunas de **pagamento** entram no 2º passe. `DATA_INVOICE` fica de fora de propósito: ela
alimenta a cascata de `DATA_REFERENCIA`, e completá-la **moveria faturas de mês** no painel — não
seria aditivo, e é decisão separada.

### Leitura de pagamentos: uma query recortada (`_carregar_pagamentos`)

O startup do app demorava porque a `AP_ORACLE_VIEW` era lida **duas vezes, inteira**. Medido em
05/08/2026:

| query | linhas trafegadas | usadas |
|---|---|---|
| `stg_pagamentos.sql` | 1.004.303 | 1.113 |
| `stg_pagamentos_installment.sql` | 975.691 | ≤1.113 |

O `WHERE STATUS_PAGAMENTO_INSTALLMENT = 'Totalmente paga'` não filtrava nada — são **97%** da view
(975.691 de 1.004.303). E a `ap_oracle_view` é `materialized='view'` sobre três
`QUALIFY ROW_NUMBER()` (AP_INVOICES / AP_INSTALLMENTS / AP_PAYMENTS), ou seja, recalculada duas
vezes por abertura. `stg_pagamentos_usinas.sql` resolve as duas coisas: recorta no servidor e
devolve os dois blocos numa leitura só — **1.113 linhas**.

**Não era o tamanho do histórico.** Cortar de 01/2025 pra frente resolveria pouco: 580.959 das
1.004.303 linhas já são `>= 2025` (42% de corte, e só de uma das duas queries). E `INVOICEDATE` é
`TEXT` de formato misto (`2026-05-04 11:31:08` e `2026-07-21T00:00:00Z`), então filtro de data ali
é frágil. O desperdício era de **escopo**: 99,9% das linhas não eram de nota de usina.

O recorte é pelas notas que o monitor consegue casar — `monitoramento_cusd_aws` ∪
`fattureweb_usinas` dos consórcios GD — e pela **chave normalizada** (`_nf_key`: tira `.0` e zero à
esquerda), não por igualdade: das 1.113 linhas, **107 só casam depois de normalizar**. Saída
idêntica à de antes, e a medição do 2º passe de chave (acima) mostra por quê: as 2.663 chaves
ambíguas vivem todas fora do universo do monitoramento, então reduzir o escopo não muda nem
ambiguidade nem pagamento exibido.

`stg_pagamentos.sql` **não foi tocado** — é compartilhado com a lambda `monitoramento_cusd` (PROD) e
com o `main_pagamento_usinas.py`, que precisam da AP inteira. As duas queries antigas seguem no
`conf` como **fallback**: se a recortada falhar (colunas de parcela ainda não na view, grant
faltando em `MONITORAMENTO_CUSD_AWS`), o monitor volta ao caminho anterior em vez de ficar sem
pagamento. Ambos os caminhos testados, incluindo o pior caso (recorte **e** parcela indisponíveis).

| helper | invariante protegida |
|---|---|
| `_prep_pag` | devolve **só** `COLS_PAG` — se `STATUS_INSTALLMENT` vazasse pro `df_pag`, o merge do `df_inst` criaria `_x`/`_y` e o 3º degrau parava de ser lido; e `na_position='first'` elege a linha **paga** quando a nota repete |
| `_prep_inst` | guarda só a evidência positiva (`Totalmente paga`); no caminho antigo é no-op, no recortado é o que separa as linhas; nota nula fora |
| `_carregar_pagamentos` | 1 leitura quando a recortada está disponível; fallback pras 2 queries antigas na ordem certa; `df_inst` vazio **com as colunas certas** no pior caso |

### Valor da fatura: FattureWeb vs Oracle (`Valor Oracle` / `Divergência Valor`)

O `INVOICEAMOUNT` do Oracle já vinha na query de pagamento (como `FATURA_VALOR`) e morria em
`_prep_pag` — nunca chegava à saída. Passou a ser exibido porque as duas pontas discordam sem aviso:
NFF `047744547` vale `19.142,04` no FattureWeb e `7.525,59` no Oracle, e como o ✓ de `Pago` vem do
Oracle enquanto o valor exibido vinha do FattureWeb, o painel sugeria que os 19.142,04 tinham sido
quitados.

Casos cobertos, e o que cada um protege:

| caso | invariante |
|---|---|
| valores divergentes | as duas colunas saem preenchidas, `Divergência Valor` = FW − Oracle (11.616,45), e o `Pago` continua sendo reportado — a divergência **informa**, não invalida o pagamento |
| valores iguais | diferença `0.0`, pra UI não marcar ⚠ em fatura correta |
| sem `FATURA_VALOR` na base | fatura ainda não lançada no Oracle (ou fixture antiga sem a coluna) sai com as duas vazias, **não** como divergência do total inteiro — senão todo mês novo apareceria vermelho |
| total do FW em texto BR (`'19.142,04'`) | a divergência é calculada (11.616,45) e o `Total Fatura` exibido continua o texto da fonte. É como o dado chega de verdade — os casos acima usam float e por isso passavam enquanto, em produção, `pd.to_numeric` devolvia `NaN` e a divergência nunca aparecia |

`_dinheiro` tem teste próprio com os formatos que a conversão precisa aceitar: `'32810,15'`,
`'1.234,56'`, `'0,0'`, `'7525.59'`, float, e vazio/ilegível virando `NaN`.

### Fatura zerada (`Fatura Zerada`)

Fatura de valor zero não tem o que pagar (out/2026, duas usinas Equatorial GO). Dois casos:

| caso | invariante |
|---|---|
| `TOTAL_DA_FATURA = '0,0'`, sem pagamento | `Fatura Zerada` verdadeiro, `Pago` **continua falso** (não houve pagamento) e o `Status` de chegada não muda |
| sem `TOTAL_DA_FATURA` | `Fatura Zerada` falso — total desconhecido não é zero, a fatura segue "A pagar" |

**O valor também depende do 2º passe de chave.** Na primeira versão da coluna, toda NFF com
**zero à esquerda** aparecia paga com `Valor Oracle` vazio — visível no painel como um padrão
limpo: só as NFF sem zero traziam valor. Causa: o merge exato falha nessas notas (`047744547` no
monitoramento, `47744547` no Oracle) e quem as recupera é o passe normalizado, que estava
completando **só** `DATA_DE_PAGAMENTO`.

O `FATURA_VALOR` é completado em chamada **separada** da data, e isso é o ponto delicado: a
salvaguarda 1 do `_completar_por_chave_normalizada` só deixa disputar a chave quem informa alguma
das colunas pedidas, e `FATURA_VALOR` vem preenchido em **toda** linha de AP — inclusive na nota
Cancelada do GO-MNU-01, hoje eliminada justamente por não ter pagamento nem parcela. Na mesma
chamada ela voltaria à disputa, a chave viraria ambígua e o pagamento que hoje é recuperado se
perderia. Há teste para as duas formas, provando a diferença. Em chamada própria o pior caso fica
contido no valor: chave ambígua descarta o **valor** (fica `—`, investigável) sem tocar na data.

## Fora de cobertura (por enquanto)

- **`carregar_base()` / `consultar_faturas()`** — orquestram Snowflake + Graph
  (rede + VPN). Exigiriam mocks pesados; ficam pra um passo de integração
  separado. O recorte de mês em si (`montar_mes`/`listar_meses`) foi extraído
  como função pura justamente pra ser testável sem rede. A leitura de pagamentos
  saiu dessa lista: `_carregar_pagamentos` é testada com `read_sql` falso.
- **`api.py`** (camada pywebview) e **`main.py`** (bootstrap da janela).

> Nota: `_fmt_uc`, `_status` e `_dias_para_vencer` eram funções aninhadas dentro
> de `consultar_faturas()`; foram extraídas pro nível do módulo (refactor
> aditivo, comportamento idêntico — `_status`/`_dias_para_vencer` recebem
> `hoje_date` por parâmetro) justamente pra serem testáveis isoladamente.
