import pandas as pd
import os
import numpy as np
from utils.src_usinas import initialize_snowflake_connection
from utils.utils_usinas import get_conf_by_project, get_query, standardize_string

# A configuração deste cálculo vive em conf/conf_exception_billing.yml, que NÃO veio
# para este repo (o get_conf() antigo lia um conf que ficou para trás). Sem ele, o
# __init__ para com FileNotFoundError. O arquivo precisa ter:
#   - model_parameters.queries: faturamentos_excecao, tarifas_distribuidoras, crm
#     (candidatos em sql/: stg_fattureweb_excecao.sql, stg_aneel_tarifas_distribuidoras.sql,
#     stg_crm.sql — confirmar antes de usar)
#   - consumption_bands, tariff_discounts, distributors, other_financial_charges
#     (regra de negócio: pegar os valores com quem mantinha o cálculo, não deduzir)


class ExceptionBilling:
    def __init__(self):
        self.conf = get_conf_by_project('exception_billing')
        self.connection = initialize_snowflake_connection()

    def read_query(self, query):
        try:
            model_parameters = self.conf["model_parameters"]
            query_text = get_query(query, model_parameters)
            df = pd.read_sql(query_text, con=self.connection)
            return df
        except Exception as e:
            print(f"Error reading query: {e}")
            return None


    def get_billing_table(self):
        
        billing = self.read_query("faturamentos_excecao")

        float_columns = billing.select_dtypes(include=["float"]).columns
        billing[float_columns] = (billing
                                    .select_dtypes(include=["float"])
                                    .fillna(0)
        )

        quantidades = [column for column in billing.columns if column.startswith("QUANTIDADE_CONSUMO_TE")]
        billing["quantidade_calculada"] = np.where(
                                                billing["QUANTIDADE_CONSUMO_KWH"]==0,
                                                billing[quantidades].sum(axis=1),
                                                billing["QUANTIDADE_CONSUMO_KWH"]
                                                )

        billing=convert_to_datetime(billing, ["DATA_DE_EMISSAO_DA_FATURA"])
        bands = self.get_bands()
        
        billing_allocated = allocate_to_bands(billing, "CONSUMO_BASE", bands, prefix="baseline")
        billing_allocated = allocate_to_bands(billing_allocated, "quantidade_calculada", bands, prefix="real")

        return billing_allocated


    def get_bands(self):

        bands = self.conf["consumption_bands"]
        bands_values = [bands[0]]
        for i in range(len(bands)-1):
            bands_values.append(bands[i+1] - bands[i])
        bands_values.append(0)

        return bands_values


    def get_tariffs_table(self):

        tariffs = self.read_query("tarifas_distribuidoras")

        tariffs["DISTRIBUIDORA"] = (tariffs["SigAgente"]
                                    .apply(lambda x: 
                                            replace_rows(x,self.conf["distributors"]))
        )

        date_columns = ["DatInicioVigencia", "DatFimVigencia"]
        tariffs = convert_to_datetime(tariffs, date_columns)

        tariffs["tarifa_sem_impostos"] = (tariffs["VlrTE"] + tariffs["VlrTUSD"]) / 1000
        return tariffs


    def get_crm_table(self):

        crm_discounts = self.read_query("crm")

        distributors = self.conf["distributors"]

        crm_discounts["DISTRIBUIDORA"] = crm_discounts["DISTRIBUIDORA"].apply(lambda x: replace_rows(x,distributors))

        return crm_discounts

        
    def get_current_tariffs(self, billing, tariffs):

        # Sorting values in dataframe for the merge_asof function
        billing = billing.sort_values("DISTRIBUIDORA", ascending = True)
        billing = billing.sort_values("DATA_DE_EMISSAO_DA_FATURA", ascending = True)
        tariffs = tariffs.sort_values("DISTRIBUIDORA", ascending = True)
        tariffs = tariffs.sort_values("DatInicioVigencia", ascending = True)

        # Remove any rows with NaT in the "DATA_DE_EMISSAO_DA_FATURA" column
        billing = billing[billing["DATA_DE_EMISSAO_DA_FATURA"].notna()]

        # Merge_asof
        billing_tariffs_join = pd.merge_asof(billing,
                                                tariffs,
                                                left_on="DATA_DE_EMISSAO_DA_FATURA",
                                                right_on="DatInicioVigencia",
                                                by="DISTRIBUIDORA",
                                                direction="backward")

        # Filtro para considerar apenas tarifas válidas
        billing_tariffs_join = (billing_tariffs_join
                                .loc[billing_tariffs_join["DATA_DE_EMISSAO_DA_FATURA"]
                                        <= billing_tariffs_join["DatFimVigencia"]])

        return billing_tariffs_join


    def calculate_taxes(self, df):

        df["aliquota_pis_cofins"] = (df["ALIQUOTA_COFINS"]
                                    + df["ALIQUOTA_PIS_PASEP"])
        
        df["total_com_impostos"] = (df["total_sem_impostos"]
                                    / (1-df["ALIQUOTA_ICMS"])
                                    / (1-df["aliquota_pis_cofins"]))
        
        df["energia_dx"] = (df["faixa_retirada"]
                            / (1-df["ALIQUOTA_ICMS"])
                            / (1-df["aliquota_pis_cofins"]))
        return df


    def calculate_discounts(self, df):

        discounts = [1-discount for discount in self.conf["tariff_discounts"]]
        columns_real = [column for column in df.columns if column.startswith("consumo_real")]
        columns_baseline = [column for column in df.columns if column.startswith("consumo_baseline")]


        ####### ALTERAR REGRA PARA CLIENTES MONOFASICO, BIFASICO E TRIFASICO
        df["faixa_retirada"] = np.where(
                                df['quantidade_calculada']<=df['CONSUMO_BASE'],
                                0,
                                (np.dot(df[columns_baseline], discounts)
                                * df["tarifa_sem_impostos"]))

        df["total_sem_impostos"] = (np.dot(df[columns_real], discounts) 
                                    * df["tarifa_sem_impostos"]
                                    - df["faixa_retirada"])
        return df


    def other_financial_charges(self, df):

        other_financial_charges = self.conf["other_financial_charges"]
        df["total_outros"] = df[other_financial_charges].sum(axis=1)

        return df
    
    
    def filter_active_customers(self, df_main, df_crm):

        # Assuming df_main and df_crm are already loaded as DataFrames

        # Step 1: Ensure dates are datetime
        df_main['MES_DE_REFERENCIA_DA_FATURA'] = pd.to_datetime(df_main['MES_DE_REFERENCIA_DA_FATURA'])
        df_crm['DATA_INICIO_CONTRATO'] = pd.to_datetime(df_crm['DATA_INICIO_CONTRATO'])
        df_crm['DATA_DENUNCIA_CONTRATO'] = pd.to_datetime(df_crm['DATA_DENUNCIA_CONTRATO'])

        # Step 2: Join on customer_id (many-to-many if multiple contracts)
        df_merged = df_main.merge(df_crm, on=['NUMERO_DA_INSTALACAO', 'DISTRIBUIDORA'], how='left')

        # Step 3: Define active contract condition
        active_condition = (
            (df_merged['MES_DE_REFERENCIA_DA_FATURA'] >= df_merged['DATA_INICIO_CONTRATO']) &
            (
                df_merged['DATA_DENUNCIA_CONTRATO'].isna() |
                (df_merged['MES_DE_REFERENCIA_DA_FATURA'] <= df_merged['DATA_DENUNCIA_CONTRATO'])
            )
        )

        # Step 4: Filter only active contracts
        df_active = df_merged[active_condition].copy()

        # Optional: If multiple matching contracts and you want to deduplicate
        df_active = df_active.drop_duplicates(subset=['NUMERO_DA_INSTALACAO', 'DISTRIBUIDORA', 'MES_DE_REFERENCIA_DA_FATURA'])


        return df_active


    def get(self):

        billing = self.get_billing_table()
        tariffs = self.get_tariffs_table()
        crm_discounts = self.get_crm_table()

        active_customers = self.filter_active_customers(billing, crm_discounts)
        billing_tariffs_join = self.get_current_tariffs(active_customers, tariffs)


        billing_tariffs_join = self.calculate_discounts(billing_tariffs_join)
        billing_tariffs_join = self.calculate_taxes(billing_tariffs_join)
        billing_tariffs_join = self.other_financial_charges(billing_tariffs_join)

        billing_tariffs_join["total_descontado"] = (billing_tariffs_join["total_com_impostos"] 
                                                    * (100 - billing_tariffs_join["DESCONTO_PRECIFICADO"])
                                                    / 100)
        

        return billing_tariffs_join
    
    
    def generate_output(self, df):
        
        df_copy = df.copy()
        output_schema = ['UNIDADE_CONSUMIDORA',
                         'MES_REFERENCIA',
                         'DISTRIBUIDORA',
                         'TARIFA_DISTRIBUIDORA',
                         'PRECO_SERENA',
                         'ENERGIA_FATURADA',
                         'TOTAL_FATURAMENTO',
                         'ECONOMIA',
                         'OUTROS_INTERNO',
                         'OUTROS_EXTERNO']
        
        rename_map = {
                            'NUMERO_DA_INSTALACAO':'UNIDADE_CONSUMIDORA',
                            'MES_DE_REFERENCIA_DA_FATURA':'MES_REFERENCIA',
                            'quantidade_calculada':'ENERGIA_FATURADA',
                            'total_descontado':'TOTAL_FATURAMENTO'
                        }

        df_copy['TARIFA_DISTRIBUIDORA'] = (df_copy['tarifa_sem_impostos'] 
                                          / (1-df_copy['aliquota_pis_cofins'])
                                          / (1-df_copy['ALIQUOTA_ICMS']))

        df_copy['PRECO_SERENA'] = (df_copy['TARIFA_DISTRIBUIDORA'] 
                              * (100-df_copy['DESCONTO_PRECIFICADO']) 
                              / 100)
        

        
        df_copy['ECONOMIA'] = df_copy['total_com_impostos'] - df_copy['total_descontado']

        df_copy['OUTROS_INTERNO'] = df_copy['total_outros']
        df_copy['OUTROS_EXTERNO'] = df_copy['total_outros']

        
        df_copy = df_copy.rename(columns=rename_map)

        return df_copy[output_schema]


# Funcoes auxiliares
def replace_rows(x, distributors):
    x = standardize_string(x, separator="")
    return np.where(
            distributors.get(x) == None,
            x, 
            distributors.get(x)
        )


def allocate_to_bands(df, value_col, bands, prefix):
    def allocate(value):
        result = []
        for i, band in enumerate(bands):
            if i == len(bands) - 1:
                # Last band: take whatever is left
                result.append(value)
            elif value > band:
                result.append(band)
                value -= band
            else:
                result.append(value)
                value = 0
        return result

    df_copy = df.copy()
    band_allocations = df[value_col].apply(allocate)
    band_retainer = 0
    bands_list = []
    for i in range(len(bands)):
        band_retainer += bands[i]
        if bands[i] == 0:
            df_copy[f"consumo_{prefix}_pos_{band_retainer}"] = band_allocations.apply(lambda x: x[i])
        else:
            df_copy[f"consumo_{prefix}_ate_{band_retainer}"] = band_allocations.apply(lambda x: x[i])
            bands_list.append(band_retainer)
    
    return df_copy


def convert_to_datetime(df, columns):
        """
        Converts specified columns in a DataFrame to datetime format.
        """
        for column in columns:
            df[column] = pd.to_datetime(df[column])
        return df
    