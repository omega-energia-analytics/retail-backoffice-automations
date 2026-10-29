import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import yaml
import pandas as pd
import datetime as dt
from utils.src_ingestion import initialize_connections
from paths import CONF_DIR, QUERY_DIR
from colorama import Fore, Style
import warnings
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_conf():
    # Caminho absoluto até o arquivo de configuração
    conf_path = CONF_DIR / "conf_cusd_invoices.yml"

    # Leitura do YAML e conversão para dicionário Python
    with open(conf_path, "r") as file:
        conf = yaml.safe_load(file)

    return conf


def get_query(query_name, model_parameters):
    # Resolve o caminho do arquivo SQL a partir do YAML
    query_path = QUERY_DIR / model_parameters["queries"][query_name]

    # Leitura da query SQL
    with open(query_path, "r") as file:
        query = file.read()

    return query


def main():
    # Carrega configurações do modelo
    conf = get_conf()

    # Inicializa credenciais e conexão com o banco
    access, connection = initialize_connections()

    # Parâmetros específicos do modelo
    model_parameters = conf['model_parameters']

    # Carrega a query de extração do CRM
    query = get_query("crm_extraction", model_parameters)

    # Executa a query e carrega o resultado em um DataFrame
    crm = pd.read_sql(query, connection)

    # Exporta o resultado para CSV com timestamp
    crm.to_csv(
        f"crm_extraction_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        index=False
    )

    # Log simples de sucesso
    print("Extração concluída e salva em CSV!")


# Garante que o script só será executado quando rodado diretamente
# (e não quando importado como módulo)
if __name__ == "__main__":
    print(f"{Fore.MAGENTA}\n=== ETAPA 1: Inicialização ==={Style.RESET_ALL}")
    main()