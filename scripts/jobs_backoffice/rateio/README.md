# rateio

Leitores de **rateio de energia** — a planilha/CSV em que cada distribuidora informa o percentual de
geração de uma UG (usina) alocado para cada UC (unidade consumidora). Um módulo por distribuidora,
todos devolvendo o **mesmo DataFrame canônico**.

Consumido por [`monit_hist_usina.py`](../monit_hist_usina.py), que é quem enriquece e consolida o
resultado no histórico. Ver [MONIT_HIST_USINA.md](../MONIT_HIST_USINA.md).

## Por que existe

Cada distribuidora inventa seu próprio formato: a CPFL manda um CSV por UG, a Equatorial GO manda
Excel com cabeçalho em linha variável e o percentual numa coluna chamada "% kWh" — e o nome da
coluna de UC nem é "UC" (é "Conta Contrato"). Tratar isso inline no pipeline significava um `if
distribuidora ==` crescendo para sempre, e cada bug de leitura reaparecendo na distribuidora
seguinte.

A separação é: **o módulo da distribuidora sabe ler o arquivo dela; o pipeline não sabe de
distribuidora nenhuma.**

## O contrato

Todo leitor expõe duas coisas:

```python
DISTRIBUIDORA = "CPFL PAULISTA"                              # string usada como chave no registry
def ler_todos_rateios(folder, data_hoje, mes_envio) -> DataFrame   # já canônico
```

E a saída tem **exatamente** estas colunas ([`base.py`](base.py)):

```python
COLUNAS_CANONICAS = ["Distribuidora", "UG", "UC", "%", "Data de Envio", "Mês de Envio"]
```

- `%` é **fração** (0.3124 = 31,24%), nunca percentual.
- `UG` e `UC` são **string** sem `.0` (vêm como float de planilha com frequência).
- As três últimas colunas são carimbadas por `finalizar_rateio()` — o leitor não precisa montá-las.

O [`__init__.py`](__init__.py) mantém o registry:

```python
LEITORES = {cpfl_paulista.DISTRIBUIDORA: cpfl_paulista.ler_todos_rateios, ...}
```

## Decisões e por quê

### O percentual é sempre dividido por 100 — sem heurística

A versão antiga fazia `if x > 1: x / 100`, tentando aceitar as duas escalas. **Isso estava errado e
o erro era silencioso:** UC com rateio abaixo de 1% (`0.94` = 0,94%) passava intacta e virava 94%,
estourando a soma da UG. A coluna vem sempre em escala percentual nas duas distribuidoras; a
conversão é incondicional.

Se algum dia aparecer uma distribuidora que manda fração de verdade, trate no **módulo dela** — não
volte a adivinhar pela magnitude do número.

### A soma tem que fechar ~100% por UG, e isso bloqueia

`validar_soma_rateio(df, tolerancia=0.01, bloquear=True)` levanta `ValueError` se alguma UG ficar
fora de `1.0 ± 0.01`, ou se houver `%` não numérico.

Por que bloqueia em vez de avisar: rateio que não fecha é o sintoma comum de **todos** os erros de
leitura — escala errada, linha de "TOTAL" capturada como se fosse UC, coluna trocada, arquivo do mês
errado. Nenhum deles quebra o script; todos geram número errado que segue para o histórico e para a
distribuidora. A trava é a única coisa que os pega antes.

A mensagem lista UG por UG com o desvio, para ser acionável direto.

### Arquivo do OneDrive: checar por leitura, não por atributo

