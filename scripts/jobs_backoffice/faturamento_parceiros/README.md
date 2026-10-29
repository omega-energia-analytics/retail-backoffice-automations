# Faturamento de parceiros — geração de NFF

Preenche a aba `NFFs` da planilha **ADFDI do Oracle** (`CreateQuickInvoices.xlsm`) com as NFFs de
parceiros, lendo os lançamentos de **Débito** da planilha de controle de contratos. Depois é a
pessoa que revisa e faz o *Upload* no Oracle.

## Por que existe

NFF de parceiro não entra no Oracle por API. Entra por **ADFDI** (Application Desktop Integration):
um add-in de Excel que transforma a planilha em formulário do ERP — você digita nas linhas, ele
rastreia o que mudou e sobe. O preenchimento era manual, linha por linha, com de/para de unidade de
negócio e de fornecedor feitos de cabeça ou consultando outra aba.

São ~18 campos por NFF, dos quais 8 são constantes e 2 são de/para que o Oracle **recusa se vier
com o texto errado**. Errar um significa refazer o lote. Este job monta o bloco inteiro e deixa só a
revisão para a pessoa.

## O fluxo, de ponta a ponta

```
contratos completos.xlsx          CreateQuickInvoices*.xlsm            Oracle
  aba Controle_Emissão      →       aba NFFs (linhas 9+)         →     Upload
  (filtra Tipo de Nota =            escrito via xlwings, com            (manual, feito
   "Débito")                        o add-in ADFDI vivo                 por quem tem acesso)
```

1. `ler_debitos()` — abre a origem com openpyxl (read-only), acha as colunas **pelo texto do
   cabeçalho** e devolve só as linhas com `Tipo de Nota = "Débito"`.
2. `montar_registros()` — um dict por NFF, aplicando os de/para e as constantes.
3. `achar_destino()` — pega o `CreateQuickInvoices*.xlsm` **mais recente da própria pasta**.
4. `gravar()` — abre/anexa ao Excel interativo e escreve coluna por coluna. Salva, não fecha.
5. `relatorio()` — resumo colorido no terminal: quantas NFFs, o que revisar, o que ficou sem de/para.

## Premissas (o que precisa estar verdadeiro para funcionar)

- **Windows, com Excel instalado e o add-in ADFDI configurado e logado no Oracle.** Sem isso o job
  escreve na planilha mas as linhas não sobem — e o sintoma é silencioso.
- **As duas planilhas moram nesta pasta e não vão para o git** (têm dado de fornecedor e de
  faturamento). Clonar o repo não traz nenhuma das duas. `contratos completos.xlsx` é o controle do time;
  `CreateQuickInvoices*.xlsm` é o template ADFDI baixado do Oracle.
- **Layout da origem:** aba `Controle_Emissão`, cabeçalho na primeira linha, com as colunas
  `PAGADOR`, `Nº da Nota`, `Valor`, `FORNECEDOR`, `CNPJ`, `Descrição`, `Charge Account`,
  `Tipo de Nota`. Falta uma → o job para com o cabeçalho que leu, de propósito.
- **Layout do destino:** aba `NFFs`, cabeçalho na **linha 8**, dados a partir da **linha 9**.

## Decisões e por quê

### xlwings + Excel interativo, não openpyxl

O ADFDI é um add-in **VSTO**: ele só carrega numa sessão *interativa* do Excel e rastreia as
alterações via `Worksheet_Change`. Consequências, todas aprendidas na prática:

- **`os.startfile()` em vez de `xw.App()`.** Instância de automação do Excel não carrega o add-in.
  `os.startfile` é o equivalente a dar duplo-clique — sessão normal, add-in vivo. O job espera até
  90s o workbook aparecer, e se já estiver aberto, **anexa** à sessão existente.
- **`EnableEvents = True` durante a escrita.** É o que dispara o rastreio: cada coluna escrita gera
  a "Chave" da linha e marca "Alterado" (▲). Sem eventos, a planilha fica preenchida e nada sobe.
- **`desbloquear_motw()`** remove o *Mark-of-the-Web* (o stream NTFS `Zone.Identifier`) antes de
  abrir. Arquivo baixado da internet abre em modo protegido, e modo protegido bloqueia add-ins —
  esse era o motivo real de "o rastreio não engancha". A remoção é idempotente e preserva os outros
  ADS (tags de DLP, por exemplo).

### Não desprotegemos a aba — e nunca limpamos o bloco inteiro

Duas armadilhas que já quebraram o upload:

- **Desproteger a aba para limpar tudo apagava a coluna "Chave"** — o id que o ADFDI usa para
  rastrear cada linha. Sem Chave, o add-in perde a linha e ela não sobe. As colunas de *dados* são
  desbloqueadas pelo próprio template: dá para escrever nelas **com a aba protegida**. As colunas do
  add-in ("Alterado", "Status da Linha", "Chave") são bloqueadas — e devem continuar.
