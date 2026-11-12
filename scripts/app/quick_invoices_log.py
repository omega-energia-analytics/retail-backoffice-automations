"""Log de execução do Quick Invoices CUSD — base do KPI "% das NFFs CUSD lançadas pela automação".

POR QUE EXISTE
    O Oracle não diferencia NFF gerada pelo quickinvoices de NFF digitada à mão: as duas sobem
    pela mesma planilha ADFDI e chegam com a mesma origem (INVOICE_SOURCE_CODE = 'INVOICE
    GATEWAY' em 100% das NFFs de usina de 2026, medido em 12/11/2026). Também não há marca
    indireta confiável — descrição vem sempre vazia e a data da NFF é "depois da emissão" nos
    dois casos. A única forma de saber o que passou pela automação é ela mesma registrar.

O QUE GRAVA
    Um JSON por execução do `run()`, com quem rodou, onde, os parâmetros e as NFFs que foram
    escritas na planilha. O monitor de observability lê esses arquivos e cruza com o Oracle:
        automação = NFF CUSD no Oracle que aparece em algum log
        manual    = NFF CUSD no Oracle que não aparece em nenhum log
        ajustada  = está no log, mas o valor difere do INVOICEAMOUNT do Oracle

ONDE GRAVA — local primeiro, SharePoint depois
    1. ~/Faturas Oracle/log_quickinvoices/pendentes/<run_id>.json
    2. upload via Graph para a pasta `log_quick_invoices.pasta_shp` do conf
    3. o que subiu vai para .../enviados/; o que falhou fica em pendentes/ e sobe no próximo run

    Log que não chega ao SharePoint vira "manual" no KPI (falso manual), então o arquivo
    nunca é descartado por falha de rede: fica pendente até subir.

NUNCA DERRUBA O QUICK INVOICES
    `registrar_run` engole qualquer exceção e só avisa no terminal. Ficar sem a planilha por
    causa do log seria pior do que ficar sem uma linha do log.
"""
import getpass
import json
import platform
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

VERSAO_FORMATO = 1

PASTA_LOCAL_PADRAO = Path.home() / "Faturas Oracle" / "log_quickinvoices"

# Colunas do df que sai de CreateQuickInvoices.format_to_quick_invoices. Os nomes são os da
# query, mas os VALORES de CLIENTE_APELIDO e DISTRIBUIDORA_SIGLA já foram trocados pelo
# rename_maps do conf (unidade de negócio e razão social do Oracle) — é o que foi para a planilha.
CAMPOS_NFF = {
    "nff": "NOTA_FISCAL",
    "valor": "TOTAL_DA_FATURA",
    "fornecedor": "DISTRIBUIDORA_SIGLA",
    "unidade_de_negocio": "CLIENTE_APELIDO",
    "emissao": "DATA_DE_EMISSAO_DA_FATURA",
    "vencimento": "DATA_DE_VENCIMENTO",
}


# ---------------------------------------------------------------------------
# Lógica pura (testável sem disco nem rede)
# ---------------------------------------------------------------------------

def _seguro_para_arquivo(texto):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(texto)) or "desconhecido"


def _vazio(valor):
    return valor is None or (not isinstance(valor, str) and pd.isna(valor))


def _texto(valor):
    """Texto ou None. NaN do pandas viraria o literal NaN no JSON, que não é JSON válido."""
    return None if _vazio(valor) else str(valor).strip()


def _texto_nff(valor):
    """NFF como texto, sem o '.0' de quando passou por float. Zeros à esquerda ficam: quem
    lê normaliza a chave (mesma regra do _nf_key do monitor de NFF) e a NFF exibida continua
    a original."""
    if _vazio(valor):
        return None
    texto = re.sub(r"\.0$", "", str(valor).strip())
    return texto or None


def _numero(valor):
    """Valor em reais como float. Aceita número ou texto BR ('1.234,56'), porque nada garante
    que a coluna tenha o tipo que o nome sugere (ver README do monitor de NFF). Texto que não
    der para converter é guardado cru — melhor que perder a linha."""
    if _vazio(valor):
        return None
    if isinstance(valor, (int, float)):
        return round(float(valor), 2)
    texto = str(valor).strip()
    try:
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        return round(float(texto), 2)
    except ValueError:
        return str(valor)


def _data(valor):
    if _vazio(valor):
        return None
    if isinstance(valor, (datetime, date, pd.Timestamp)):
        return valor.strftime("%Y-%m-%d")
    return str(valor)


def _parametro(valor):
    if isinstance(valor, (datetime, date, pd.Timestamp)):
        return valor.isoformat()
    return valor


