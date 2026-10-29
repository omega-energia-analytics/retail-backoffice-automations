# Monitor NFF

App desktop que responde, para cada usina GD e cada mês: **a fatura CUSD da distribuidora chegou?
chegou no prazo? já foi paga?** Uma linha por projeto/mês, com NFF, UC, status e pagamento.

## Por que existe

O acompanhamento era manual: abrir o FattureWeb, abrir o Oracle, conferir na planilha de controle,
repetir para ~80 usinas. O primeiro passo de automação foi o
[`jobs_adhoc/0_monitoramento_total_nff.py`](../jobs_adhoc/0_monitoramento_total_nff.py) — menu no
terminal, que já cruzava monitoramento × projetos. Ele mostrou o valor e os limites: terminal não
serve para quem só quer *olhar*, não dá para filtrar, e não tem como exportar para levar à reunião.

Daí este app. E a diferença real não é a interface: é que **uma fatura "não chegou" quase nunca
significa que ela não chegou**. Significa que ela chegou por um caminho que a fonte principal não
enxerga, ou que o número da nota está escrito diferente nas duas pontas, ou que o pagamento entrou
por outra porta do Oracle. Quase todo o código de [`monitor.py`](monitor.py) é sobre isso — e é o
que está documentado, com números de casos reais, em
[`tests/README.md`](tests/README.md). **Leia esse arquivo antes de mexer na lógica**; aqui está a
arquitetura, a operação e as decisões de projeto.

## Arquitetura

```
main.py     → sobe a janela pywebview, aponta pra ui/index.html, injeta a Api como js_api
api.py      → classe Api: cada método é chamado do JS e devolve {"ok": bool, "data"|"error"}
              guarda o CACHE da base (o pedaço caro)
monitor.py  → o pipeline de dados (pandas puro + as queries). É onde vive a regra de negócio.
db.py       → SQLite local: controle_nff (NFFs enviadas pro Oracle) + historico_fatura
              (o que mudou no painel ao longo do tempo)
config.py   → caminhos portáveis: env var > settings.json > default (~/Faturas Oracle/)
ui/         → HTML/CSS/JS servidos localmente (sem framework, sem build, sem CDN)
```

Não há servidor nem porta: o `pywebview` embute o WebView do sistema e o JS chama Python direto via
`window.pywebview.api.<método>`. Por isso **não existe passo de build para a UI** — editar
`ui/app.js` e reabrir o app já reflete.

### Fontes de dados

Quatro queries, todas resolvidas pelo `conf_cusd_invoices.yml` (nome lógico → arquivo em `sql/`):

| Nome lógico | Fonte | Papel |
|---|---|---|
| `job_monitoramento` | `MONITORAMENTO_CUSD_AWS` | **âncora**: é a única fonte que amarra nota → acrônimo da usina |
| `pagamentos_usinas` | `ap_oracle_view` (`AP_PAYMENTS` + `AP_INSTALLMENTS`) | as **duas** portas de pagamento do Oracle, numa leitura só |
| `fattureweb_usinas` | `FATTUREWEB_USINAS` | apresentação, competência, emissão, UC, **endereço** |
| `hist_usina_livia` | `MONITORAMENTO_HIST_USINA` | cadastro de usinas — de/para UC → acrônimo |

Nenhuma filtra data no servidor: a base vem inteira e o recorte de mês é feito em memória (ver
cache, abaixo).

O que a `pagamentos_usinas` filtra é **escopo**, não período. Ela existe porque a `AP_ORACLE_VIEW`
era lida duas vezes e inteira — 1.004.303 + 975.691 linhas para usar 1.113 (medido em 05/08/2026) —
e a view é `materialized='view'` sobre três `QUALIFY ROW_NUMBER()`, logo era recalculada duas vezes
por abertura. Era esse o gargalo do startup. O recorte é pelas notas que o monitor consegue casar
(`MONITORAMENTO_CUSD_AWS` ∪ `FATTUREWEB_USINAS` dos consórcios GD), pela chave normalizada do
`_nf_key`. Detalhe e números no header do [`stg_pagamentos_usinas.sql`](../../sql/stg_pagamentos_usinas.sql)
e em [`tests/README.md`](tests/README.md).

