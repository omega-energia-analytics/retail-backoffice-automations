import pdfplumber
import pandas as pd
import unicodedata
import re
import os
from datetime import datetime
# ----------------------------------------------------------
# 📌 1. PASTA DE ENTRADA (onde você vai salvar os PDFs brutos)
# ----------------------------------------------------------
# pasta_entrada = r
# "C:\Users\vinicius.azevedo\Serena\Comercializadora - Acompanhamento - Operação GD\2. Faturamento Usinas - Parceiros\2. DEMONSTRATIVOS COELBA"
# Raiz "Acompanhamento - Operação GD": mesma env var BACKOFFICE_GD_DIR do monit_hist_usina.py
base_gd = os.getenv("BACKOFFICE_GD_DIR") or os.path.join(
    os.path.expanduser("~"), "Serena", "Comercializadora - OMG", "03 - BackOffice",
    "13 - Geração Distribuída", "Acompanhamento - Operação GD",
)
pasta_entrada = os.path.join(base_gd, "2. Faturamento Usinas - Parceiros", "2. DEMONSTRATIVOS COELBA")

# Lista todos os PDFs
arquivos_pdf = [f for f in os.listdir(pasta_entrada) if f.lower().endswith(".pdf")]
if not arquivos_pdf:
    print("⚠️ Nenhum PDF encontrado na pasta de entrada.")
    exit()
# ----------------------------------------------------------
# 📌 Funções auxiliares
# ----------------------------------------------------------
def normalizar(texto):
    if texto is None:
        return ""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ASCII", "ignore").decode("utf-8")
    texto = re.sub(r"\s+", " ", texto)
    return texto
def limpar_valor(valor):
    if pd.isna(valor):
        return ""
    valor = str(valor).strip()
    valor = re.sub(r"[^\d,.-]", "", valor)
    return valor
# Cabeçalhos dos modelos
cabecalho_completo = [
    "mes", "instalacao", "rateio", "saldo_anterior_kwh",
    "energia_consumida_kwh", "energia_recebida_kwh",
    "energia_compensada_kwh", "saldo_acumulado_kwh"
]
cabecalho_resumido = [
    "codigo_cliente", "rateio", "saldo_acumulado_kwh"
]
# ----------------------------------------------------------
# 📌 2. PROCESSAR CADA PDF ENCONTRADO
# ----------------------------------------------------------
for arquivo in arquivos_pdf:
    caminho_pdf = os.path.join(pasta_entrada, arquivo)
    tabelas = []
    print("\n" + "="*90)
    print(f"📄 PROCESSANDO: {arquivo}")
    print("="*90)
    with pdfplumber.open(caminho_pdf) as doc:
        print(f"Total de páginas: {len(doc.pages)}")
        for i, page in enumerate(doc.pages):
            tables = page.extract_tables()
            print(f"🔍 {len(tables)} tabela(s) encontrada(s) na página {i+1}")
            for idx, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue
                # ------------------------------------------------------
                # Modelo COMPLETO
                # ------------------------------------------------------
                if any("scee - beneficiarias" in normalizar(cell) for row in table for cell in row if cell):
                    header_index = None
                    for j, row in enumerate(table):
                        if row and normalizar(row[0]) == "mes":
                            header_index = j
                            break
                    if header_index is not None and header_index + 1 < len(table):
                        print(f"✅ MODELO COMPLETO encontrado na página {i+1}, tabela {idx+1}")
                        data_rows = table[header_index + 1:]
                        df = pd.DataFrame(data_rows, columns=cabecalho_completo)
                        df.replace("-", "", inplace=True)
                        for col in df.columns:
                            if col != "mes":
                                df[col] = df[col].apply(limpar_valor)
                        tabelas.append(df)
                    else:
                        print(f"⚠️ Cabeçalho 'Mês' não encontrado na página {i+1}, tabela {idx+1}")
                    continue
                # ------------------------------------------------------
                # Modelo RESUMIDO
                # ------------------------------------------------------
                primeira_celula = normalizar(table[0][0])
                if "resumo do saldo de credito por unidade" in primeira_celula:
                    print(f"✅ MODELO RESUMIDO encontrado na página {i+1}, tabela {idx+1}")
                    df = pd.DataFrame(table[1:], columns=cabecalho_resumido)
                    df.replace("-", "", inplace=True)
                    for col in df.columns:
                        df[col] = df[col].apply(limpar_valor)
                    tabelas.append(df)
                    continue
                # ------------------------------------------------------
                # Tabela não reconhecida
                # ------------------------------------------------------
                print(f"⚠️ Tabela não reconhecida na página {i+1}, tabela {idx+1}")
    # ----------------------------------------------------------
    # 📌 3. COMBINAR TABELAS (se existirem)
    # ----------------------------------------------------------
    if tabelas:
        df_final = pd.concat(tabelas, ignore_index=True)
        df_final = df_final.where(pd.notnull(df_final), "")
    else:
        print("⚠️ Nenhuma tabela válida identificada neste PDF.")
        continue
    # ----------------------------------------------------------
    # 📌 4. GERAR NOME DO EXCEL
    # ----------------------------------------------------------
    nome_base_pdf = os.path.splitext(arquivo)[0]
    nome_base_pdf = re.sub(r'[\\/*?:"<>|]', "", nome_base_pdf)
    data_execucao = datetime.now().strftime("%Y%m%d")
    nome_excel_base = f"{nome_base_pdf}_{data_execucao}"
    nome_excel = f"{nome_excel_base}.xlsx"
    caminho_saida = os.path.join(pasta_entrada, nome_excel)
    contador = 1
    while os.path.exists(caminho_saida):
        nome_excel = f"{nome_excel_base}_{contador}.xlsx"
        caminho_saida = os.path.join(pasta_entrada, nome_excel)
        contador += 1
    # ----------------------------------------------------------
    # 📌 5. EXPORTAR EXCEL
    # ----------------------------------------------------------
    df_final.to_excel(caminho_saida, index=False)
    print(f"📁 Excel gerado: {caminho_saida}")
print("\n✔️ PROCESSAMENTO FINALIZADO PARA TODOS OS PDFs!")