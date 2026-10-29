# monit_hist_usina.py — consolidação do HistRateio

Pega o **rateio novo do mês** de uma distribuidora, enriquece com os dados da usina (acrônimo) e com
a **Conta Contrato do CRM**, e concatena no arquivo de histórico (`HistRateio`), gerando um Excel
novo com timestamp.

Documentação do arquivo [`monit_hist_usina.py`](monit_hist_usina.py). Os leitores de rateio que ele
consome estão em [`rateio/`](rateio/README.md).

## Por que existe

O HistRateio é a base de acompanhamento de rateio por UC — o que foi enviado, para qual UG, em que
mês, e se a distribuidora aceitou. A cada mês entra um lote novo, que chega no formato da
distribuidora e precisa de três coisas que **não vêm no arquivo dela**:

- **Usina e acrônimo** — o arquivo traz só o número da UG.
- **Conta Contrato (CC)** — o vínculo UC → CC mora no CRM.
- **Layout do histórico** — nomes de coluna, `Id`, `Chave`, `Aceitou Rateio?`.

Fazer isso à mão é colar 200 linhas num Excel e procurar acrônimo por UG. O script faz o de/para,
valida, e **nunca escreve no histórico original** — sempre gera arquivo novo.

## ⚠️ Antes de rodar: as 4 variáveis do topo

Este é o ponto mais escorregadio do job. O bloco `CONFIGURAÇÕES` (linhas ~28-55) tem **quatro
valores que precisam ser ajustados juntos e falam de coisas diferentes**:

| Variável | Exemplo | O que é |
|---|---|---|
| `distribuidora_escolhida` | `"EQUATORIAL GO"` | qual leitor usar. Tem que existir em `LEITORES` |
| `mes_pasta_rateio` | `"04.2026"` | **nome da subpasta** dentro de `7. Rateio/<distribuidora>/` |
| `mes_envio` (linha ~81) | `converter_mes_envio("04/2026")` | mês que vai **carimbado** em cada linha do rateio |
| `allocation_month` | `"2026-06"` | mês usado para **achar o arquivo do HistRateio** na pasta `_processado` |

Sim: `mes_pasta_rateio` e `mes_envio` costumam ser o mesmo mês escrito de duas formas, e
`allocation_month` costuma ser **outro** mês. Não são redundantes e não dá para inferir um do outro
— o rateio de abril é consolidado no histórico de junho. **Confira os três a cada execução**; errar
um não quebra nada, só produz um arquivo errado, silenciosamente.