> As chaves antigas `pagamentos` / `pagamentos_installment` continuam no conf como **fallback** — se
> a recortada falhar, `_carregar_pagamentos` volta ao caminho de duas queries em vez de deixar o
> monitor sem pagamento. E o `stg_pagamentos.sql` **não pode ganhar o recorte**: ele é compartilhado
> com a lambda `monitoramento_cusd` (PROD) e com o `main_pagamento_usinas.py`, que precisam da AP
> inteira.

## Decisões de projeto (e por quê)

### A lista `PROJETOS` é hardcoded no código

As ~83 usinas, com `Dia` (prazo esperado de chegada) e `Forma Recebimento`, estão numa lista
literal no topo do [`monitor.py`](monitor.py). Não é elegante, e é proposital: o `Dia` é **acordo
comercial por usina**, não existe em nenhuma tabela, e mantê-lo em planilha significaria mais um
arquivo não versionado no caminho crítico. Aqui ele fica em `git log`.

Consequências que você precisa saber:

- **Usina nova / prazo mudou / distribuidora trocou → edite `PROJETOS`.** Não há outro lugar.
- **A mesma lista está duplicada** no `jobs_adhoc/0_monitoramento_total_nff.py`. Elas **já
  divergiram** no passado. O `0_` é o predecessor e está congelado; se você mexer nele, saiba que a
  fonte de verdade é o `monitor.py`.
- `Forma Recebimento = 'N/A'` (PI-JCO-01, PI-SRN-01, PI-SRN-04) **fica fora do painel**: fluxo
  manual, sem NFF rastreável. São as mesmas usinas da lista `nff_bloqueados` do
  `conf_cusd_invoices.yml` — nunca geram nota, então também não faz sentido cobrar fatura delas.
- `PROJETOS` **não tem data de entrada em operação**. Por isso mês anterior à primeira fatura da
  usina aparece como "Atrasada" — limitação conhecida, concentrada em 2025, some a partir de
  12/2025.

### O cache: base cara, recorte barato

`carregar_base()` conecta, roda as 4 queries e devolve a base inteira. `montar_mes()` fatia um mês
dessa base, em pandas puro, sem rede. A `Api` guarda o resultado de `carregar_base()` em memória.

Isso não é micro-otimização: **conectar reautentica no navegador**. Sem o cache, trocar o mês no
seletor abriria uma aba de login e re-rodaria as 4 queries para olhar *os mesmos dados* em outro mês. O
botão de recarregar (`force_refresh=True`) é o único caminho para bater no Snowflake de novo.

Se você adicionar algo ao pipeline, respeite a divisão: **rede em `carregar_base()`, regra de mês em
`montar_mes()`**. Foi o que permitiu testar a regra de negócio inteira sem mock de Snowflake.

### O histórico grava mudança, não snapshot

A aba **Histórico** responde "o que mudou nesta usina ao longo do tempo?" — a pergunta que o painel,
que só mostra o agora, não respondia. Grava em `historico_fatura` (mesmo SQLite do `controle_nff`,
então sobrevive a fechar o app).

A regra é **só mudança entra**. `registrar_snapshot` compara cada fatura com o último valor gravado
dela e insere uma linha por campo que mudou; abrir o app cinco vezes no mesmo dia sem nada mudar não
grava nada. Snapshot completo por carga seria ~83 projetos × meses × aberturas de fotos idênticas —
e a busca devolveria repetição em vez de história.

Decisões que não são óbvias:

- **A chave é (projeto, mês do painel, competência, NFF).** As quatro partes são necessárias, e
  cada uma pagou o preço de faltar:
  - sem `NFF`, a 2ª nota do mês (que o painel joga em `NFF Adicionais`) entraria no log como se a
    primeira tivesse mudado de número;
  - sem `mês do painel`, fatura que ainda **não chegou** — que não tem competência nem nota — teria
    a chave `(projeto, '', '')` e **todos os meses dela colapsariam numa só**. Como o mesmo projeto
    aparece `Pendente` no mês corrente e `Atrasada` num mês vencido, cada mês sobrescrevia o outro e
    o log registrava um vai-e-volta infinito, a cada carga (observado em produção: `PE-BMD-01` indo
    `Pendente → Atrasada` e `Atrasada → Pendente` no mesmo segundo, 170 linhas assim);
  - `competência` separa faturas de competências diferentes que caem no mesmo mês do painel, já que
    o recorte da aba Faturas é por data de **chegada**.

  Por isso a tabela mostra **Mês** e **Compet.** como colunas distintas: a fatura que ainda não
  chegou tem mês e não tem competência.
