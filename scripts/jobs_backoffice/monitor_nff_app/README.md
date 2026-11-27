# Monitor NFF

App desktop que responde, para cada usina GD e cada mês: **a fatura CUSD da distribuidora chegou?
chegou no prazo? já foi paga? e o prazo de pagar, está em dia ou venceu?** Uma linha por
projeto/mês, com NFF, UC, status, pagamento e vencimento.

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
quick_invoices.py → tela "QuickInvoices Usinas": busca, classifica e envia à planilha ADFDI
              (reaproveita scripts/app/create_quick_invoices.py — ver a seção própria abaixo)
ui/         → HTML/CSS/JS servidos localmente (sem framework, sem build, sem CDN)
```

Não há servidor nem porta: o `pywebview` embute o WebView do sistema e o JS chama Python direto via
`window.pywebview.api.<método>`. Por isso **não existe passo de build para a UI** — editar
`ui/app.js` e reabrir o app já reflete.

### Fontes de dados

Quatro queries, todas resolvidas pelo `conf_cusd_invoices.yml` (nome lógico → arquivo em `sql/`):

| Nome lógico | Fonte | Papel |
|---|---|---|
| `job_monitoramento` | `USINAS_GERACAO` (dbt, `RETAIL_PROD`) | **âncora**: é a única fonte que amarra nota → acrônimo da usina. Desde 15/10/2026 (PROD em 28/10); antes era a `MONITORAMENTO_CUSD_AWS` (lambda) |
| `pagamentos_usinas` | `ap_oracle_view` (`AP_PAYMENTS` + `AP_INSTALLMENTS`) | as **duas** portas de pagamento do Oracle, numa leitura só |
| `fattureweb_usinas` | `FATTUREWEB_USINAS` | apresentação, competência, emissão, UC, **endereço** |
| `hist_usina_livia` | `V_MONITORAMENTO_HIST_USINA` | cadastro de usinas — de/para UC → acrônimo |

Nenhuma filtra data no servidor: a base vem inteira e o recorte de mês é feito em memória (ver
cache, abaixo).

> O **Quick Invoices** (`app/create_quick_invoices.py`) **não** usa a âncora acima: ele lê a
> `MONITORAMENTO_CUSD_AWS` (`stg_cusd_monitoring.sql`) mais o suplemento do FattureWeb. São duas
> fontes de nota diferentes para dois consumidores diferentes — mexeu numa, confira a outra.

O que a `pagamentos_usinas` filtra é **escopo**, não período. Ela existe porque a `AP_ORACLE_VIEW`
era lida duas vezes e inteira — 1.004.303 + 975.691 linhas para usar 1.113 (medido em 05/08/2026) —
e a view é `materialized='view'` sobre três `QUALIFY ROW_NUMBER()`, logo era recalculada duas vezes
por abertura. Era esse o gargalo do startup. O recorte é pelas notas que o monitor consegue casar
(`USINAS_GERACAO` ∪ `FATTUREWEB_USINAS` dos consórcios GD), pela chave normalizada do
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

### O export é o retrato da tela, e a aba `Info` diz de qual

Os botões de exportar gravam um `.xlsx` com o que a UI está mostrando: **base cacheada + filtros
ativos**. Quem recebe o arquivo não vê nada disso, então a pergunta "por que a NFF X não aparece no
relatório?" ficava sem resposta — base carregada horas antes? chip ou filtro escondendo a linha?

Por isso o export de **Faturas** (`exportar_excel(linhas, nome, info)`) ganha uma 2ª aba, `Info`, com
pares campo/valor: quando foi exportado, **quando a base foi consultada no Snowflake**, o mês do
painel, linhas exportadas × linhas do mês sem filtro, e o chip, a busca e os filtros de Status, Pago
e Prazo. A aba `Dados` continua igual (mesma ordem de colunas). Os exports de Parceiros, Histórico e
NFFs passam sem `info` e saem só com `Dados`; `info` é opcional na `Api`.

Se você criar um filtro novo na aba Faturas, acrescente-o em `infoExportFaturas()` ([`ui/app.js`](ui/app.js)) —
filtro que não está na `Info` volta a ser filtro invisível.

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
  `NaN` no JS. No `monitor.py` a armadilha é a mesma: `pd.to_numeric('32810,15')` também é `NaN`, e
  por isso a `Divergência Valor` nunca era calculada fora dos testes (que montam o total como float).
  Lá a conversão é `monitor._dinheiro`, mesma regra do `db._num`. É a mesma família de armadilha que
  as datas (ver *Datas: nenhuma fonte concorda com a outra*): **nada aqui garante que uma coluna
  tenha o tipo que o nome sugere.**
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
Pagamento`, `Competência`, `Faturas no Mês`, `NFF Adicionais`, `Valor Oracle`, `Divergência Valor`,
`Fatura Zerada`, `NFF Cancelada` e as de vencimento entraram assim). Quem consome lê por nome, mas quem exporta para Excel lê por posição.

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

