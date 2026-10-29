"""
Atualiza a coluna NUMERO_NFE em RETAIL_{env}.BACKOFFICE.DIFERIMENTO_PARCERIAS_TESTE
a partir do Excel que a Ana preenche manualmente (conectado via ODBC na view/tabela).

A chave de UPDATE é ID_REGISTRO (PK estavel exposta pelo model dbt), nunca uma
coluna de negocio - ver models/schemas/diferimento_parcerias_teste.yml.

O valor de NUMERO_NFE no Excel e sempre sobrescrito na tabela tal como vier,
inclusive vazio: quem preenche essa coluna e exclusivamente a Ana, entao vazio
significa "ainda nao preenchido", nao "sem informacao a atualizar".

DATA_ULTIMO_LOAD_NFE registra quando cada linha foi tocada por este script, para
confirmar que o load aconteceu. Essa coluna vive fora do model dbt (nao esta no
SELECT do stg_06/mart) porque o model e materialized='table' e recriaria a
tabela do zero a cada build, apagando o valor - o proprio script recria a
coluna via ALTER TABLE ADD COLUMN IF NOT EXISTS sempre que roda.

Uso:
    Edite as constantes EXCEL_PATH e ENV logo abaixo e de "Run" neste arquivo
    no VSCode (nao usa mais argumento de linha de comando).
"""

import re
import sys
from pathlib import Path

import pandas as pd
import snowflake.connector
from cryptography.hazmat.primitives import serialization

# ==========================================================================
# CONFIGURACAO - edite estas linhas antes de rodar
# ==========================================================================

# Caminho completo do Excel com as colunas ID_REGISTRO e NUMERO_NFE.
# PLANILHA QUE PUXAMOS DO SNOWFLAKE VIA POWERQUERY E QUE A ANA PREENCHERÁ MANUALMENTE COM O NUMERO DA NFE.
EXCEL_PATH = Path.home() / "Documents" / "load_diferimento.xlsx"

# Ambiente Snowflake de destino: "dev", "stg" ou "prod".
ENV = "dev"

# Caminho do .env com as credenciais de key-pair auth (SF_ACCOUNT, SF_USER,
# SF_ROLE, SF_WAREHOUSE, PRIVATE_KEY_PATH, PRIVATE_KEY_PASSPHRASE). Cada
# pessoa que rodar este script tem seu proprio usuario/chave neste arquivo.
ENV_PATH = Path.home() / "Documents" / "CODE" / "serena-analytics" / "retail-backoffice" / "dbt-resources" / ".env"

# ==========================================================================

REQUIRED_COLUMNS = ["ID_REGISTRO", "NUMERO_NFE"]


def load_env(path: Path) -> dict:
    values = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([A-Z_]+)\s*=\s*(.*)$", line)
            if match:
                values[match.group(1)] = match.group(2).strip().strip('"')
    return values


def connect(env_vars: dict):
    with open(env_vars["PRIVATE_KEY_PATH"], "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=env_vars["PRIVATE_KEY_PASSPHRASE"].encode(),
        )
    private_key_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return snowflake.connector.connect(
        account=env_vars["SF_ACCOUNT"],
        user=env_vars["SF_USER"],
        role=env_vars["SF_ROLE"],
        warehouse=env_vars["SF_WAREHOUSE"],
        private_key=private_key_der,
    )


def read_updates(excel_path: Path) -> pd.DataFrame:
    df = pd.read_excel(excel_path, dtype={"ID_REGISTRO": str})

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Excel sem as colunas obrigatorias: {missing}")

    df = df[REQUIRED_COLUMNS].copy()

    if df["ID_REGISTRO"].isna().any():
        raise ValueError("Existem linhas sem ID_REGISTRO no Excel - abortando.")

    duplicated = df["ID_REGISTRO"][df["ID_REGISTRO"].duplicated()]
    if not duplicated.empty:
        raise ValueError(
            f"ID_REGISTRO duplicado no Excel: {duplicated.unique().tolist()}"
        )

    df["NUMERO_NFE"] = df["NUMERO_NFE"].where(df["NUMERO_NFE"].notna(), None)
    return df


def apply_updates(conn, table: str, df: pd.DataFrame) -> int:
    cur = conn.cursor()
    try:
        # Coluna de auditoria do load manual - fora do model dbt (materialized='table'
        # recria a tabela do zero a cada build e apagaria o valor). ADD COLUMN IF NOT
        # EXISTS torna a criacao idempotente: cobre tanto a 1a execucao do script quanto
        # qualquer rebuild do dbt que tenha eliminado a coluna.
        cur.execute(
            f"ALTER TABLE {table} "
            "ADD COLUMN IF NOT EXISTS DATA_ULTIMO_LOAD_NFE TIMESTAMP_NTZ"
        )
        cur.execute(
            f"CREATE OR REPLACE TEMPORARY TABLE {table}__NFE_STAGING "
            "(ID_REGISTRO VARCHAR, NUMERO_NFE VARCHAR)"
        )
        rows = list(df.itertuples(index=False, name=None))
        cur.executemany(
            f"INSERT INTO {table}__NFE_STAGING (ID_REGISTRO, NUMERO_NFE) "
            "VALUES (%s, %s)",
            rows,
        )
        cur.execute(
            f"""
            UPDATE {table} AS t
            SET t.NUMERO_NFE = s.NUMERO_NFE,
                t.DATA_ULTIMO_LOAD_NFE = CURRENT_TIMESTAMP()
            FROM {table}__NFE_STAGING AS s
            WHERE t.ID_REGISTRO = s.ID_REGISTRO
            """
        )
        updated = cur.rowcount
        conn.commit()
        return updated
    finally:
        cur.close()


def main():
    excel_path = Path(EXCEL_PATH)
    if ENV not in ("dev", "stg", "prod"):
        sys.exit(f"ENV invalido: {ENV!r} (use 'dev', 'stg' ou 'prod')")
    if not excel_path.exists():
        sys.exit(f"Arquivo nao encontrado: {excel_path}")

    env_vars = load_env(ENV_PATH)
    database = f"RETAIL_{ENV.upper()}"
    table = f"{database}.BACKOFFICE.DIFERIMENTO_PARCERIAS_TESTE"

    df = read_updates(excel_path)
    print(f"{len(df)} linha(s) lida(s) do Excel.")

    conn = connect(env_vars)
    try:
        updated = apply_updates(conn, table, df)
        print(f"{updated} linha(s) atualizada(s) em {table}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