- **Fatura que ganha nota é adotada, não renasce** (`_adotar_sem_nff`). A NFF na chave cria um caso
  a resolver: a fatura aparece no painel *antes* de ter nota (como `Atrasada`/`Pendente`) e ganha a
  nota quando chega. Sem adoção isso a partiria em duas — a sem-nota congelando no último status e
  a com-nota nascendo do zero —, e `Atrasada → Chegou`, a transição que motivou a aba, nunca
  apareceria. A adoção transfere o histórico e registra a chegada da nota como um evento `NFF`. Só
  adota se a nota ainda não tem história própria: se já tem, a sem-nota é outra fatura.
- **NFF ausente vira `''`, não `NULL`.** `NULL` não casa com `=` em SQL, então a linha nunca
  reencontraria o próprio estado anterior e "apareceu" se repetiria a cada carga.
- **A comparação é textual e a representação precisa ser estável** (`db._txt`): bool vira
  `sim`/`nao` e dinheiro vira sempre `1234.56`. Sem isso, ruído de ponto flutuante
  (`19142.039999999997`) viraria mudança a cada carga. Um centavo de diferença continua sendo
  mudança — a divergência FW × Oracle é real e é justamente o que se quer ver.
- **`Total Fatura` chega do FattureWeb como TEXTO em formato brasileiro** (`'32810,15'`), enquanto
  `Valor Oracle` chega como float. São a mesma grandeza e precisam virar a mesma coisa antes de
  comparar (`db._num`, que também trata o separador de milhar `'1.234,56'`). Sem isso `'7575,1'` e
  `'7575,10'` contariam como mudança, e a tela mostrava o texto cru porque `Number('32810,15')` é
  `NaN` no JS. É a mesma família de armadilha que as datas (ver *Datas: nenhuma fonte concorda com a
  outra*): **nada aqui garante que uma coluna tenha o tipo que o nome sugere.**
- **`Divergência Valor` fica fora dos campos vigiados**: é derivado de `Total Fatura` e
  `Valor Oracle`, então registrá-lo duplicaria toda mudança de valor.
- **A gravação roda no `_base()`, não no `carregar_faturas()`.** Precisa cobrir todos os meses da
  base, não só o que o usuário abriu — senão mês que ninguém olhou nunca entraria no log. E falha
  ali não derruba a carga: ficar sem app por causa do log seria pior que ficar sem uma linha dele.

A busca (por acrônimo, projeto ou NFF) é uma só e acontece no SQL, indexada. É o que permite seguir
a mesma usina — ou a mesma nota — ao longo de vários meses.

**A carga inicial fica escondida por padrão.** A primeira gravação de um banco registra todo o
acervo que já estava no painel (~2.000 faturas, milhares de linhas, todas com `De` vazio e o mesmo
timestamp). Isso não é mudança, é o retrato de quando o log passou a existir — e mostrá-lo afoga a
mudança de verdade. `db.carga_inicial_em()` marca esse instante e `buscar_historico` corta a partir
dele; o check *incluir carga inicial* na UI traz de volta. O corte é a **primeira** gravação e não
desliza: se deslizasse, a cada carga a anterior viraria "inicial" e sumiria da tela.

O rodapé da aba mostra onde o arquivo mora (`~/Faturas Oracle/controle_nff.db`) e desde quando grava
— "onde isso fica salvo?" é a primeira pergunta de quem abre.

### Toda fonte nova entra como degrau, nunca como substituição

O padrão de todo o `monitor.py`: a fonte que já existia continua mandando, e a nova só preenche o
que ficou vazio (`fillna`, ou escrita condicionada a `isna()`). Vale para pagamento (3 degraus),
data (2 cascatas), de/para de UC (3 fontes), chave de nota (2 passes).