`checar_arquivos_baixados()` tenta **abrir e ler 1 byte** de cada arquivo antes de processar. Arquivo
"online-only" com download travado falha com um `OSError [Errno 22]` críptico ("a operação na nuvem
não foi concluída") **no meio do processamento**, num arquivo só, depois de já ter lido os outros.

A checagem prévia dá uma mensagem única listando todos os problemáticos, com a instrução ("Sempre
manter neste dispositivo"). E é **por leitura real, de propósito**: o flag `RECALL_ON_DATA_ACCESS`
do OneDrive continua setado mesmo em arquivo já baixado e legível, então checar atributo dava
falso-positivo e bloqueava arquivo bom.

### `astype(str)` transforma célula vazia em `"nan"` — e `"nan"` escapa do `dropna`

Armadilha recorrente nos dois leitores. Sem reverter `"nan"`/`"None"`/`""` para `pd.NA` depois da
conversão, a linha **"TOTAL"** do rodapé da planilha entra no rateio como se fosse uma UC. Se você
escrever um leitor novo, copie esse trecho.

### Equatorial GO: o cabeçalho é procurado, não assumido

A linha do cabeçalho varia entre arquivos, então o leitor varre as linhas até achar uma que tenha
**"% KWH" e "CONTA CONTRATO"** juntas, e relê o arquivo com aquele `header`. A UG sai do **nome do
arquivo** por regex (`Rateio - Equatorial - <UG>.xlsx`), não do conteúdo — mesma coisa na CPFL
(`Template-InformarRateio<UG>.csv`). Nome de arquivo fora do padrão levanta erro com o nome no
texto.

### A UG é o número da instalação — e o acrônimo no nome do arquivo é ruído

Em 08/2026 a Equatorial passou a mandar `Rateio - Equatorial - GO-HLX-01.1 - <instalação> - <data> -
<timestamp>.xlsx`, com o **acrônimo** ocupando a posição onde antes vinha só a UG. A regex antiga
exigia dígito logo após "Equatorial -" e o job parava em `UG não encontrada`.

O acrônimo virou um grupo **opcional e não capturado** — a UG continua sendo o **número da
instalação**, porque é ele que casa com `NUMERO_DA_INSTALACAO` no merge do `monit_hist_usina.py`.
Trocar por acrônimo aqui não quebraria a leitura, mas deixaria todas as linhas sem `Usina`/`CC`
depois do merge. Se aparecer outro nome novo, estenda o grupo opcional — não solte o `(\d+)` para
casar em qualquer lugar do nome, que a data (`01-07-2026`) e o timestamp também são dígitos.

## Como adicionar uma distribuidora

1. Crie `<distribuidora>.py` nesta pasta, usando [`cpfl_paulista.py`](cpfl_paulista.py) (CSV,
   simples) ou [`equatorial_go.py`](equatorial_go.py) (Excel, cabeçalho variável) como template.
   Exponha `DISTRIBUIDORA` e `ler_todos_rateios(folder, data_hoje, mes_envio)`.
2. Dentro dele, implemente `listar_arquivos(folder)` e `ler_rateio(caminho, data_hoje, mes_envio)`,
   e delegue o loop para `agregar_rateios()` do `base.py` — ele já faz a checagem de OneDrive e a
   concatenação.
3. Termine com `finalizar_rateio(df, DISTRIBUIDORA, data_hoje, mes_envio)`.
4. Registre em `LEITORES`, no [`__init__.py`](__init__.py).
5. Se a pasta dentro de `7. Rateio` tiver nome diferente do valor de `DISTRIBUIDORA`, registre em
   `pastas_especiais` no [`monit_hist_usina.py`](../monit_hist_usina.py).
6. Acrescente o alias no `map_distribuidoras` do `monit_hist_usina.py` se o CRM/cadastro usar outra
   sigla (ex.: `CELGD` → `EQUATORIAL GO`).

**Nada mais no pipeline precisa mudar.** Teste o leitor novo criando a fixture de arquivo em
`tmp_path` (sem depender de OneDrive) — ver *Testes*, abaixo.

## Como rodar

Não é executável direto: é biblioteca. O caminho normal é pelo
[`monit_hist_usina.py`](../monit_hist_usina.py). Para testar um leitor isolado:

```python
from jobs_backoffice.rateio import LEITORES, validar_soma_rateio
import pandas as pd

df = LEITORES["EQUATORIAL GO"]("<pasta do mês>", pd.Timestamp.today(), pd.Timestamp("2026-04-01"))
validar_soma_rateio(df)
```

(com o `PYTHONPATH` apontando para `scripts/` — ver o [README raiz](../../../README.md#como-rodar)).

## Testes

O `test_rateio.py`, que cobria os leitores e o `validar_soma_rateio` com fixtures em `tmp_path`,
**não veio para este repo** — hoje esta pasta não tem teste aqui. Ao recriá-lo, coloque em
[`../tests/`](../tests/) (o `conftest.py` de lá já põe `scripts/` no `sys.path`, então
`from jobs_backoffice.rateio import ...` funciona) e rode:

```powershell
python -m pytest scripts\jobs_backoffice\tests -v
```
