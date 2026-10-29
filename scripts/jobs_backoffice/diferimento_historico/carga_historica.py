import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import pandas as pd
from utils.src_ingestion import initialize_connections
from utils.utils_snowflake import load_data
from utils.utils_ingestion import log_error, log_info, log_success

DATABASE = "RETAIL_DEV"
SCHEMA = "BACKOFFICE"
TABLE_NAME = "DIFERIMENTO_COMISSAO_RAW"
INPUT_FILE = os.path.join(os.path.dirname(__file__), "Diferimento Comissão 13.10.xlsx")


def read_diferimento(filepath):
    df = pd.read_excel(filepath, sheet_name="DIFERIMENTO ")
    # Colunas soltas fora da tabela (célula perdida no Excel, sem relação com as linhas)
    df = df.drop(columns=[c for c in df.columns if c.startswith("Unnamed:")])
    return df


def main():
    log_info(f"Lendo planilha: {INPUT_FILE}")
    df = read_diferimento(INPUT_FILE)
    log_success(f"{len(df)} linhas lidas")

    _, conn = initialize_connections()
    if conn is None:
        log_error("Não foi possível conectar ao Snowflake")
        return

    try:
        log_info(f"Truncando {DATABASE}.{SCHEMA}.{TABLE_NAME}")
        conn.cursor().execute(f"TRUNCATE TABLE IF EXISTS {DATABASE}.{SCHEMA}.{TABLE_NAME}")

        log_info(f"Carregando dados em {DATABASE}.{SCHEMA}.{TABLE_NAME}")
        load_data(df, DATABASE, SCHEMA, TABLE_NAME, conn)
        log_success("Load concluído")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
