"""
Leitor de rateio da CPFL PAULISTA.

Formato: arquivos CSV "Template-InformarRateio*.csv", um por UG.
"""

import os
import re
from pathlib import Path

import pandas as pd

from .base import agregar_rateios, finalizar_rateio

DISTRIBUIDORA = "CPFL PAULISTA"


def listar_arquivos(folder_path):
    folder = Path(folder_path)

    if not folder.exists():
        raise FileNotFoundError(f"Pasta CPFL não encontrada: {folder_path}")

    arquivos = [
        f for f in folder.iterdir()
        if f.is_file()
        and f.suffix.lower() == ".csv"
        and f.name.startswith("Template-InformarRateio")
        and not f.name.startswith("~$")
    ]

    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV CPFL encontrado em: {folder_path}")

    arquivos = sorted(arquivos, key=lambda x: x.name)

    print(f"\nArquivos CPFL encontrados: {len(arquivos)}")
    for arq in arquivos:
        print("-", arq.name)

    return arquivos


def ler_rateio(caminho_csv, data_hoje, mes_envio):
    nome_arquivo = os.path.basename(caminho_csv)

    match = re.search(r"(\d+)", nome_arquivo)

    if not match:
        raise ValueError(f"UG não encontrada no nome: {nome_arquivo}")

    ug = match.group(1)

    df = pd.read_csv(caminho_csv, encoding="utf-8-sig")

    df = df.rename(columns={
        "uc": "UC",
        "rateio": "%"
    })

    df["UG"] = ug

    df["UC"] = (
        df["UC"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )

    df["UG"] = (
        df["UG"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )

    df["%"] = pd.to_numeric(df["%"], errors="coerce") / 100

    df_final = finalizar_rateio(df, DISTRIBUIDORA, data_hoje, mes_envio)

    print(f"{nome_arquivo} | UG {ug} | Soma {df_final['%'].sum()}")

    return df_final


def ler_todos_rateios(folder, data_hoje, mes_envio):
    return agregar_rateios(listar_arquivos, ler_rateio, folder, data_hoje, mes_envio)
