import fitz  # PyMuPDF
import pandas as pd
import re
from pathlib import Path
from datetime import datetime


# Regex de chars ilegais no Excel (controle ASCII + zero-width + BOM)
ILLEGAL_CHARS_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\u200B-\u200D\uFEFF]')


def _clean(v):
    """Remove caracteres ilegais para o Excel e normaliza espaços."""
    if isinstance(v, str):
        return ILLEGAL_CHARS_RE.sub('', v).replace('\xa0', ' ').strip()
    return v


# Função auxiliar para capturar valores via regex
def extract(pattern, text, group=1, all_matches=False):
    matches = re.findall(pattern, text, re.IGNORECASE)
    if all_matches:
        return [m.strip() for m in matches] if matches else []
    return matches[group - 1].strip() if matches else ""


# Ordem das colunas do Excel de saída
colunas = [
    "REFERÊNCIA", "PÁGINA",
    "CLIENTE", "ENDERECO", "MUNICIPIO", "BAIRRO", "REFERENCIA", "VENCIMENTO",
    "DOCUMENTO", "COMPLEMENTO", "VALOR", "EMPRESA", "LOCAL", "CONJ_CONTRATO", "UNIDADE_LEITURA",
    "REFERENCIA_SEC", "NOME", "ENDERECO_SEC", "BAIRRO_SEC", "MUNICIPIO_SEC",
    "COMPLEMENTO_SEC", "FATURA", "INSTALACAO", "UNIDADE_CONSUMIDORA", "CLASSE_PRINCIPAL", "CLASSE_CONSUMO", "TENSAO", "FASE",
    "DATA_FAT", "DIAS_FAT", "DATA_LEIT_ANT", "DATA_LEIT_ATUAL", "REAVISO", "CORTE",
    "HASH_CODE", "NOTA_FISCAL", "APRESENTACAO", "VENCIMENTO_SEC", "RECOLHIMENTO", "VALOR_SEC",
    "VALOR_NUM", "ICMS_BaseCalculo", "ICMS_Aliquota", "ICMS_Valor", "COFINS_BaseCalculo",
    "COFINS_Aliquota", "COFINS_Valor", "PIS_BaseCalculo", "PIS_Aliquota", "PIS_Valor",
    "Medidor", "Cte", "Leit_Anterior", "Leit_Atual", "Medido", "Faturado",
    "Cip_Ilum_Pub_Pref_Munic", "Consumo_quantidade", "Consumo_preco", "Consumo_valor",
    "Consumo_Compensado_quantidade", "Consumo_Compensado_preco", "Consumo_Compensado_valor",
    "Dev_Geracao_quantidade", "Dev_Geracao_preco", "Dev_Geracao_valor",
    "Adicional_Bandeira_valor", "Multa_valor", "Correcao_Monetaria_valor", "Juros_valor"
]


