"""
Leitor de rateio da EQUATORIAL GO.

A Equatorial já mandou três layouts diferentes — o leitor aceita os três, porque
o job reprocessa meses passados:

  até 05/2026  aba única "Modelo Equatorial GO"; colunas "% kWh" + "Conta Contrato"
  06/2026      aba única "2";                    colunas "% do Excedente" + "Conta Contrato"
  07/2026 em   5 abas (ROTEIRO/0/1/2/FONTES),    colunas "% do Excedente" + "Unidade Consumidora"
               tabela na aba "2"

Nada disso fica fixo no código: a tabela é PROCURADA (aba a aba, linha a linha)
pela dupla de rótulos, a UG sai da célula "... da Unidade Geradora" e a escala do
% é decidida pela soma do arquivo. Ver README.md desta pasta.
"""

import os
import re
from pathlib import Path

import pandas as pd

from .base import agregar_rateios, finalizar_rateio

DISTRIBUIDORA = "EQUATORIAL GO"

# Rótulos da coluna de UC. A Equatorial chama de "Conta Contrato" até 06/2026 e de
# "Unidade Consumidora" a partir de 07/2026 — mas é o MESMO identificador (validado
# contra o HistRateio: 100% dos valores de 06/2026 casam com a coluna UC do
# histórico e ~0% com a coluna CC). Aqui é sempre "UC".
ROTULOS_UC = ("CONTA CONTRATO", "UNIDADE CONSUMIDORA")

# Rótulos da coluna de percentual.
ROTULOS_PCT = ("% KWH", "% DO EXCEDENTE")

# A célula que guarda a UG vem como "Conta Contrato da Unidade Geradora" ou
# "Unidade Consumidora da Unidade Geradora" — o sufixo é o que a distingue dos
# rótulos de coluna acima.
SUFIXO_UG = "DA UNIDADE GERADORA"


def listar_arquivos(folder_path):
    folder = Path(folder_path)

    if not folder.exists():
        raise FileNotFoundError(f"Pasta Equatorial GO não encontrada: {folder_path}")

    arquivos = [
        f for f in folder.iterdir()
        if f.is_file()
        and f.suffix.lower() in [".xlsx", ".xlsm"]
        and not f.name.startswith("~$")
        and f.name.lower().startswith("rateio - equatorial")
    ]

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum Excel de rateio Equatorial GO encontrado em: {folder_path}"
        )

    arquivos = sorted(arquivos, key=lambda x: x.name)

    print(f"\nArquivos Equatorial GO encontrados: {len(arquivos)}")
    for arq in arquivos:
        print("-", arq.name)

    return arquivos


def _em_maiuscula(df):
    return df.astype(str).apply(lambda c: c.str.strip().str.upper())


def _eh_rotulo_uc(valor):
    # "CONTA CONTRATO DA UNIDADE GERADORA" é a célula da UG, não o cabeçalho da
    # coluna — por isso o sufixo é excluído aqui.
    return any(r in valor for r in ROTULOS_UC) and SUFIXO_UG not in valor


def _eh_rotulo_pct(valor):
    return any(r in valor for r in ROTULOS_PCT)


def localizar_tabela(abas):
    """
    Acha (aba, linha do cabeçalho) da tabela de rateio.

    A linha do cabeçalho e a ABA variam entre layouts, então nenhuma das duas é
    assumida: procuramos a primeira linha que tenha, JUNTAS, uma coluna de UC e
    uma de percentual.
    """
    for nome_aba, raw in abas.items():
        texto = _em_maiuscula(raw)

        for idx, linha in texto.iterrows():
            valores = [v for v in linha if v and v != "NAN"]

            if any(_eh_rotulo_uc(v) for v in valores) and any(
                _eh_rotulo_pct(v) for v in valores
            ):
                return nome_aba, idx

    return None, None


def extrair_ug_da_planilha(abas):
    """UG a partir da célula '<...> da Unidade Geradora' — vale mais que o nome
    do arquivo, que a Equatorial já mudou duas vezes."""
    for raw in abas.values():
        texto = _em_maiuscula(raw)

        for idx, linha in texto.iterrows():
            if not any(SUFIXO_UG in v for v in linha if v):
                continue

            for valor in raw.iloc[idx]:
                if pd.isna(valor):
                    continue
                valor = str(valor).strip().replace(".0", "")
                if valor.isdigit():
                    return valor

    return None


