
import pandas as pd
import datetime as dt
import numpy as np
import yaml
import requests
import unicodedata
import pdfplumber
import pandas as pd
import os
import re
from datetime import datetime
from colorama import Fore, Style
from datetime import datetime
from urllib.parse import quote
from io import BytesIO
from paths import QUERY_DIR


def log_info(msg):
    print(f"{Fore.CYAN}[{datetime.now():%H:%M:%S}] {msg}")


def log_success(msg):
    print(f"{Fore.GREEN}[{datetime.now():%H:%M:%S}] ✅ {msg}")


def log_error(msg):
    print(f"{Fore.RED}[{datetime.now():%H:%M:%S}] ❌ {msg}")


def get_query(query_name, model_parameters):
    with open(QUERY_DIR / model_parameters["queries"][query_name], "r") as file:
        query = file.read()
    return query


# Função para limpar valores numéricos
def clean_value(value):
    if pd.isna(value):
        return ""
    value = str(value).strip()
    value = re.sub(r"[^\d,.-]", "", value)  # Mantém apenas dígitos, vírgulas, pontos e sinal de menos
    return value


def adjust_date(value):
    mapping = {
        'jan': 1,
        'fev': 2,
        'mar': 3,
        'abr': 4,
        'mai': 5,
        'jun': 6,
        'jul': 7,
        'ago': 8,
        'set': 9,
        'out': 10,
        'nov': 11,
        'dez': 12
        }
    
    

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


def get_binary_data_from_file(access_token, model_parameters, distributor, filename):

    drive_id = model_parameters['input_files']['drive_id']
    filepath = model_parameters['input_files'][distributor]['filepath']
    fullpath = '/'.join([filepath,filename])

    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{fullpath}:/content"

    try:
        # Make the GET request with the token
        response = requests.get(url, headers={"Authorization": f"Bearer {access_token}"})
        return BytesIO(response.content)
        
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição manual_file_ingestion: {e}")
        print("Verifique se o arquivo existe no OneDrive e se o token de acesso é válido.")


def get_all_files_shp(model_parameters, access_token, distributor):

    drive_id = model_parameters['input_files']['drive_id']
    filepath = model_parameters['input_files'][distributor]['filepath']
    filename = model_parameters['input_files'][distributor]['filename']
    format = model_parameters['input_files'][distributor]['format']

    url = f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{filepath}:/children'

    res = requests.get(url, headers={"Authorization": f"Bearer {access_token}"})

    if res.status_code == 200:
        files = [file for file in eval(res.content)['value']]
        found_files = [re.match(filename, file['name'])[0] for file in files if file['name'].endswith(format)]
        return found_files
    
    else:
        raise FileNotFoundError("Error: Não foi possível encontrar o diretório esperado")