def parse_bloco(bloco, referencia, pagina):
    """Extrai os ~60 campos de um bloco de fatura (texto de um CLIENTE) num dict.

    `referencia` é o nome do PDF (sem extensão) e `pagina` o número da página —
    ambos só compõem as colunas de identificação. Os campos com sufixo `_SEC`
    são a 2ª ocorrência do campo no bloco (faturas trazem endereço/bairro/etc.
    duplicados); quando só há uma ocorrência, o secundário repete o principal.
    """
    # Captura todas as ocorrências de campos duplicados
    enderecos = extract(r"Endere[cç]o:\s*([^\n]+)", bloco, all_matches=True)
    bairros = extract(r"Bairro:\s*([^\n]+)", bloco, all_matches=True)
    municipios = extract(r"Munic[ií]pio:\s*([A-Z\s]+)", bloco, all_matches=True)
    complementos = extract(r"Complemento:\s*([^\n]+)", bloco, all_matches=True)

    endereco_principal = enderecos[0] if len(enderecos) > 0 else ""
    endereco_secundario = enderecos[1] if len(enderecos) > 1 else endereco_principal

    bairro_principal = bairros[0] if len(bairros) > 0 else ""
    bairro_secundario = bairros[1] if len(bairros) > 1 else bairro_principal

    municipio_principal = municipios[0] if len(municipios) > 0 else ""
    municipio_secundario = municipios[1] if len(municipios) > 1 else municipio_principal

    complemento_principal = complementos[0] if len(complementos) > 0 else ""
    complemento_secundario = complementos[1] if len(complementos) > 1 else complemento_principal

    # Dados da fatura
    dados = {
        "REFERÊNCIA": referencia,
        "PÁGINA": pagina,

        # Cabeçalho principal
        "CLIENTE": extract(r"CLIENTE:\s*(\d+\s*-\s*[A-Z\s]+)", bloco),
        #"CONTA_CONTRATO": extract(r"CONTA CONTRATO:\s*(\d+)", bloco),
        "ENDERECO": endereco_principal,
        "MUNICIPIO": municipio_principal,
        "BAIRRO": bairro_principal,
        "REFERENCIA": extract(r"Refer[eê]ncia:\s*([\d/]+)", bloco),
        "VENCIMENTO": extract(r"Vencimento:\s*([\d\-\/]+)", bloco),
        "DOCUMENTO": extract(r"Documento:\s*(\d+)", bloco),
        "COMPLEMENTO": complemento_principal,
        "VALOR": extract(r"Valor:\s*([\d\.,]+)", bloco),

        # Empresa / Local
        "EMPRESA": extract(r"Empresa:\s*([^\n]+)", bloco),
        "LOCAL": extract(r"Local:\s*([^\n]+)", bloco),
        "CONJ_CONTRATO": extract(r"Conj\.Contrato:\s*([^\s\n]+)", bloco),
        "UNIDADE_LEITURA": extract(r"Unidade de Leitura:\s*([^\s\n]+)", bloco),
        "REFERENCIA_SEC": extract(r"Refer[eê]ncia:\s*([\d/]+)", bloco),

        # Segunda seção (dados da instalação)
        "NOME": extract(r"Nome:\s*([^\n]+)", bloco),
        "ENDERECO_SEC": endereco_secundario,
        "BAIRRO_SEC": bairro_secundario,
        #"UNIDADE_CONSUMIDORA": extract(r"Instala[cç][aã]o:\s*(\d+)", bloco),
        "MUNICIPIO_SEC": municipio_secundario,
        "COMPLEMENTO_SEC": complemento_secundario,
        "FATURA": extract(r"Fatura:\s*(\d+)", bloco),
        "INSTALACAO": extract(r"Instala[cç][aã]o:\s*(\d+)", bloco),
        "UNIDADE_CONSUMIDORA": extract(r"UNIDADE\s+CONSUMIDORA:\s*([^\s\n]+)", bloco),

        # Dados técnicos
        "CLASSE_PRINCIPAL": extract(r"Classe Principal[:\s\n]+(\d+)", bloco),
        "CLASSE_CONSUMO": extract(r"Classe de Consumo[:\s\n]+(\d+)", bloco),
        "TENSAO": extract(r"Tens[aã]o[:\s\n]+([A-Z0-9]+)", bloco),
        "FASE": extract(r"Fase[:\s\n]+([\d,]+)", bloco),
        "DATA_FAT": extract(r"Data Fat\.?[:\s\n]+([\d/]+)", bloco),
        "DIAS_FAT": extract(r"Dias Fat\.?[:\s\n]+(\d+)", bloco),
        "DATA_LEIT_ANT": extract(r"Dta\.Leit\.Ant[:\s\n]+([\d/]+)", bloco),
        "DATA_LEIT_ATUAL": extract(r"Dta\.Leit\.Atual[:\s\n]+([\d/]+)", bloco),
        "REAVISO": extract(r"Reaviso[:\s\n]*([^\n]*)", bloco),
        "CORTE": extract(r"Corte[:\s\n]*([^\n]*)", bloco),

        # Hash e nota fiscal
        "HASH_CODE": extract(r"Hash Code:\s*([A-Z0-9\.]+)", bloco),
        "NOTA_FISCAL": extract(r"Nota Fiscal:\s*(\d+)", bloco),
        "APRESENTACAO": extract(r"Apres:\s*([\d/]+)", bloco),
        "VENCIMENTO_SEC": extract(r"Vecto:\s*([\d/]+)", bloco),
        "RECOLHIMENTO": extract(r"Recolhimento:\s*([\d/]+)", bloco),
        "VALOR_SEC": extract(r"Valor\s+até\s+o\s+vencimento[:\s]*([\d\.,]+)", bloco),

        "VALOR_NUM": extract(r"Hash Code:[\s\S]*?Valor:\s*([\d\.,]+)", bloco),

        # Tributos
        "ICMS_BaseCalculo": extract(r"ICMS\s*([\d\.,]+)\s*[\d,]+\s*[\d\.,]+", bloco),
        "ICMS_Aliquota": extract(r"ICMS\s*[\d\.,]+\s*([\d,]+)\s*[\d\.,]+", bloco),
        "ICMS_Valor": extract(r"ICMS\s*[\d\.,]+\s*[\d,]+\s*([\d\.,]+)", bloco),
        "COFINS_BaseCalculo": extract(r"COFINS\s*([\d\.,]+)\s*[\d,]+\s*[\d\.,]+", bloco),
        "COFINS_Aliquota": extract(r"COFINS\s*[\d\.,]+\s*([\d,]+)\s*[\d\.,]+", bloco),
        "COFINS_Valor": extract(r"COFINS\s*[\d\.,]+\s*[\d,]+\s*([\d\.,]+)", bloco),
        "PIS_BaseCalculo": extract(r"PIS\s*([\d\.,]+)\s*[\d,]+\s*[\d\.,]+", bloco),
        "PIS_Aliquota": extract(r"PIS\s*[\d\.,]+\s*([\d,]+)\s*[\d\.,]+", bloco),
        "PIS_Valor": extract(r"PIS\s*[\d\.,]+\s*[\d,]+\s*([\d\.,]+)", bloco),

        # Medição
        "Medidor": extract(r"CAT\s*(\d+)", bloco),
        "Cte": extract(r"CAT\s*\d+\s*([\d,]+)", bloco),
        "Leit_Anterior": extract(r"Leit\. Anterior\s*([\d\.,]+)", bloco),
        "Leit_Atual": extract(r"Leit\. Atual\s*([\d\.,]+)", bloco),
        "Medido": extract(r"CAT\s+\S+\s+[\d\.,]+\s+[\d\.,]+\s+[\d\.,]+\s+[\d\.,]+\s+([\d\.,]+)", bloco),
        "Faturado": extract(r"Faturado[\s\S]*?([\d\.,]+)", bloco),

        # Valores Faturados
        "Cip_Ilum_Pub_Pref_Munic": extract(r"Cip-Ilum Pub Pref Munic\s+([\d\.,]+)", bloco),

        "Consumo_quantidade": extract(r"Consumo\s+([\d\.,]+)\s+[\d\.,]+\s+[\d\.,]+", bloco),
        "Consumo_preco": extract(r"Consumo\s+[\d\.,]+\s+([\d\.,]+)\s+[\d\.,]+", bloco),
        "Consumo_valor": extract(r"Consumo\s+[\d\.,]+\s+[\d\.,]+\s+([\d\.,]+)", bloco),

        "Consumo_Compensado_quantidade": extract(r"Consumo Compensado\s+([\d\.,]+)\s+[\d\.,]+\s+[\d\.,]+", bloco),
        "Consumo_Compensado_preco": extract(r"Consumo Compensado\s+[\d\.,]+\s+([\d\.,]+)\s+[\d\.,]+", bloco),
        "Consumo_Compensado_valor": extract(r"Consumo Compensado\s+[\d\.,]+\s+[\d\.,]+\s+([\d\.,]+)", bloco),

        "Dev_Geracao_quantidade": extract(r"(?m)^\s*Dev.*?\s+([\d\.,]+-?)\s+[\d\.,]+-?\s+[\d\.,]+-?", bloco),
        "Dev_Geracao_preco": extract(r"(?m)^\s*Dev.*?\s+[\d\.,]+-?\s+([\d\.,]+-?)\s+[\d\.,]+-?", bloco),
        "Dev_Geracao_valor": extract(r"(?m)^\s*Dev.*?\s+[\d\.,]+-?\s+[\d\.,]+-?\s+([\d\.,]+-?)", bloco),

        "Adicional_Bandeira_valor": extract(r"Adicional Bandeira\s+([\d\.,]+)", bloco),
        "Multa_valor": extract(r"Multa\s+([\d\.,]+)", bloco),
        "Correcao_Monetaria_valor": extract(r"Corre[cç][aã]o Monet[aá]ria\s+([\d\.,]+)", bloco),
        "Juros_valor": extract(r"Juros\s+([\d\.,]+)", bloco),
    }

    return dados