Por que: as saídas deste app vão para reunião e para planilha de acompanhamento. Uma mudança que
altera linha que já estava certa é ruído que ninguém consegue auditar. Assim, o pior caso de um
degrau novo é *não melhorar* uma linha — nunca piorar.

Corolário nas colunas de saída: **coluna nova entra no fim da lista**, nunca no meio (`Fonte
Pagamento`, `Competência`, `Faturas no Mês`, `NFF Adicionais`, `Valor Oracle`, `Divergência Valor`
entraram assim). Quem consome lê por nome, mas quem exporta para Excel lê por posição.

### Valor da fatura: o painel mostra as DUAS pontas, não escolhe

`Total Fatura` vem do FattureWeb e `Valor Oracle` (`AP_ORACLE_VIEW.INVOICEAMOUNT`) vem da mesma
fonte que responde o `Pago`. Elas **deveriam** bater e não batem: a NFF `047744547` vale
`19.142,04` no FattureWeb e `7.525,59` no Oracle. Como o ✓ de pagamento é do Oracle e o valor
exibido era só o do FattureWeb, a leitura natural do painel era "os 19.142,04 foram quitados" —
quando o que entrou na AP foi 7.525,59.

O painel não tenta decidir qual está certo (fatura lançada parcialmente, valor digitado errado e
NFF reutilizada produzem o mesmo sintoma e a resposta é caso a caso). Ele mostra os dois números e
`Divergência Valor` = `Total Fatura − Valor Oracle`; a UI marca em vermelho com ⚠ quando a
diferença passa de 1 centavo (abaixo disso é arredondamento das duas pontas). Fatura ainda não
lançada no Oracle sai com as duas colunas vazias, não como divergência do total inteiro.

O `Valor Oracle` depende do **2º passe de chave**, não só do merge exato: NFF com zero à esquerda
(`047744547` no monitoramento, `47744547` no Oracle) não casa no merge, e sem completar o valor
nesse passe ela aparecia paga com o valor em branco. O passe do valor é uma chamada **separada** da
do pagamento — ver a seção correspondente do [`tests/README.md`](tests/README.md), que explica por
que juntá-los quebraria o resgate de pagamento do GO-MNU-01.

### Quando a fonte nova não existe, o degrau se desliga

A leitura de `pagamentos_installment` está dentro de um `try/except` largo. Se a `ap_oracle_view`
ainda não expõe as colunas de parcela (build da view não rodou), a query falha com "invalid
identifier", o app **avisa e segue** com o comportamento anterior — em vez de morrer inteiro.

Mesma ideia em `montar_mes()`: colunas que podem faltar são criadas vazias antes do uso. Isso
também é o que permite alimentar o `montar_mes()` com fixture de teste mínima.

### Na dúvida, a usina fica sem fatura

Todo cruzamento heurístico aqui (de/para por endereço, 2º passe de chave por nota normalizada)
descarta chave ambígua em vez de escolher uma. **Exibir o pagamento de outra fatura é muito pior
que exibir "sem pagamento"** — o segundo caso alguém investiga, o primeiro passa como verdade. Duas
usinas em Morro Agudo (SP-ATN-01 e SP-ATN-02) dividem literalmente o mesmo endereço e por isso
seguem fora do resgate por endereço; está correto que sigam.

### Datas: nenhuma fonte concorda com a outra

Três armadilhas que já custaram meses de número errado, todas resolvidas em `monitor.py` e todas
com chance de voltar:

1. **`AP_ORACLE_VIEW` mistura dois formatos** na mesma coluna (`2026-05-04 11:31:08` e
   `2026-07-21T00:00:00Z`). `pd.to_datetime` sem `format` infere pela primeira linha não-nula e
   silenciosamente vira `NaT` no resto — todo pagamento recente aparecia como não pago. É o que
   `_to_naive()` resolve, com duas passadas.
2. **Competência ≠ emissão ≠ lançamento contábil ≠ chegada.** São quatro datas diferentes, e qual
   usar depende da pergunta. O painel recorta o mês pela **chegada**; ver `_cascata_datas` e a seção
   correspondente do [`tests/README.md`](tests/README.md).
