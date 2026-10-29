import re
import pandas as pd
import yaml
from utils.src_usinas import initialize_snowflake_connection
from utils.utils_usinas import (
    get_conf_by_project,
    get_query,
    fill_in_column, 
    clear_column_content, 
    change_column_formatting,
    standardize_string,
)
import xlwings as xw
import datetime as dt
from pathlib import Path

# Colunas que identificam a usina na fonte (stg_cusd_monitoring.sql). Não vão para a
# planilha — existem só para o bloqueio, e são removidas depois dele.
COLUNAS_DE_BLOQUEIO = ["ACRONIMO", "NUMERO_DA_INSTALACAO"]


def normaliza_chave_bloqueio(valor):
    """Normaliza acrônimo/UC antes de comparar com a lista de bloqueio.

    A mesma UC aparece como '2000003809' e como '2000003809.0' (o número passa por float
    em parte do caminho), e o acrônimo varia em caixa e espaço nas pontas. Comparar cru
    faria o bloqueio não casar exatamente no caso em que ele precisa funcionar.
    """
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    texto = re.sub(r"\.0$", "", str(valor).strip().upper())
    return texto or None


class CreateQuickInvoices():
    def __init__(self):
        self.conf = get_conf_by_project('cusd_invoices')
        model_parameters = self.conf["model_parameters"]
        wb = xw.Book(str(Path.home() / "Faturas Oracle" / model_parameters["output_files"]["workbook_name"]))
        self.sheet = wb.sheets[model_parameters["output_files"]["sheet_name"]]
        self.connection = initialize_snowflake_connection()


    def rename_rows(self, row, rename_map, conf_rename):
        return conf_rename[rename_map].get(row)

    
    def provision_column(self, df):
        parameters = list(self.conf["model_parameters"]["output_files"]["parameters"].values())
        return '-'.join([df["CLIENTE_APELIDO"][:4]] * 2 + parameters)

    
    def select_emission_date(self, df, days = 7, to_date = dt.date.today()):

        emission_dates = pd.to_datetime(df["DATA_DE_EMISSAO_DA_FATURA"], errors="coerce")

        start_date = pd.Timestamp(to_date - dt.timedelta(days=days))
        end_date = pd.Timestamp(to_date)

        mask = (emission_dates >= start_date) & (emission_dates <= end_date)
        return df.loc[mask]

    
    def remove_usinas_bloqueadas(self, df):
        """Descarta as usinas que não podem gerar NFF (`nff_bloqueados` no conf).

        Roda como PRIMEIRO passo do format_to_quick_invoices, antes de qualquer
        transformação: a linha bloqueada nunca chega perto da planilha.

        A planilha CreateQuickInvoices não tem coluna de acrônimo, então o bloqueio não
        pode morar nela — nem seria confiável, porque o workbook é editado à mão. Aqui a
        regra fica versionada e casa por acrônimo OU UC (ver comentário no conf).

        Falha FECHADA de propósito: sem lista, ou sem as colunas de identificação, o job
        aborta em vez de seguir gerando NFF. É o que impede o bloqueio de ser desligado em
        silêncio por uma edição futura no stg_cusd_monitoring.sql que tire o ACRONIMO do
        SELECT — sem isso o filtro simplesmente não acharia nada para barrar e passaria.
        """
        bloqueio = self.conf["model_parameters"].get("nff_bloqueados") or {}
        acronimos = {normaliza_chave_bloqueio(v) for v in bloqueio.get("acronimos") or []}
        ucs = {normaliza_chave_bloqueio(v) for v in bloqueio.get("unidades_consumidoras") or []}
        acronimos.discard(None)
        ucs.discard(None)

        if not acronimos and not ucs:
            raise ValueError(
                "nff_bloqueados vazio ou ausente no conf_cusd_invoices.yml. Existem usinas "
                "que não podem gerar NFF; sem a lista não há como garantir isso e o job para."
            )

        faltando = [c for c in COLUNAS_DE_BLOQUEIO if c not in df.columns]
        if faltando:
            raise ValueError(
                f"Colunas de identificação da usina ausentes no resultado da query: {faltando}. "
                "O bloqueio de NFF depende delas — devolva-as no stg_cusd_monitoring.sql "
                "antes de rodar."
            )

        bloqueada = (
            df["ACRONIMO"].map(normaliza_chave_bloqueio).isin(acronimos)
            | df["NUMERO_DA_INSTALACAO"].map(normaliza_chave_bloqueio).isin(ucs)
        )

        if bloqueada.any():
            removidas = df.loc[bloqueada, COLUNAS_DE_BLOQUEIO + ["NOTA_FISCAL"]]
            print(
                f"[BLOQUEIO NFF] {int(bloqueada.sum())} linha(s) descartada(s) por estarem "
                f"em nff_bloqueados:\n{removidas.to_string(index=False)}"
            )
        else:
            print("[BLOQUEIO NFF] nenhuma linha bloqueada no período.")

        # As colunas saem aqui: o dropna() logo adiante descarta a linha por QUALQUER nulo,
        # então mantê-las mudaria quais faturas sobrevivem hoje.
        return df.loc[~bloqueada].drop(columns=COLUNAS_DE_BLOQUEIO)


    def read_query(self, query):
        try:
            model_parameters = self.conf["model_parameters"]
            query_text = get_query(query, model_parameters)
            df = pd.read_sql(query_text, con=self.connection)
            return df
        except Exception as e:
            print(f"Error reading query: {e}")
            return None      


    def format_to_quick_invoices(self, df, **kwargs):

        conf_rename = self.conf["model_parameters"]["rename_maps"]

        # Usinas bloqueadas saem primeiro, antes de qualquer transformação
        df = self.remove_usinas_bloqueadas(df)

        # Drop rows that are not completely filled
        df = df.dropna()
        print(df)

        # Add new columns that have fixed value
        df["MOEDA_DA_NFF"] = "BRL"
        df["GRUPO_DE_PAGAMENTOS"] = "Método Direto"
        df["DATA_DE_CRIACAO"] = dt.date.today()
        df["NUMERO_DO_FORNECEDOR"] = df["DISTRIBUIDORA_SIGLA"]
        df['CONDICOES_PAGAMENTO'] = 'Imediato'
        df['DATA_DE_VENCIMENTO'] = df['DATA_DE_VENCIMENTO_DA_FATURA']

        # Rename rows in columns
        columns_to_rename_rows = {"CLIENTE_APELIDO": "business_unit", 
                            "DISTRIBUIDORA_SIGLA": "supplier_name",
                            "NUMERO_DO_FORNECEDOR": "supplier_number"}
        
        for column, rename_map in columns_to_rename_rows.items():
            df[column] = (
                df[column]
                .apply(lambda row: self.rename_rows(row, rename_map, conf_rename))
            )

        df["DISTRIBUIDORA_CNPJ"] = df["DISTRIBUIDORA_CNPJ"].apply(lambda row: standardize_string(text=row, separator = ""))
        df["COMBINACAO_DE_DISTRIBUICAO"] = df.apply(lambda row: self.provision_column(row), axis=1)

        df = self.select_emission_date(df, **kwargs)

        return df


    def send_to_quick_invoices(self, df):

        columns_to_fill = self.conf["model_parameters"]['output_files']['schema']

        cleared_content_log = {}
        inserted_data_log = {}
        format_change_log = {}

        for i, j in columns_to_fill.items():
            # print("Limpando:", j["oracle_sheet_column"])
            cleared_content_log[i] = clear_column_content(j["oracle_sheet_column"], self.sheet)
            inserted_data_log[i] = fill_in_column(j["oracle_sheet_column"], df[j["input_column"]], self.sheet)
            if i == "data_da_nff":
                # Convert date to the format required by Quick Invoices
                format_change_log[i] = change_column_formatting(j["oracle_sheet_column"], self.sheet, "mm/dd/aaaa")
        return cleared_content_log, inserted_data_log, format_change_log


    def get_invoices(self, **kwargs):
        df = self.read_query("cusd_monitoring")

        # Suplemento: notas de distribuidoras que não sobem para o MONITORAMENTO_CUSD_AWS
        # (COELBA, CELPE, CEMIG) e por isso nunca apareciam aqui, mesmo já visíveis no
        # monitor de NFF. Ver header do stg_cusd_invoices_suplemento.sql.
        df_suplemento = self.read_query("cusd_invoices_suplemento")
        if df_suplemento is not None and not df_suplemento.empty:
            df = pd.concat([df, df_suplemento], ignore_index=True)

        df_copy = self.format_to_quick_invoices(df, **kwargs)
        return df_copy

    
    def run(self, **kwargs):
        df = self.get_invoices(**kwargs)
        cleared_content_log, inserted_data_log, format_change_log = self.send_to_quick_invoices(df)
        return cleared_content_log, inserted_data_log, format_change_log, df
    