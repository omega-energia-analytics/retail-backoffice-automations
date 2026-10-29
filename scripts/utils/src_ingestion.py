from dotenv import load_dotenv
import os
import requests
import snowflake.connector as snowflake
from colorama import Fore, Style
from datetime import datetime
from utils.utils_usinas import log_error, log_info, log_success


def initialize_connections():
    try:
        # Carrega variáveis de ambiente (independente do CWD de onde o script é chamado)
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", "jobs_backoffice", ".env"))
        tenant_id = os.getenv("TENANT_ID")
        client_id = os.getenv("CLIENT_ID")
        client_secret = os.getenv("CLIENT_SECRET")
        if not all([tenant_id, client_id, client_secret]):
            raise ValueError("Uma ou mais variáveis de ambiente não foram encontradas.")
        log_success("Variáveis de ambiente carregadas com sucesso!")

        # Define a URL para obtenção do token OAuth
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        
        # Configura os dados para a requisição do token OAuth
        token_data = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default'
        }

        # Envia requisição POST para obter o token
        print(f"{Fore.MAGENTA}\n=== ETAPA 2: Autenticação ==={Style.RESET_ALL}")
        log_info("Requisitando token...")
        response = requests.post(token_url, data=token_data, timeout=10)
        response.raise_for_status()  # Levanta exceção para status != 200
        access_token = response.json()['access_token']   
        log_info("Requisição Token - Código de status: 200")
        log_success("Token de Acesso obtido com sucesso!")

        # Estabelece conexão com o banco de dados Snowflake
        print(f"{Fore.MAGENTA}\n=== ETAPA 3: Conexão Snowflake ==={Style.RESET_ALL}")
        log_info("Estabelecendo conexão com Snowflake...")
        connection = snowflake.connect(
            account=os.getenv("SF_ACCOUNT"),
            user=os.getenv("SF_USERNAME"),
            # password=os.getenv("SF_PASSWORD"),
            authenticator="externalbrowser",
            warehouse=os.getenv("SF_WAREHOUSE"),
            database=os.getenv("SF_DATABASE"),
            schema=os.getenv("SF_SCHEMA"),
            clientStoreTemporaryCredential = True
        )
        log_success("Conexão Snowflake estabelecida com sucesso!")

        return access_token, connection

    except Exception as e:
        log_error(f"Erro na inicialização das conexões: {e}")
        return None, None
    