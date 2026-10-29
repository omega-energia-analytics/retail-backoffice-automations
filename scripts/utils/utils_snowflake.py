import json
import os
import boto3
import pandas as pd

from pandas.api.types import is_datetime64_any_dtype
from dotenv import load_dotenv
from snowflake import connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from snowflake.connector.pandas_tools import write_pandas


# Load environment variables from .env file (caminho explícito: sem ele a busca parte de
# utils/ e não acha o .env de jobs_backoffice/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "jobs_backoffice", ".env"))

# Environment configuration
STAGE = os.getenv('STAGE')
DOMAIN = os.getenv('DOMAIN')
SCHEMA = os.getenv('SCHEMA')


def get_snowflake_connection():

    parameter_store_session = boto3.client('ssm', region_name='us-east-1')
    snowflake_credentials = json.loads(
        parameter_store_session
        .get_parameter(Name='/snowflake/retailservice_prod/rsa', WithDecryption=True)['Parameter']['Value']
    )
    private_key = snowflake_credentials['private']
    passphrase = snowflake_credentials['passphrase']

    p_key = serialization.load_pem_private_key(
        private_key.encode(), password=passphrase.encode(), backend=default_backend())

    pkb = p_key.private_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )

    conn = connector.connect(
        user=snowflake_credentials['username'],
        account=snowflake_credentials['account'],
        private_key=pkb,
        )
    
    return conn

def get_data(query, conn):
    return pd.read_sql(query, conn)


def load_data(df, database, schema, table_name, conn):
    df_str = format_dataframe(df)
    success, nchunks, nrows, _ = write_pandas(conn, df_str, table_name=table_name, database=database, schema=schema, auto_create_table=True)
    print(f"Success: {success}, Number of chunks: {nchunks}, Number of rows: {nrows}")


def create_table(columns, database, schema, table_name, conn):
    cols_statement = ''
    counter = 0
    for col in columns:
        cols_statement += f'{col.upper()} VARCHAR(16777216)'
        counter += 1
        if counter < len(columns):
            cols_statement += ',\n'

    conn.cursor().execute(f"""
        CREATE TABLE IF NOT EXISTS {database}.{schema}.{table_name} (
        {cols_statement}
        )
    """
    )


def format_dataframe(df: pd.DataFrame):

    df_str = df.copy()
    df_str.columns = df_str.columns.str.upper()

    
    for i in df_str.columns:
        if is_datetime64_any_dtype(df_str[i]):
            df_str[i] = df_str[i].dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            df_str[i] = df_str[i].astype(str)
            
    df_str = df_str.replace('nan', None)
    df_str = df_str.replace('NaT', None)

    return df_str