def get_tables_from_pdf(binary):
    
    tabelas = []
    # Cabeçalhos esperados
    cabecalho_completo = [
        "mes", "instalacao", "rateio", "saldo_anterior_kwh",
        "energia_consumida_kwh", "energia_recebida_kwh",
        "energia_compensada_kwh", "saldo_acumulado_kwh"
    ]
    
    cabecalho_resumido = [
        "codigo_cliente", "rateio", "saldo_acumulado_kwh"
    ]
    
    # Leitura e tratamento das tabelas
    with pdfplumber.open(binary) as doc:
        log_info(f"Total de páginas: {len(doc.pages)}")
        for i, page in enumerate(doc.pages):
            tables = page.extract_tables()
            log_info(f"🔍 {len(tables)} tabela(s) encontrada(s) na página {i + 1}")
            for idx, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue
    
                # Verifica se é modelo completo pela frase "SCEE - Beneficiárias"
                if any("scee_beneficiarias" in standardize_string(cell) for row in table for cell in row if cell):
                    header_index = None
                    for j, row in enumerate(table):
                        if row and standardize_string(row[0]) == "mes":
                            header_index = j
                            break
    
                    if header_index is not None and header_index + 1 < len(table):
                        log_success(f"Tabela 'MODELO COMPLETO' identificada na página {i + 1}, tabela {idx + 1}")
                        data_rows = table[header_index + 1:]
                        df = pd.DataFrame(data_rows, columns=cabecalho_completo)
                        df.replace("-", "", inplace=True)
    
                        # Limpa espaços e caracteres indesejados, exceto na coluna 'mes'
                        for col in df.columns:
                            if col != "mes":
                                df[col] = df[col].apply(clean_value)
    
                        tabelas.append(df)
                    else:
                        log_error(f"Cabeçalho 'Mês' não encontrado ou sem dados abaixo na página {i + 1}, tabela {idx + 1}")
                    continue
    
                # Verifica se é modelo resumido
                primeira_linha = table[0]
                primeira_celula = standardize_string(primeira_linha[0])
                if "resumo_do_saldo_de_credito_por_unidade" in primeira_celula:
                    log_success(f"Tabela 'MODELO RESUMIDO' identificada na página {i + 1}, tabela {idx + 1}")
                    df = pd.DataFrame(table[1:], columns=cabecalho_resumido)
                    df.replace("-", "", inplace=True)

    
                    # Limpa espaços e caracteres indesejados
                    for col in df.columns:
                        df[col] = df[col].apply(clean_value)
    
                    tabelas.append(df)
                elif "scee_geracao" in primeira_celula:
                    dados_geracao = table[2]
                    unidade_geradora = dados_geracao[1]
                    geracao_excedente = dados_geracao[3]
                    log_success(f"Unidade Geradora encontrada: {unidade_geradora}")
                    log_success(f"Geração Excedente encontrada: {geracao_excedente}")
                else:
                    log_success(f"Tabela não reconhecida na página {i + 1}, tabela {idx + 1}")
                    log_info(f"Colunas encontradas: {primeira_linha}")
    
    # Combina todas as tabelas reconhecidas
    if tabelas:
        df_final = pd.concat(tabelas, ignore_index=True)
        df_final = df_final.where(pd.notnull(df_final), "")
        df_final['unidade_geradora'] = unidade_geradora
        df_final['geracao_excedente'] = geracao_excedente
        for col in df_final.columns:
            df_final[col] = df_final[col].str.replace('.','')
            df_final[col] = df_final[col].str.replace(',','.')
    else:
        log_error("Nenhuma tabela válida encontrada.")
        df_final = pd.DataFrame()
    
    return df_final


def parse_shp_file(access_token, model_parameters, filename, distributor):

    log_info(f"Realizando leitura dos dados no sharepoint")

    format = model_parameters["input_files"][distributor]["format"]
    binary = get_binary_data_from_file(access_token, model_parameters, distributor, filename)

    log_info(f"Lendo arquivo de formato {format}...")
    if format == 'xlsx':
        df = pd.read_excel(binary, header = 6)
    
    elif format == 'pdf':
        df = get_tables_from_pdf(binary)
    
    log_success("Arquivo lido com sucesso!")
    return df


def new_processed_filename(filename):
    new_filename = (
        filename[:filename.index('.')]
        + '_processado'
        + datetime.now().strftime("_%Y_%m_%d_%H_%M_%S")
        + filename[filename.index('.'):]
    )
    return new_filename


def get_item_id(url, access_token):
    response = requests.get(url, headers={"Authorization": f"Bearer {access_token}"})
    return eval(response.content)['id']


def move_shp_file(access_token, model_parameters, filename, distributor):

    log_info(f"Movimentando o arquivo {filename} para a pasta _processado")
    drive_id = model_parameters['input_files']['drive_id']
    filepath = model_parameters['input_files'][distributor]['filepath']

    base_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}"

    file_url = f"{base_url}/root:/{filepath}/{filename}"
    destination_url = f"{base_url}/root:/{filepath}/_processado"
    
    file_item_id = get_item_id(file_url, access_token)
    destination_folder_id = get_item_id(destination_url, access_token)
    
    file_item_url = f"{base_url}/items/{file_item_id}"

    headers={
        "Authorization": f"Bearer {access_token}", 
        "Content-Type": "application/json"
    }
    body = {
    "parentReference": {
        "id": destination_folder_id
    },
    "name": new_processed_filename(filename)
    }

    return requests.patch(file_item_url, headers=headers,json=body)
        