Há ainda `base_gd`, a raiz da pasta *"Acompanhamento - Operação GD"* no OneDrive. É a única coisa
que muda entre máquinas — `folder_hist` e a pasta de rateio são derivados dela. **Não edite no
código**: o default parte da sua home (`~\Serena\Comercializadora - OMG\...`); se a sua pasta
sincronizada tiver outro nome, defina `BACKOFFICE_GD_DIR` uma vez (ver
[Caminhos locais](../../README.md#5-caminhos-locais-só-se-o-seu-for-diferente) no README raiz).

## As etapas

O script imprime `=== ETAPA N ===` conforme avança — use isso para saber onde parou.

| Etapa | O que faz |
|---|---|
| 1 | Valida `distribuidora_escolhida`, monta os caminhos e confirma que a pasta do mês existe |
| 2 | Conecta no Snowflake e lê `hist_usina_livia` (cadastro de usinas) e `crm` |
| 3 | Normaliza `DISTRIBUIDORA` nas bases auxiliares pelo `map_distribuidoras` |
| 4 | **Lê o rateio** pelo leitor da distribuidora + `validar_soma_rateio` (bloqueante) |
| 5 | Padroniza chaves de merge (string, sem `.0`, vazio → `NA`) |
| — | **DEBUG**: compara UGs do arquivo × UGs do cadastro, e lista duplicados antes dos merges |
| 6 | Merge com o cadastro de usinas → `Usina`, `Acrônimo` (`validate="many_to_one"`) |
| 7 | Merge com o CRM → `CC`; exporta CSV das **UCs sem CC** |
| 8 | Validação: campos vazios, soma de `%` por UG |
| 9 | Lê o HistRateio pronto (arquivo mais recente que casa com `allocation_month`) |
| 9.1 | Renomeia as colunas do lote novo para o padrão do histórico (`UPPER_SNAKE`) |
| 10 | Cria as colunas que faltam, reordena para o layout exato do histórico |
| 11 | `concat` + conferência de contagem de linhas |
| 12 | Exporta `HistRateio_merge_<DIST>_<timestamp>.xlsx` com formatação de data |

## Decisões e por quê

### O histórico nunca é sobrescrito

A saída é sempre um arquivo **novo**, com timestamp, na pasta `_processado`. O histórico é o registro
do que foi enviado à distribuidora — não existe "corrigir uma linha". Se a consolidação sair errada,
você apaga o arquivo gerado e roda de novo; o insumo continua intacto.

### `validate="many_to_one"` nos dois merges

Os merges são declarados com `validate="many_to_one"`: se a chave do lado direito estiver duplicada,
o pandas **levanta erro** em vez de multiplicar as linhas do rateio. Isso importa porque duplicar
linha de rateio inflaria a soma da UG sem que a soma pareça errada em nenhum lugar óbvio.

Como o cadastro e o CRM *têm* duplicados de verdade, há um `drop_duplicates` deliberado antes de cada
merge (`keep="first"`, após ordenar) — e o bloco de DIAGNÓSTICO imprime quais chaves estavam
duplicadas. **Não remova esses prints**: eles são o único aviso de que um de/para tinha ambiguidade.

### `map_distribuidoras`: aliases de sigla

Cadastro, CRM e arquivo da distribuidora usam nomes diferentes para a mesma empresa (`CELGD`,
`CEPISA`, `CEMAR`, `CELPA`, `CPFLPAULISTA`…). O dicionário normaliza tudo para o nome usado no
rateio, e `fillna` preserva quem não estiver mapeado. Distribuidora nova → acrescente o alias aqui,
além do leitor em `rateio/`.

### CSV de UCs sem CC é entregável, não log

`ucs_sem_cc_<DIST>_<timestamp>.csv` é gravado na pasta `_processado` toda execução. UC que não casa
com o CRM significa cadastro faltando **do lado do CRM** — é trabalho de outra pessoa, e o CSV é o
que se manda para ela. Não é erro do job: o job segue e deixa `CC` vazio.

### Campos do histórico criados condicionalmente

`Id`, `Chave`, `UC/CC` e `Aceitou Rateio?` só são criados **se a coluna existir no histórico lido**.
O layout do HistRateio já mudou antes; assim, o script se adapta ao arquivo em vez de assumir um
formato.

Regras de formação: `Id` = `UG - UC - M/AAAA`, `Chave` = `ACRONIMO-M/AAAA` — em ambos o mês vai **sem
zero à esquerda** (`6/2026`, não `06/2026`), porque é assim que o histórico sempre gravou. `Aceitou
Rateio?` entra como `"NÃO"`: é o estado inicial, atualizado depois manualmente quando a
distribuidora confirma. `CC/UG` entra vazio de propósito — é preenchido na planilha.

### Erro de usuário sai limpo, sem traceback

A leitura do rateio (etapa 4) está num `try/except (FileNotFoundError, ValueError)` que imprime a
mensagem e faz `sys.exit(1)`. Os erros esperados ali — arquivo não baixado do OneDrive, rateio que
não fecha 100%, nome fora do padrão — são todos acionáveis por quem está rodando, e um traceback de
40 linhas só esconde a instrução.

## Como rodar

Pré-requisitos: VPN, `scripts/jobs_backoffice/.env`, `PYTHONPATH` apontando para `scripts/` (ver
o [README raiz](../../README.md#como-rodar)), OneDrive sincronizado **com os arquivos baixados**
(botão direito na pasta → "Sempre manter neste dispositivo").

1. Abra o [`monit_hist_usina.py`](monit_hist_usina.py) e ajuste as 4 variáveis (ver a seção
   acima). `base_gd` só precisa de `BACKOFFICE_GD_DIR` se o seu caminho fugir do default.
2. ```powershell
   python scripts\jobs_backoffice\monit_hist_usina.py
   ```
3. Autentique o Snowflake no navegador quando abrir.
4. **Leia a saída**, nesta ordem de importância:
   - `Validação de rateio OK` (etapa 4) — se falhou, o script parou e a mensagem diz qual UG.
   - `UGs no df_novo que NÃO existem em df_usinas_sel` — UG sem cadastro fica sem acrônimo.
   - `Linhas sem CC` + o CSV gerado.
   - `OK: concat realizado corretamente` na etapa 11.
5. Confira o `HistRateio_merge_*.xlsx` gerado antes de promovê-lo a histórico oficial.

Para outra distribuidora, mude `distribuidora_escolhida` (e os meses) e rode de novo — uma
distribuidora por execução.

## Limitações conhecidas

- **O script executa no import.** Não há `main()` nem guard `if __name__ == "__main__":`: o código
  roda de cima a baixo, em escopo de módulo. Consequências: não é importável, **não é testável**, e
  não dá para reaproveitar nenhuma etapa. Extrair para funções + `main()` é o refactor mais valioso
  desta pasta, e daria cobertura de teste às etapas 5-11 (que são pandas puro). O bloco de leitura
  de rateio já foi extraído para [`rateio/`](rateio/README.md) — é o caminho a seguir para o
  resto. (O teste desse pedaço, `test_rateio.py`, não veio para este repo; ver o README de
  `rateio/`.)
- **A configuração é edição de código.** Cinco valores por execução, sem argumento de linha de
  comando e sem validação cruzada entre eles. Um `argparse` resolveria e evitaria commit acidental
  de configuração de execução.
- **Só CPFL Paulista e Equatorial GO** têm leitor. As outras distribuidoras seguem manuais.
