import pandas as pd
import sqlite3
import os
import sys
import yaml
import warnings
import requests
import snowflake.connector as snowflake
from datetime import datetime
from dotenv import load_dotenv
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.utils_usinas import log_error
from paths import CONF_DIR, QUERY_DIR
from pyfiglet import figlet_format


# ==============================
# CONFIGURAÇÕES NFF
# ==============================

ABA = "NFFs"
ARQUIVO_EXCEL = r"C:\Users\vinicius.azevedo\Faturas Oracle\CreateQuickInvoices.xlsm"
DB_PATH = r"C:\Users\vinicius.azevedo\Faturas Oracle\controle_nff.db"
HEADER_LINHA = 7

# ==============================
# UTILITÁRIOS
# ==============================

def limpar_tela():
    os.system('cls' if os.name == 'nt' else 'clear')

def conectar_db():
    return sqlite3.connect(DB_PATH)

def inicializar_banco():
    with conectar_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS controle_nff (
            numero_nff TEXT PRIMARY KEY,
            data_envio TEXT
        )
        """)
        conn.commit()

def logo(titulo):
    print("=" * 80)
    print(figlet_format(text=titulo, font="standard", justify="center"))
    print("=" * 80)

# ==============================
# FUNÇÕES BANCO
# ==============================

def buscar_nff(numero):
    with conectar_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT numero_nff, data_envio FROM controle_nff WHERE numero_nff = ?",
            (numero,)
        )

        resultado = cursor.fetchone()

        if resultado:
            print("\n🔎 NFF encontrada:")
            print(f"NFF: {resultado[0]}")
            print(f"Data registro: {resultado[1]}")
        else:
            print("\n❌ NFF não encontrada no controle.")

def listar_banco():
    with conectar_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT numero_nff, data_envio 
            FROM controle_nff 
            ORDER BY datetime(data_envio)
        """)

        registros = cursor.fetchall()

        if not registros:
            print("\n📭 Banco vazio.")
        else:
            print(f"\n📋 Total de registros: {len(registros)}\n")
            for r in registros:
                print(f"NFF: {r[0]} | Data: {r[1]}")

# ==============================
# PROCESSAMENTO EXCEL NFF
# ==============================

def processar_excel():

    try:
        df = pd.read_excel(
            ARQUIVO_EXCEL,
            sheet_name=ABA,
            header=HEADER_LINHA,
            engine="openpyxl"
        )
    except Exception as e:
        print("❌ Erro ao ler o Excel:", e)
        return

    df.columns = df.columns.astype(str).str.strip()

    if "*Número da NFF" not in df.columns:
        print("❌ Coluna '*Número da NFF' não encontrada.")
        return

    coluna_nff = "*Número da NFF"

    df = df[df[coluna_nff].notna()]
    nffs_planilha = df[coluna_nff].astype(str).str.strip()

    nffs_planilha = nffs_planilha[
        ~nffs_planilha.str.contains("Obrigatório|Alterado|▲", case=False, na=False)
    ]

    nffs_planilha = nffs_planilha[
        nffs_planilha.str.match(r"^[0-9.\-]+$")
    ]

    nffs_planilha = nffs_planilha.unique()

    print(f"\n📄 Total de NFFs reais na planilha: {len(nffs_planilha)}")

    with conectar_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT numero_nff FROM controle_nff")
        nffs_enviadas = set(r[0] for r in cursor.fetchall())

        print(f"🗂 Já registradas: {len(nffs_enviadas)}")

        nffs_novas = [nff for nff in nffs_planilha if nff not in nffs_enviadas]

        print(f"🆕 NFFs novas: {len(nffs_novas)}")

        if not nffs_novas:
            print("✔ Nenhuma NFF nova.")
        else:
            for nff in nffs_novas:
                cursor.execute("""
                    INSERT OR IGNORE INTO controle_nff (numero_nff, data_envio)
                    VALUES (?, ?)
                """, (nff, datetime.now().isoformat()))

                print(f"✔ Registrada: {nff}")

            conn.commit()
            print("🚀 Registro concluído.")

    print("🏁 Processo finalizado.")

# ==============================
# MONITORAMENTO FATURAS FW
# ==============================

