import pandas as pd
import yaml
from utils.src_usinas import initialize_connections
from utils.utils_usinas import (
    get_conf_by_project,
    get_query,
    cross_join,
    create_months_dataframe,
    handle_double_merges_same_df,
    manual_file_ingestion_shp
)
import xlwings as xw
import datetime as dt
from snowflake.connector.pandas_tools import write_pandas

access_token, connection = initialize_connections()

def publish_to_snowflake(df):

    success, nchunks, nrows, _ = write_pandas(
    conn=connection,
    df=df,
    database='RETAIL_DEV',
    schema='BACKOFFICE',
    table_name="MONITORAMENTO_CUSD_DE",  # upper case = no quoting needed
    auto_create_table=True,
    overwrite=True  # set to False if you want to append instead
    )

    return success, nchunks, nrows


def create_table():

    conf = get_conf_by_project('cusd_invoices')
    model_parameters = conf["model_parameters"]

    # Ingestion of Input and output tables

    # Manual input - backoffice
    drive_id =  model_parameters["input_files"]["shp"]["drive_id"]
    file_path = model_parameters["input_files"]["shp"]["filepath"]
    file_name = model_parameters["input_files"]["workbook_name"]
    usinas = manual_file_ingestion_shp(
        access_token,
        drive_id,
        file_path,
        file_name
    ).fillna("0")

    # Convert columns to string
    usinas["INSTALACAO"] = usinas["INSTALACAO"].astype("int64").astype("str")
    usinas["DATA_INICIO"] = usinas["DATA_INICIO"].astype("str")

    # Dataframe with all first days
    start_date = dt.datetime.strptime(model_parameters["start_date"], "%d/%m/%Y").date()
    datas = create_months_dataframe(start_date)

    # Invoices
    query = get_query("fattureweb_usinas", model_parameters)
    ref_fattureweb = pd.read_sql(query, connection)

    # Cross join for date purposes
    df = cross_join(usinas, datas)
    df["CHAVE"] = df["INSTALACAO"] + "_" + df["MES"]

    # Creation of key columns for merging with template
    ref_fattureweb["CHAVE_INSTALACAO"] = (
        ref_fattureweb["NUMERO_DA_INSTALACAO"] + "_" +
        ref_fattureweb["MES_DE_REFERENCIA_DA_FATURA"]
    )
    ref_fattureweb["CHAVE_CONTRATO"] = (
        ref_fattureweb["CONTRATO"] + "_" +
        ref_fattureweb["MES_DE_REFERENCIA_DA_FATURA"]
    )

    # Merging invoices with the base table and handling columns with repeated names
    df_merged = (
        df
        .merge(ref_fattureweb, left_on="CHAVE", right_on="CHAVE_INSTALACAO", how="left")
        .merge(ref_fattureweb, left_on="CHAVE", right_on="CHAVE_CONTRATO", how="left")
        .drop(columns = ["index", "key"])
    )
    df_merged_adjusted = handle_double_merges_same_df(df_merged)

    return df_merged_adjusted


def flow():

    print("Creating table for monitoring of plant payments...")

    df = create_table()

    print("Table created successfully!")

    print("Publishing table on snowflake...")

    date = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df["upload_date"] = date
    success, nchunks, nrows = publish_to_snowflake(df)

    print("Table published successfully at {date}.".format(date=date))
    print("""
          Returned values:
            success: {success}
            nchunks: {nchunks}
            nrows: {nrows}
          """.format(success=success, nchunks=nchunks, nrows=nrows))
    