def extrair_ug_do_nome(nome_arquivo):
    """Fallback: UG pelo nome do arquivo, nos dois padrões já vistos —
    'Rateio - Equatorial - <UG> - ...' e 'Rateio - Equatorial - <acrônimo> - <UG> - ...'."""
    match = re.search(
        r"Rateio\s*-\s*Equatorial\s*-\s*(?:[A-Za-z]{2}-[A-Za-z]{3}-[\d.]+\s*-\s*)?(\d+)",
        nome_arquivo,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def escalar_percentual(serie, nome_arquivo):
    """
    Converte a coluna de % para FRAÇÃO, decidindo a escala pela soma do arquivo.

    Um rateio sempre totaliza 100% — então a soma diz a escala sem ambiguidade:
    ~100 é escala percentual (÷100), ~1 já é fração. Até 06/2026 a Equatorial
    mandava percentual ("% Total" = 100); desde 07/2026 manda fração ("% Total" =
    0,999...). Qualquer outra soma é arquivo torto e para aqui, com o número na
    mensagem.

    ATENÇÃO: isto é decidido pelo TOTAL do arquivo, nunca por valor individual.
    A heurística antiga "if x > 1: x/100" olhava linha a linha e deixava passar
    UC com rateio abaixo de 1% (0,94 virava 94%) — ver README.md.
    """
    soma = serie.sum()

    if abs(soma - 1) <= 0.01:
        return serie

    if abs(soma - 100) <= 1:
        return serie / 100

    raise ValueError(
        f"Escala do % não reconhecida em {nome_arquivo}: as linhas somam "
        f"{soma:.6f}, e o esperado era ~1 (fração) ou ~100 (percentual). "
        f"Confira se a planilha está completa e se a coluna lida é a de rateio."
    )


def ler_rateio(caminho_excel, data_hoje, mes_envio):
    nome_arquivo = os.path.basename(caminho_excel)

    # sheet_name=None lê o workbook inteiro de uma vez: a aba da tabela mudou de
    # nome e de posição entre layouts, e desde 07/2026 nem é mais a primeira
    # (a primeira virou "ROTEIRO", um texto de instruções).
    abas = pd.read_excel(caminho_excel, sheet_name=None, header=None, dtype=str)

    ug = extrair_ug_da_planilha(abas) or extrair_ug_do_nome(nome_arquivo)

    if not ug:
        raise ValueError(
            f"UG não encontrada em {nome_arquivo}: nem no nome do arquivo, nem na "
            f"célula '... da Unidade Geradora' da planilha. Quando o export da "
            f"Equatorial sai com erro de fórmula, os dois campos vêm com o texto "
            f"do erro (ex.: 'Erro 2042'). Peça o reexport do arquivo, ou renomeie "
            f"trocando o trecho do erro pelo número da instalação da UG."
        )

    nome_aba, linha_header = localizar_tabela(abas)

    if linha_header is None:
        raise ValueError(
            f"Cabeçalho da tabela não encontrado em: {nome_arquivo} "
            f"(procurei {ROTULOS_UC} junto de {ROTULOS_PCT} em todas as abas: "
            f"{list(abas)})"
        )

    df = pd.read_excel(
        caminho_excel,
        sheet_name=nome_aba,
        header=linha_header,
        dtype=str
    )

    df.columns = [
        str(c)
        .strip()
        .replace("\n", " ")
        .replace("  ", " ")
        for c in df.columns
    ]

    col_percentual = next(c for c in df.columns if _eh_rotulo_pct(c.upper()))
    col_uc = next(c for c in df.columns if _eh_rotulo_uc(c.upper()))

    df = df.rename(columns={
        col_percentual: "%",
        col_uc: "UC"
    })

    df = df[["UC", "%"]].copy()
    df = df.dropna(subset=["UC", "%"], how="all")

    df["UC"] = (
        df["UC"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )

    # astype(str) transforma célula vazia no texto "nan", que escapa do dropna.
    # Reverter para nulo garante que linhas sem UC (ex.: a linha "TOTAL" no rodapé,
    # ou as listas de valores que a planilha nova mantém numa coluna à direita)
    # sejam descartadas e não entrem no rateio.
    df["UC"] = df["UC"].replace({
        "nan": pd.NA,
        "None": pd.NA,
        "<NA>": pd.NA,
        "": pd.NA,
    })

    df["%"] = (
        df["%"]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.strip()
    )

    df["%"] = pd.to_numeric(df["%"], errors="coerce")

    df = df.dropna(subset=["UC", "%"])

    df["%"] = escalar_percentual(df["%"], nome_arquivo)

    df["UG"] = str(ug).replace(".0", "").strip()

    df_final = finalizar_rateio(df, DISTRIBUIDORA, data_hoje, mes_envio)

    print(
        f"{nome_arquivo} | aba {nome_aba!r} | header linha {linha_header} "
        f"| UG {ug} | {len(df_final)} UCs | Soma {df_final['%'].sum()}"
    )

    return df_final


def ler_todos_rateios(folder, data_hoje, mes_envio):
    return agregar_rateios(listar_arquivos, ler_rateio, folder, data_hoje, mes_envio)