def montar_registro(df, parametros=None, usuario=None, maquina=None, agora=None):
    """Monta o dict do log de um run a partir do df que foi escrito na planilha."""
    agora = agora or datetime.now().astimezone()
    usuario = usuario or getpass.getuser()
    maquina = maquina or platform.node()

    nffs = []
    if df is not None:
        for _, linha in df.iterrows():
            nffs.append({
                "nff": _texto_nff(linha.get(CAMPOS_NFF["nff"])),
                "valor": _numero(linha.get(CAMPOS_NFF["valor"])),
                "fornecedor": _texto(linha.get(CAMPOS_NFF["fornecedor"])),
                "unidade_de_negocio": _texto(linha.get(CAMPOS_NFF["unidade_de_negocio"])),
                "emissao": _data(linha.get(CAMPOS_NFF["emissao"])),
                "vencimento": _data(linha.get(CAMPOS_NFF["vencimento"])),
            })

    valores = [n["valor"] for n in nffs if isinstance(n["valor"], float)]
    run_id = "_".join([
        agora.strftime("%Y%m%dT%H%M%S"),
        _seguro_para_arquivo(usuario),
        _seguro_para_arquivo(maquina),
        uuid.uuid4().hex[:6],
    ])

    return {
        "versao": VERSAO_FORMATO,
        "run_id": run_id,
        "executado_em": agora.isoformat(timespec="seconds"),
        "usuario": usuario,
        "maquina": maquina,
        "parametros": {k: _parametro(v) for k, v in (parametros or {}).items()},
        "qtd_nffs": len(nffs),
        "valor_total": round(sum(valores), 2),
        "nffs": nffs,
    }


# ---------------------------------------------------------------------------
# Disco e rede
# ---------------------------------------------------------------------------

def salvar_local(registro, pasta=PASTA_LOCAL_PADRAO):
    destino = Path(pasta) / "pendentes"
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"{registro['run_id']}.json"
    arquivo.write_text(
        json.dumps(registro, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return arquivo


def enviar_pendentes(upload, pasta=PASTA_LOCAL_PADRAO):
    """Sobe tudo o que está em pendentes/ (inclusive de runs anteriores que falharam).

    `upload(nome_arquivo, conteudo_bytes)` levanta exceção se falhar. Cada arquivo é
    independente: um que falha não impede os outros. Devolve (enviados, falhas).
    """
    pendentes = Path(pasta) / "pendentes"
    enviados_dir = Path(pasta) / "enviados"
    enviados, falhas = [], []
    if not pendentes.is_dir():
        return enviados, falhas

    for arquivo in sorted(pendentes.glob("*.json")):
        try:
            upload(arquivo.name, arquivo.read_bytes())
        except Exception as e:  # noqa: BLE001 — qualquer falha deixa o arquivo pendente
            falhas.append((arquivo.name, str(e)))
            continue
        enviados_dir.mkdir(parents=True, exist_ok=True)
        arquivo.replace(enviados_dir / arquivo.name)
        enviados.append(arquivo.name)
    return enviados, falhas


def obter_token_graph():
    """Token client_credentials do Graph com as credenciais do jobs_backoffice/.env.

    Importa o ENV_PATH aqui dentro para o módulo continuar importável (e testável) sem o
    snowflake-connector que o src_usinas puxa.
    """
    import os

    import requests
    from dotenv import load_dotenv

    from utils.src_usinas import ENV_PATH

    load_dotenv(ENV_PATH)
    tenant = os.getenv("TENANT_ID")
    resposta = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("CLIENT_ID"),
            "client_secret": os.getenv("CLIENT_SECRET"),
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    resposta.raise_for_status()
    return resposta.json()["access_token"]


def upload_sharepoint(token, drive_id, pasta_shp):
    """Devolve a função `upload(nome, conteudo)` que grava na pasta do SharePoint.

    PUT por caminho cria as pastas intermediárias que faltarem. O nome do arquivo é único
    por run (timestamp + usuário + máquina + sufixo aleatório), então reenviar um arquivo
    cuja resposta se perdeu só sobrescreve ele mesmo.
    """
    import requests

    def upload(nome, conteudo):
        caminho = quote(f"{pasta_shp.strip('/')}/{nome}", safe="/")
        resposta = requests.put(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{caminho}:/content",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            data=conteudo,
            timeout=30,
        )
        resposta.raise_for_status()

    return upload


def registrar_run(df, conf, parametros=None, pasta=PASTA_LOCAL_PADRAO):
    """Grava o log do run e tenta subir os pendentes. Nunca levanta exceção."""
    try:
        registro = montar_registro(df, parametros)
        arquivo = salvar_local(registro, pasta)
        print(f"[LOG QUICK INVOICES] {registro['qtd_nffs']} NFF(s) registradas em {arquivo.name}")
    except Exception as e:  # noqa: BLE001
        print(f"[LOG QUICK INVOICES] ⚠ não foi possível gravar o log local: {e}")
        return

    try:
        model_parameters = conf["model_parameters"]
        drive_id = model_parameters["input_files"]["shp"]["drive_id"]
        pasta_shp = model_parameters["log_quick_invoices"]["pasta_shp"]
        upload = upload_sharepoint(obter_token_graph(), drive_id, pasta_shp)
        enviados, falhas = enviar_pendentes(upload, pasta)
    except Exception as e:  # noqa: BLE001
        print(
            f"[LOG QUICK INVOICES] ⚠ upload para o SharePoint falhou ({e}). "
            f"O log ficou em {Path(pasta) / 'pendentes'} e sobe no próximo run."
        )
        return

    if enviados:
        print(f"[LOG QUICK INVOICES] {len(enviados)} arquivo(s) enviados ao SharePoint.")
    for nome, erro in falhas:
        print(f"[LOG QUICK INVOICES] ⚠ {nome} não subiu ({erro}); fica pendente.")