### Fatura zerada: chegou, mas não há o que pagar

Fatura com `Total Fatura` = 0 no FattureWeb não tem pagamento — e aparecia como "A pagar" para
sempre. Caso real em out/2026 (GO-MNU-01 e GO-RIQ-04), confirmado pelo Backoffice: são faturas
zeradas que não precisam ser pagas.

A marca é a coluna `Fatura Zerada`, e **não** um valor novo em `Status` nem em `Pago`:

- `Status` responde só "chegou no prazo?" — e a fatura zerada chegou (às vezes atrasada, o que
  continua valendo informar). Um status novo também ficaria fora de toda regra que testa
  `Chegou`/`Chegou atrasada` (cards, chips, filtros).
- `Pago` continua booleano porque é campo vigiado do histórico e lido pela exportação; virar um
  terceiro estado mudaria valor de coluna existente.

Quem traduz é a UI: com `Pago` falso e `Fatura Zerada` verdadeiro, a célula mostra **Zerada** (cinza),
a fatura sai do card/chip "A pagar" e entra em "Zeradas", e a exportação escreve `Zerada` na coluna
Pago. Total **ausente** não é zero: sem `Total Fatura`, a fatura segue "A pagar".

### Vencimento: o prazo de pagar é outra pergunta que o `Status`

`Status` responde "a fatura **chegou** no prazo?" (contra a `Data Esperada`, o `Dia` de `PROJETOS`).
Não diz se ela já passou do **prazo de pagar**, e uma fatura chegada e não paga não mostrava isso.
Desde 13/11/2026 o painel cruza o **vencimento impresso na fatura** (`VENCIMENTO_FW`, FattureWeb)
com o pagamento — as colunas `Vencimento`, `Prazo Pagamento`, `Situação Prazo`, `Dias Prazo`,
`Vence Logo` e `Valor Fatura`, todas no fim da lista de saída. `Status` e `Pago` não mudaram.

- **Prazo = vencimento; sábado/domingo vale até a segunda** (`_prazo_util`). Feriado não é tratado.
  A mesma regra está em `observability/.../kpis.py` (`prazo_util`), porque o KPI 2 e este painel
  precisam julgar "vencida" igual. **Mudou aqui? Mude lá.** São duas cópias de 3 linhas, de propósito:
  o `kpis.py` é puro e testável sem importar o `monitor.py` (que puxa Snowflake).
- **`Situação Prazo`** (`_situacao_prazo`): `Vencida` (não paga e o prazo passou), `Em dia` (não paga e
  o prazo ainda vale — vencer **hoje** ainda é em dia), `Paga no prazo`, `Paga com atraso`, `Paga`
  (paga pela parcela do Oracle sem data nenhuma: não dá para julgar) ou vazio (sem vencimento no
  FattureWeb, fatura zerada ou NFF cancelada: não há prazo a cobrar). `Dias Prazo` é a folga entre o
  prazo e o pagamento (ou hoje, se não paga): positivo sobrou prazo, negativo é atraso.
- **`Vence Logo`** = `Em dia` com folga ≤ `DIAS_ALERTA_PRAZO` (2). Alimenta o selo âmbar, o chip e o
  card "Vence ≤2d". O número também está escrito nos rótulos da UI (`app.js`) — mexeu na constante,
  ajuste os textos.
- **`Valor Fatura`** = `Total Fatura` do FW e, sem ele, `Valor Oracle`. Existe para o card somar as
  vencidas em R$. Não é o valor pago (ver *Limitações*).
- **A UI**: `Vencimento` em vermelho só quando `Vencida`; coluna `Prazo` com o selo; chips/cards
  `Vencidas` e `Vence ≤2d` (com R$); filtro `Prazo`; linha vencida ganha o fundo de `row-danger`.
  O chip antigo "Vence ≤3d" virou **"Chega ≤3d"**: ele sempre mediu a **chegada** da fatura
  pendente (`Dias Restantes`), e o nome colidia com o vencimento de verdade.
- **Só vale para o mês de chegada** que a aba está mostrando: uma fatura de outubro vencida e sem
  pagamento não aparece em novembro. A visão por mês do vencimento é a da aba KPIs do observability.