def monitorar_faturas_fw():
    warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable.*")

    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    def initialize_connections():
        try:
            # Carrega variáveis de ambiente
            load_dotenv()
            tenant_id = os.getenv("TENANT_ID")
            client_id = os.getenv("CLIENT_ID")
            client_secret = os.getenv("CLIENT_SECRET")
            if not all([tenant_id, client_id, client_secret]):
                raise ValueError("Uma ou mais variáveis de ambiente não foram encontradas.")

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
            response = requests.post(token_url, data=token_data, timeout=10)
            response.raise_for_status()  # Levanta exceção para status != 200
            access_token = response.json()['access_token']   

            # Estabelece conexão com o banco de dados Snowflake
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

            return access_token, connection

        except Exception as e:
            log_error(f"Erro na inicialização das conexões: {e}")
            return None, None

    def get_conf():
        conf_path = CONF_DIR / "conf_cusd_invoices.yml"
        with open(conf_path, "r") as file:
            return yaml.safe_load(file)

    def get_query(query_name, model_parameters):
        query_path = QUERY_DIR / model_parameters["queries"][query_name]
        with open(query_path, "r") as file:
            return file.read()

    conf = get_conf()
    model_parameters = conf['model_parameters']
    access, conn = initialize_connections()

    query = get_query("job_monitoramento", model_parameters)
    df_faturas = pd.read_sql(query, conn)

    df_faturas.rename(columns=lambda x: x.upper(), inplace=True)
    df_faturas.columns = df_faturas.columns.str.strip()

    df_faturas['DATA_DA_APRESENTACAO_DA_FATURA'] = pd.to_datetime(
        df_faturas['DATA_DA_APRESENTACAO_DA_FATURA'],
        format='%d/%m/%Y',
        errors='coerce',
        dayfirst=True
    )

    projetos = [
        ['GUI02','PI-GUI-02','Equatorial PI',7,'FW'],
        ['UFV Santa Lucia I','SP-SLU-01','CPFL Paulista',11,'E-MAIL'],
        ['UFV Rincão','SP-RIN-01','CPFL Paulista',15,'E-MAIL'],
        ['UFV Boa Esperança do Sul II','SP-BES-02','CPFL Paulista',12,'E-MAIL'],
        ['UFV Dourado III','SP-DOR-03','CPFL Paulista',12,'E-MAIL'],
        ['UFV Descalvado I','SP-DES-01','CPFL Paulista',14,'E-MAIL'],
        ['UFV Altair I','SP-ALT-01','CPFL Paulista',11,'E-MAIL'],
        ['UFV Morro Agudo 101','SP-ATN-01','CPFL Paulista',19,'E-MAIL'],
        ['UFV Morro Agudo 102','SP-ATN-02','CPFL Paulista',18,'E-MAIL'],
        ['UFV Morro Agudo 103','SP-ATN-03','CPFL Paulista',18,'E-MAIL'],
        ['SERENA 01','PI-SRN-01','Equatorial PI',9,'N/A'],
        ['JUNCO','PI-JCO-01','Equatorial PI',7,'N/A'],
        ['UFV Araraquara IV','SP-ARQ-04','CPFL Paulista',13,'E-MAIL'],
        ['UFV Araraquara III','SP-ARQ-03','CPFL Paulista',19,'E-MAIL'],
        ['UFV Piacatu I','SP-PIA-01','CPFL Paulista',13,'E-MAIL'],
        ['UFV Guapó 1','GO-HLX-01.1','Equatorial GO',20,'E-MAIL'],
        ['UFV Guapó 2','GO-HLX-01.2','Equatorial GO',20,'E-MAIL'],
        ['UFV Guapó 3','GO-HLX-01.3','Equatorial GO',20,'E-MAIL'],
        ['UFV Guapó 4','GO-HLX-01.4','Equatorial GO',20,'E-MAIL'],
        ['UFV Guapó 5','GO-HLX-01.5','Equatorial GO',20,'E-MAIL'],
        ['UFV Miguelópolis','SP-MIG-01','CPFL Paulista',14,'E-MAIL'],
        ['UFV Porangatu I','GO-PRG-01','Equatorial GO',11,'E-MAIL'],
        ['UFV Getulina II','SP-GET-02','CPFL Paulista',18,'E-MAIL'],
        ['SERRA DO RAMALHO','BA-SRR-01','COELBA',20,'E-MAIL'],
        ['UFV SMP 101','PA-ATN-01','Equatorial PA',8,'FW'],
        ['UFV SMP 102','PA-ATN-02','Equatorial PA',8,'FW'],
        ['UFV SMP 103','PA-ATN-03','Equatorial PA',8,'FW'],
        ['UFV SMP 104','PA-ATN-04','Equatorial PA',8,'FW'],
        ['UFV SMP 105','PA-ATN-05','Equatorial PA',8,'FW'],
        ['UFV SMP 106','PA-ATN-06','Equatorial PA',7,'FW'],
        ['UFV SMP 107','PA-ATN-07','Equatorial PA',8,'FW'],
        ['UFV Boa Esperança do Sul V','SP-BES-05','CPFL Paulista',22,'E-MAIL'],
        ['UFV Avanhandava I','SP-AVA-01','CPFL Paulista',19,'E-MAIL'],
        ['UFV GOY 400','RJ-ATN-01','Enel RJ',14,'FW'],
        ['UFV Pompéia II','SP-POM-02','CPFL Paulista',18,'E-MAIL'],
        ['UFV TIM 201','MA-ATN-01','Equatorial MA',8,'FW'],
        ['UFV TIM 202','MA-ATN-02','Equatorial MA',7,'FW'],
        ['UFV TIM 203','MA-ATN-03','Equatorial MA',8,'FW'],
        ['UFV TIM 204','MA-ATN-04','Equatorial MA',9,'FW'],
        ['UFV TIM 205','MA-ATN-05','Equatorial MA',8,'FW'],
        ['UFV CXPO DO OURO','MT-TOV-01','EMT',8,'FW'],
        ['UFV Nova Crixás II','GO-NVC-02','Equatorial GO',10,'E-MAIL'],
        ['UFV Nova Crixás I','GO-NVC-01','Equatorial GO',10,'E-MAIL'],
        ['UFV Minaçu I','GO-MNU-01','Equatorial GO',8,'E-MAIL'],
        ['UFV Cezarina 1','GO-HLX-02.1','Equatorial GO',10,'E-MAIL'],
        ['UFV Cezarina 2','GO-HLX-02.2','Equatorial GO',10,'E-MAIL'],
        ['UFV Cezarina 3','GO-HLX-02.3','Equatorial GO',10,'E-MAIL'],
        ['UFV Cezarina 4','GO-HLX-02.4','Equatorial GO',10,'E-MAIL'],
        ['UFV Cezarina 5','GO-HLX-02.5','Equatorial GO',10,'E-MAIL'],
        ['UFV CPP 101','PA-ATN-08','Equatorial PA',3,'FW'],
        ['UFV CPP 102','PA-ATN-09','Equatorial PA',4,'FW'],
        ['UFV CPP 103','PA-ATN-10','Equatorial PA',4,'FW'],
        ['UFV CPP 104','PA-ATN-11','Equatorial PA',6,'FW'],
        ['UFV CPP 105','PA-ATN-12','Equatorial PA',4,'FW'],
        ['UFV CPP 106','PA-ATN-13','Equatorial PA',4,'FW'],
        ['UFV CPP 107','PA-ATN-14','Equatorial PA',4,'FW'],
        ['UFV GOY 701','RJ-ATN-02','Enel RJ',13,'FW'],
        ['UFV SOLONOPOLE','CE-TOV-01','ENEL CE',13,'FW'],
        ['UFV Venturosa I','PE-VEN-01','CELPE',20,'E-MAIL'],
        ['UFV Apolo Sanharo II','PE-APS-02','CELPE',21,'E-MAIL'],
        ['UFV Aliança I','PE-ALI-01','CELPE',25,'E-MAIL'],
        ['UFV Rio do Antônio I','BA-RAN-01','COELBA',20,'E-MAIL'],
        ['UFV Rio do Antônio II','BA-RAN-02','COELBA',18,'E-MAIL'],
        ['UFV Novo Planalto II','GO-NVP-02','Equatorial GO',25,'E-MAIL'],
        ['UFV Pesqueira I','PE-PES-01','CELPE',21,'E-MAIL'],
        ['UFV Iramaia I','BA-IRM-01','COELBA',23,'E-MAIL'],
        ['UFV Barreiras','BA-BAR-01','COELBA',18,'E-MAIL'],
        ['UFV Beberibe','CE-HLX-02','Enel CE',10,'FW'],
        ['UFV Brejo Madre de Deus I','PE-BMD-01','CELPE',22,'E-MAIL'],
        ['UFV ITABIRA','MG-SUN-01','CEMIG',5,'E-MAIL'],
        ['SERENA 04','PI-SRN-04','Equatorial PI',2,'N/A'],
        ['UFV JCD 101','PA-ATN-15','Equatorial PA',2,'FW'],
        ['UFV JCD 102','PA-ATN-16','Equatorial PA',2,'FW'],
        ['UFV JCD 103','PA-ATN-17','Equatorial PA',2,'FW'],
        ['UFV JCD 104','PA-ATN-18','Equatorial PA',2,'FW'],
        ['UFV JCD 105','PA-ATN-19','Equatorial PA',2,'FW'],
        ['UFV JCD 106','PA-ATN-20','Equatorial PA',2,'FW'],
        ['UFV JCD 107','PA-ATN-21','Equatorial PA',2,'FW'],
        ['UFV JCD 108','PA-ATN-22','Equatorial PA',2,'FW'],
        ['UFV JCD 109','PA-ATN-23','Equatorial PA',2,'FW'],
        ['UFV Novo Planalto I','GO-NVP-01','Equatorial GO',5,'E-MAIL'],
        ['UFV Gravatá','PE-GRA-01','CELPE',20,'E-MAIL']
    ]


    df_projetos = pd.DataFrame(
        projetos,
        columns=['Projeto','ACRONIMO','Distribuidora','Dia','Forma Recebimento']
    )

    df_projetos['ACRONIMO'] = df_projetos['ACRONIMO'].str.strip()

    hoje = datetime.today()
    mes_atual = hoje.month
    ano_atual = hoje.year

    df_projetos['Data Esperada'] = df_projetos['Dia'].apply(
        lambda d: datetime(ano_atual, mes_atual, d)
    )

    df_faturas_recent = (
        df_faturas
        .sort_values('DATA_DA_APRESENTACAO_DA_FATURA')
        .groupby('ACRONIMO')
        .tail(1)
    )

    df_faturas_recent['ACRONIMO'] = df_faturas_recent['ACRONIMO'].str.strip()

    df = df_projetos.merge(
        df_faturas_recent[['ACRONIMO','DATA_DA_APRESENTACAO_DA_FATURA']],
        on='ACRONIMO',
        how='left'
    )

    df['Data Chegada'] = df['DATA_DA_APRESENTACAO_DA_FATURA']
    hoje_date = datetime.today().date()

    def calcula_alerta(row):
        if pd.notna(row['Data Chegada']):
            return 'OK' if row['Data Chegada'].date() <= row['Data Esperada'].date() else 'Fatura atrasada!'
        else:
            return 'Dentro do prazo' if row['Data Esperada'].date() >= hoje_date else 'Fatura atrasada!'

    df['Alerta'] = df.apply(calcula_alerta, axis=1)

    alertas = df[
        (df['Alerta'] == 'Fatura atrasada!') &
        (df['Forma Recebimento'] == 'FW')
    ]

    print("\n⚠️  Faturas FW atrasadas:\n")
    print(alertas[['Projeto','ACRONIMO','Distribuidora','Data Esperada','Data Chegada','Alerta']])

# ==============================
# MENU PRINCIPAL
# ==============================

def menu():

    while True:

        limpar_tela()
        logo("Monitor de  NFF")
        print("1 - Processar Excel NFF")
        print("2 - Buscar NFF")
        print("3 - Listar Banco de NFFs")
        print("4 - Monitorar Faturas Atrasadas FW")
        print("5 - Sair")

        modo = input("Digite o número do modo desejado: ").strip()

        limpar_tela()

        if modo == "1":
            processar_excel()

        elif modo == "2":
            numero = input("Digite o número da NFF para buscar: ").strip()
            limpar_tela()
            buscar_nff(numero)

        elif modo == "3":
            listar_banco()

        elif modo == "4":
            monitorar_faturas_fw()

        elif modo == "5":
            print("Encerrando sistema...")
            break

        else:
            print("❌ Opção inválida.")

        input("\nPressione ENTER para voltar ao menu...")

# ==============================
# EXECUÇÃO
# ==============================

if __name__ == "__main__":
    inicializar_banco()
    menu()