3. **A NFF passa por float em algum ponto** do caminho, então a mesma nota aparece como
   `42937901`, `42937901.0` e `042937901`. Chave de merge normalizada (`_nf_key`) resolve; a NFF
   **exibida** continua a original.

## Como rodar

Pré-requisitos: Windows com VPN, `scripts/jobs_backoffice/.env` preenchido (Snowflake + Microsoft
Graph), Python 3.11+. Setup completo no [README raiz](../../../README.md#primeiro-setup).

A partir da raiz do repo:

```powershell
pip install -r requirements.txt      # deps do repo todo, inclui pywebview
python scripts\jobs_backoffice\monitor_nff_app\main.py
```

Na primeira carga o app **abre o navegador** para o SSO do Snowflake — é esperado. O terminal
imprime o diagnóstico de cada etapa (`[monitor] …`): quantas linhas por fonte, cobertura de cada
degrau de data, quantas UCs o de/para cobriu, quantos projetos ficaram sem fatura no mês. **Quando
uma usina aparecer errada no painel, é essa saída que diz em qual degrau ela se perdeu.**

### Configuração de caminhos

`config.py` resolve cada valor por **env var > `settings.json` > default**:

| Chave | Env var | Default |
|---|---|---|
| `arquivo_excel` | `MONITOR_NFF_ARQUIVO_EXCEL` | `~/Faturas Oracle/CreateQuickInvoices.xlsm` |
| `db_path` | `MONITOR_NFF_DB_PATH` | `~/Faturas Oracle/controle_nff.db` |
| `aba` | `MONITOR_NFF_ABA` | `NFFs` |
| `header_linha` | `MONITOR_NFF_HEADER_LINHA` | `7` |

O `settings.json` fica em `%APPDATA%\MonitorNFF\` — pasta gravável, para sobreviver ao
empacotamento como `.exe`. A UI tem seletor de arquivo que persiste a escolha ali. **Nada disso
precisa ser editado no código** para rodar em outra máquina.

O `controle_nff.db` (SQLite, tabela `controle_nff`) registra quais NFFs já foram enviadas ao
Oracle, a partir da planilha ADFDI — é a função "Processar Excel" da UI. `INSERT OR IGNORE`: nota
já registrada não muda de data.

### Empacotar como .exe

O `requirements.txt` **desta pasta** (só as deps do app, mais enxuto que o da raiz) foi mantido
porque o build referencia ele: `pip install -r requirements.txt pyinstaller`, rodado de dentro de
`monitor_nff_app/`. **Não há `.spec` versionado no repo** — o
build era feito na mão. Se você precisar refazer, lembre que `ui/` precisa ir como dado
(`--add-data`) e que `config.py` já grava fora do bundle de propósito. Ao acertar o comando,
commite o `.spec`.

## Limitações conhecidas

- **CELPE, COELBA e CEMIG não sobem para o `MONITORAMENTO_CUSD_AWS`.** As faturas delas entram pelo
  suplemento FW+Oracle, que depende de haver de/para de UC. Sem de/para, a usina aparece sem
  fatura — não é bug do painel, é ausência de ingestão a montante.
- **O de/para por endereço cobre a virada de UC da CPFL** (padrão ANEEL, competência 06/2026)
  porque nenhuma tabela de de-para serve; todas foram verificadas e estão vazias (a tabela com o
  levantamento está no `tests/README.md`). Se a CPFL mudar o endereço cadastrado, esse resgate cai.
- **Pagamento do degrau 3 (parcela) tem data aproximada** (`UPDATED_AT` da parcela, não a data real
  do pagamento). A coluna `Fonte Pagamento` = `ORACLE_INSTALLMENT` é o que sinaliza isso — não trate
  essa data como data de caixa.
- **`Valor Oracle` é o valor da fatura no Oracle, não o valor pago.** É o `INVOICEAMOUNT` do
  lançamento, e o painel não tem o montante efetivamente liquidado. Uma divergência sinalizada
  merece investigação no Oracle — ela diz que as duas fontes discordam, não qual delas está certa.
- **`api.py` e `main.py` não têm teste** (camada pywebview/bootstrap). `carregar_base()` também
  não — precisa de rede. A regra de negócio testável foi extraída para funções puras justamente
  por isso.