def main():
    # Pasta com os PDFs
    # pdf_folder = Path("C:/Users/giovana.lima/OneDrive - Omega Energia S.A/Giovana/Projetos/aegea/Faturas_Piauí_Abril/Todas as Faturas")
    # pdf_folder = Path("C:/Users/leticia.neiva/Serena/Comercializadora - 2. Faturamento Usinas - Parceiros/AEGEA/FATURAS/Faturas_Piauí_Abril/Todas_as_Faturas")
    pdf_folder = Path.home() / "Documents" / "AEGEA" / "Faturas_Piauí_Abril" / "Todas as Faturas"

    # Lista para armazenar todas as faturas
    faturas = []

    # Itera sobre todos os PDFs da pasta
    for pdf_path in pdf_folder.glob("*.PDF"):
        print(f"📂 Processando arquivo: {pdf_path.name}")
        with fitz.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf, start=1):
                print(f"   ➡ Página {page_num}")
                text = page.get_text("text")
                blocos = re.split(r"(?=CLIENTE:)", text)

                for bloco in blocos:
                    if not bloco.strip().startswith("CLIENTE:"):
                        continue
                    faturas.append(parse_bloco(bloco, pdf_path.stem, page_num))

    # Cria DataFrame
    df = pd.DataFrame(faturas)[colunas]

    # Sanitiza chars ilegais para o Excel (controle ASCII, zero-width, NBSP)
    try:
        df = df.map(_clean)            # pandas >= 2.1
    except AttributeError:
        df = df.applymap(_clean)       # fallback versões antigas

    # Exporta com fallback em caso de arquivo travado
    # output_path = "C:/Users/giovana.lima/OneDrive - Omega Energia S.A/Giovana/Projetos/aegea/Faturas_Piauí_Abrilv5.xlsx"
    # output_path = "C:/Users/leticia.neiva/Serena/Comercializadora - 2. Faturamento Usinas - Parceiros/AEGEA/FATURAS/Faturas_Piauí_Abril.xlsx"
    output_path = Path.home() / "Documents" / "AEGEA" / "Faturas_Piauí_Junho.xlsx"

    try:
        df.to_excel(output_path, index=False)
        print(f"✅ Extração concluída! Arquivo salvo em: {output_path}")
    except (PermissionError, OSError) as e:
        fallback = output_path.with_name(
            f"{output_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        print(f"⚠ Arquivo de destino travado ({e}). Salvando em: {fallback}")
        df.to_excel(fallback, index=False)
        print(f"✅ Extração concluída! Arquivo salvo em: {fallback}")


if __name__ == "__main__":
    main()