- Data de pagamento do degrau 3 (parcela) é aproximada, então `Paga no prazo`/`Paga com atraso`
  nessas faturas também é (a coluna `Fonte Pagamento` sinaliza).

### Refaturamento: a versão válida é a exibida

A distribuidora às vezes reemite a fatura do mês (mesma competência, outra NFF), e só a última
versão vira NFF ativa e é paga. Caso real, Equatorial GO, competência 09/2026: emissões de 07/09
reemitidas em 09/09. O painel escolhia a linha exibida só por fonte e data — preferindo a linha do
monitoramento — e exibia a versão morta como "a pagar", com a paga escondida em `NFF Adicionais`
(GO-NVP-01 mostrava a NFF **cancelada** no Oracle; GO-RIQ-02, uma versão que nunca foi lançada).

- `fatura_valida()`: tem NFF ativa no Oracle (lançada e não Cancelada) ou já foi paga.
- `marcar_substituidas()`: fatura não válida cuja usina tem outra **válida da mesma competência**
  (`MES_REF_FW`). Só mesma competência: faturas de competências diferentes no mesmo mês
  (BA-BAR-01, mai/2026) não são substituição. Sem competência, nada é marcado.
- `montar_mes` troca a linha escolhida pela versão válida **só** quando a escolhida é substituída;
  qualquer outra escolha sai idêntica. A substituída segue contada em `Faturas no Mês` e listada em
  `NFF Adicionais`.
- `STATUS_NFF` (vem da `stg_pagamentos_usinas.sql`) alimenta a coluna nova `NFF Cancelada`: NFF
  cancelada sem versão válida aparece como **Cancelada** (mesmo tratamento da Zerada) e sai do
  "A pagar".

No mesmo dia: a `stg_pagamentos_usinas.sql` ganhou a perna `MAPA_USINAS` que a
`stg_fattureweb_usinas.sql` já tinha. Sem ela, usina com apelido nulo no FattureWeb (Rio Quente)
entrava no painel mas nunca tinha o pagamento buscado — a regra "mude aqui também" do header não
tinha sido seguida em 15/10/2026.

### A aba KPIs do monitor de observability lê esta base

`observability/monitor_observability_app` (aba KPIs) não tem query própria: chama
`carregar_base()` e aplica `pagamento_efetivo()` em todas as linhas, para que NFF, "Pago", data
de pagamento e valores batam com este painel por construção. Consequências para quem mexe aqui:

- **`pagamento_efetivo()` é a regra única de "Pago".** Era inline no `montar_mes`; saiu para uma
  função para os dois consumidores usarem a mesma. Mudou a cascata? Muda ali.
- **`VENCIMENTO_FW`** (vencimento impresso na fatura, do FattureWeb) nasceu para o KPI 2 e hoje é
  dividido: o painel também o exibe (ver *Vencimento*, acima).
- **`DATA_NFF`** (INVOICEDATE do Oracle, completada pela chave normalizada em chamada própria) existe
  só para os KPIs; o painel não a exibe. É coluna nova e não reaproveita `DATA_INVOICE` de propósito:
  completar `DATA_INVOICE` moveria faturas de mês na cascata.
- Renomear ou remover colunas do `df_merged` quebra a aba KPIs — os testes dela
  (`jobs_backoffice/tests/test_kpis_cusd.py`) carregam este `monitor.py` e pegam isso.

### QuickInvoices Usinas: o notebook dentro do monitor, em dois passos

A tela faz o que `notebooks/nb_quick_invoices.ipynb` faz (`CreateQuickInvoices.run`), reaproveitando
a **mesma classe** — query, bloqueio de usinas, `rename_maps`, escrita e log do KPI. O notebook
continua existindo e funcionando igual; a diferença é que aqui o `run()` vira dois passos:

1. **Buscar** (`Api.qi_buscar`) — só consulta. Dias de 1 a 365 (campo livre + atalhos 7/15/30/60/90) e
   data final (padrão: hoje). Não abre o Excel nem grava nada.
2. **Enviar** (`Api.qi_enviar`) — escreve **as linhas marcadas** na planilha, depois de um modal de
   confirmação. O envio usa os `_id` da última busca guardada em memória: o que a pessoa viu e marcou
   é exatamente o que vai, sem reconsultar.

O que a busca acrescenta sobre o notebook:

- **Cada NFF tem um de três status**: `Nova` / `Já no Oracle` / `Processada`. O Oracle é consultado por
  `sql/stg_quick_invoices_oracle.sql` (só as NFFs da busca, chave normalizada como no `_nf_key`);
  `Processada` vem dos logs do KPI — os do disco **e** os do SharePoint, ou seja, de qualquer usuário —
  e mostra a **data e hora do envio** na própria linha. A seleção padrão é só `Nova` sem alerta, então
  duas buscas sobrepostas não duplicam nota. Oracle manda sobre o log. Sem Oracle (falha), a tela avisa
  e classifica só pelos logs. NFF que no Oracle só tem versão **cancelada** continua `Nova`, mas não vem
  marcada e o detalhe avisa (relançar é decisão de quem conferiu).
- **`Processada` quer dizer "passou pela automação", não "está no Oracle".** O log prova que a NFF foi
  escrita na planilha; nada prova que o Upload foi feito. Quem sai do Excel sem salvar deixa a NFF
  `Processada` sem ela ter ido ao Oracle — ela continua selecionável (o envio substitui a planilha, então
  reenviar não duplica nada lá), mas não vem marcada. Para devolvê-la à fila como `Nova`, apague o log
  daquele envio (disco e SharePoint, `log_quickinvoices/`); o monitor só considera os logs que ainda
  estão listados no SharePoint, então não precisa reiniciar.
- **O que ficou de fora aparece**: usinas barradas por `nff_bloqueados` e linhas descartadas por dado
  incompleto (com o campo que falta). No notebook isso só saía no `print` do terminal. As duas listas
  usam a mesma janela de datas da busca — o bloqueio roda antes do filtro de data, então sem recortar
  contaria o histórico inteiro da fonte.
- **Alertas por linha**: campo obrigatório vazio (unidade de negócio, fornecedor, nº do fornecedor,
  CNPJ) ou valor zerado. Os `rename_maps` devolvem `None` para valor desconhecido (distribuidora nova),
  e a NFF iria com a célula vazia. Linha com alerta não vem marcada; o modal avisa se for enviada.
- **Falha de leitura não é silenciosa**: o suplemento (COELBA/CELPE/CEMIG) indisponível agora vira
  aviso na tela — no notebook a falha era engolida e a lista saía sem essas notas.

Decisões que não são óbvias:

- **Limite de 100 NFFs por envio.** A aba `NFFs` do template só desbloqueia as linhas 9–108; escrever
  além dá `com_error 0x800A03EC` no meio da gravação — e o fluxo **limpa as colunas antes de escrever**,
  então a planilha ficaria pela metade. A tela barra acima de 100 (o backend também) e orienta o lote:
  enviar, fazer o Upload no Oracle e buscar de novo (o que foi enviado sai da seleção).
- **O envio substitui o conteúdo da planilha**, como o `run()` sempre fez. O modal diz isso.
- **`xlwings` precisa de `CoInitialize` por thread.** Os métodos do pywebview rodam em threads do pool,
  não na principal; sem isso a gravação falha com "CoInitialize não foi chamado". Por isso o envio abre
  a planilha dentro de `_com()` e não guarda objetos COM entre chamadas.
- **A janela de dias é por data de emissão e inclusiva** (`até − dias` a `até`, ambos os dias). O
  notebook passa `datetime.now()`, que tem hora, e por isso perdia o primeiro dia da janela; aqui
  passa-se a data.
- **Auto-atualizar (15 min) não refaz a busca** desta tela: apagaria a seleção sem aviso.
- **`xlwings` só é exigido para enviar**; buscar funciona sem o Excel. `api.py` importa o serviço sob
  demanda, então dependência faltando aqui não impede o monitor de abrir.
- O envio grava o log do KPI (`registrar_run`) com `origem: monitor_nff` nos parâmetros, e a tela
  mostra se o log ficou `ok`, `pendente` (sobe no próximo envio) ou `falhou` (a NFF contaria como manual).

Teste manual (o que a suíte não cobre — Snowflake, SharePoint e Excel): buscar 30 dias e conferir
que as contagens fecham com o Oracle; enviar **3 linhas para uma cópia** da planilha (apontar
`MONITOR_NFF_ARQUIVO_EXCEL`) e checar a aba `NFFs`. Não teste o envio na planilha em uso: ele grava
log de verdade e suja o KPI 1.

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

- **CELPE, COELBA e CEMIG não sobem para o `MONITORAMENTO_CUSD_AWS`** (a fonte do Quick Invoices; a
  âncora do monitor hoje é a `USINAS_GERACAO`). As faturas delas entram pelo
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
