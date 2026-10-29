
import pandas as pd
import xlwings as xw
import datetime as dt
import numpy as np
import yaml
import requests
import unicodedata
from pathlib import Path
from colorama import Fore, Style
from datetime import datetime
import re
from urllib.parse import quote
from io import BytesIO
from paths import QUERY_DIR


def log_info(msg):
    print(f"{Fore.CYAN}[{datetime.now():%H:%M:%S}] {msg}")


def log_success(msg):
    print(f"{Fore.GREEN}[{datetime.now():%H:%M:%S}] ✅ {msg}")


def log_error(msg):
    print(f"{Fore.RED}[{datetime.now():%H:%M:%S}] ❌ {msg}")


def get_conf_by_project(project):
    # with open(f'conf/conf_{project}.yml', 'r') as file:     # usar no rateio
    conf_path = Path(__file__).resolve().parent.parent / 'conf' / f'conf_{project}.yml'
    with open(conf_path, 'r') as file:
        conf = yaml.safe_load(file)
    return conf


def get_query(query_name, model_parameters):
    with open(QUERY_DIR / model_parameters["queries"][query_name], "r") as file:
        query = file.read()
    return query


def fill_in_column(cell: str, series: pd.Series, sheet: xw.Sheet) -> list:
    # Lista de listas (NaN -> None): não depende de como a versão do xlwings/pandas/numpy
    # instalada trata ndarray 2D, que quebrava no pd.isna do xlwings.
    input_data = [[None if pd.isna(v) else v] for v in series.tolist()]
    sheet.range(cell).value = input_data
    return input_data


def clear_column_content(cell: str, sheet: xw.Sheet) -> list: 
    target_range = sheet.range(cell).expand('down')
    cleared_content = sheet.range(target_range).value
    sheet.range(target_range).clear_contents()
    return cleared_content


def change_column_formatting(cell: str, sheet: xw.Sheet, format: str) -> list: 
    target_range = sheet.range(cell).expand('down')
    changed_content = sheet.range(target_range).value
    sheet.range(target_range).number_format = format
    return changed_content


def cross_join(df_left: pd.DataFrame, df_right: pd.DataFrame) -> pd.DataFrame:
    df_left_copy = df_left.copy()
    df_right_copy = df_right.copy()

    df_left_copy["key"] = 0
    df_right_copy["key"] = 0

    cross_joined_df = (
        df_left_copy
        .merge(df_right_copy, on = "key", how = "outer")
        .reset_index()
    )

    return cross_joined_df


def standardize_string(text: str, separator: str = "_") -> str:
    if not isinstance(text, str):
        return ""

    # Lowercase and remove accents
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("utf-8").lower()

    # Replace common separators with the chosen separator
    text = re.sub(r"[ \-\/\\\.]+", separator, text)

    # Remove anything that's not a-z, 0-9, or the separator
    if separator != "":
        escaped_separator = re.escape(separator)
        text = re.sub(fr"[^a-z0-9{escaped_separator}]", "", text)

        # Collapse multiple separators
        text = re.sub(fr"{escaped_separator}+", separator, text)

    # Strip leading/trailing separators
    text = text.strip()

    return text


def create_months_dataframe(start_date: dt.date):
    today = dt.date.today()

    # Generate list of 1st days
    first_of_months = []
    current = start_date

    while current <= today:
        first_of_months.append(current.strftime("%d/%m/%Y"))
        # Move to the 1st of the next month
        if current.month == 12:
            current = dt.date(current.year + 1, 1, 1)
        else:
            current = dt.date(current.year, current.month + 1, 1)

    return pd.DataFrame({"MES":first_of_months})


def handle_double_merges_same_df(df):
    merged_columns = [column[:-2] for column in df.columns if column.endswith('_x')]
    full_schema = set([column.removesuffix('_x').removesuffix('_y') for column in df.columns])

    for col in merged_columns:
        df[col] = (
            np
            .where(
                df[col+"_x"].isna(),
                df[col+"_y"],
                df[col+"_x"]
            )
        )
    return df[list(full_schema)]


def manual_file_ingestion_shp(access_token, drive_id, file_path, file_name, header=0):
    encoded_path = '/'.join([file_path,file_name])
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded_path}:/content"

    try:
        # Make the GET request with the token
        response = requests.get(url, headers={"Authorization": f"Bearer {access_token}"})
        # print(f"Status Code: {response.status_code}")
        
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição manual_file_ingestion: {e}")
        print("Verifique se o arquivo existe no OneDrive e se o token de acesso é válido.")
    
    df = pd.read_excel(BytesIO(response.content), engine="openpyxl", header=header)
    return df


def get_all_files_shp(model_parameters, access_token):

    drive_id = model_parameters['input_files']['drive_id']
    filepath = model_parameters['input_files']['celpe']['filepath']
    filename = model_parameters['input_files']['celpe']['filename']

    url = f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{filepath}:/children'

    res = requests.get(url, headers={"Authorization": f"Bearer {access_token}"})

    if res.status_code == 200:
        files = [file for file in eval(res.content)['value']]
        found_files = [re.match(filename, file['name'])[0] for file in files]
        return found_files
    
    else:
        raise FileNotFoundError("Error: Não foi possível encontrar o diretório esperado")
        