- **As células de dados só são desbloqueadas numa faixa finita de linhas.** Abaixo dela voltam a ser
  bloqueadas, e `used_range` estoura essa faixa: limpar até ele dá "planilha protegida". Por isso o
  job descobre quantas linhas antigas existem **pela coluna de id** (densa, e leitura é permitida
  mesmo em célula bloqueada) e limpa só até lá.

### Os dois de/para

| De | Para | Onde |
|---|---|---|
| `PAGADOR` | `*Unidade de Negócio` — valor **exato** da LOV do Oracle (`<código>-<nome>`) | `DE_PARA_UNIDADE` |
| `FORNECEDOR` | `**Número do Fornecedor` (ID Oracle, coluna M) | `DE_PARA_FORNECEDOR` |

- Os **códigos de unidade não são sequenciais** (GD 9 = 6101, GD 12 = 6091). Não deduza: eles vêm
  da aba `_ADFDI_LOV` do próprio `CreateQuickInvoices`, linha 2. Unidade nova no Oracle → copiar de
  lá.
- As chaves são normalizadas por `_norm_un()` (sem acento, maiúsculo, sem pontuação final), então
  `"CONSÓRCIO…"`, `"S.A"` e `"S.A."` caem na mesma chave. Você pode adicionar a entrada como ela
  aparece na planilha.
- **Sem de/para, os dois falham "para frente", não param o job:** a unidade mantém o nome limpo
  (comportamento antigo) e o número de fornecedor fica em branco (o Oracle casa pelo nome na coluna
  L). Em ambos os casos o nome entra no relatório final como pendência a revisar. Isso é
  deliberado: um fornecedor novo não deve travar o lote inteiro.

### Constantes e regras de preenchimento

- `Moeda = BRL`, `Tipo de NFF = Standard`, `Condições = Imediato`, `Grupo = Método Direto`,
  `Tipo de linha = Item` — fixos.
- `Data da NFF` = hoje. `Data das Condições` = **último dia do mês corrente** (`MonthEnd(0)`) —
  regra passada pelo time de contas a pagar, não é convenção técnica.
- `Local do Fornecedor` = só os dígitos do CNPJ.
- `Identificador do Cabeçalho` = 1, 2, 3… (uma NFF por linha da origem).
- Na resolução de cabeçalho, **a primeira ocorrência do texto vence**: existem duas colunas
  `Descrição` (cabeçalho e linha) e a que interessa é a primeira (coluna Q).
- Linha sem `Valor` **não é descartada** — é contada e reportada. O Oracle recusa, e é melhor a
  pessoa ver a linha faltando valor do que descobrir que ela desapareceu.

## Como rodar

```powershell
python scripts\jobs_backoffice\faturamento_parceiros\gera_nff_parceiros.py
```

Não precisa de VPN nem Snowflake — este job não consulta banco. Precisa de Excel e do ADFDI.

O que esperar: o Excel abre (ou é reaproveitado se já estiver aberto), as linhas aparecem marcadas
com ▲ na aba `NFFs`, o arquivo é salvo **sem fechar**, e o terminal imprime o resumo. Então:

1. **Revise a aba `NFFs`** — em especial as pendências que o relatório listou.
2. Faça o **Upload** pelo menu do ADFDI (quem tem acesso de upload no Oracle).

O job pode ser rodado de novo: ele limpa as linhas de dados anteriores antes de escrever.

## Pontos de atenção

- **Validação de ponta a ponta depende de máquina com ADFDI vivo e acesso ao Oracle.** Erros do tipo
  `ADFDI-00153` são do add-in/sessão, não do script — o Python já terminou nesse ponto. Se você não
  tem esse acesso, o máximo que consegue verificar é que a planilha ficou preenchida corretamente.
- **Este caminho não passa pela lista `nff_bloqueados`** do `conf_cusd_invoices.yml`. Aquele bloqueio
  (PI-JCO-01, PI-SRN-01, PI-SRN-04) protege o caminho CUSD (`app/create_quick_invoices.py`), não o
  de parceiros. Se algum dia uma usina bloqueada aparecer como Débito na origem, **ela vai gerar
  NFF** — não há trava aqui.
- **Warts conhecidos:** as linhas `from turtle import pd` no topo do arquivo são resquício de
  autocomplete. Não quebram (o `turtle` realmente tem uma função `pd`, e o pandas de verdade é
  importado dentro de `montar_registros`), mas carregam `tkinter` sem motivo e confundem quem lê.
  Podem sair.
- **Testes:** a lógica pura tem cobertura em
  [`tests/test_gera_nff_parceiros.py`](../tests/test_gera_nff_parceiros.py) (de/para, normalização,
  mapeamento de cabeçalho, montagem dos registros). O I/O de Excel não é testado — depende de
  sessão interativa.
