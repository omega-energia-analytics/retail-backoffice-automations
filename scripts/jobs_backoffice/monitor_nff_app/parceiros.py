"""Faturas de parceiros — leitura da planilha de contratos + marcação "Chegou?".

A planilha (`contratos completos.xlsx`, aba `Controle_Emissão`) é a fonte da
lista de notas a emitir. O "Chegou?" NÃO vem dela: é uma decisão humana marcada
na UI, persistida em `chegou_parceiros.json` — versionado no repo, porque a
planilha é gitignorada (`*.xlsx`) e a marcação precisa sobreviver a um clone
novo e ficar visível no git.

A chave de cada linha é o hash das 8 colunas exibidas no painel. Se qualquer uma
mudar na planilha a linha vira outra e perde a marcação — preferível a herdar a
marcação de uma linha que virou outra coisa.
"""
import hashlib
import json
import os
from datetime import datetime

import pandas as pd

import config

ABA = "Controle_Emissão"

# colunas que formam a identidade da linha (e o que o painel mostra)
COLS_CHAVE = [
    "Parceiro", "FORNECEDOR", "PAGADOR", "Mês Fechamento",
    "Data Emissão", "Tipo de Nota", "Arrendamento", "Projeto",
]

ESTADO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chegou_parceiros.json")


def _fmt(col, valor):
    """Texto estável de uma célula — é o que entra na chave e o que a UI mostra.
    Datas viram ISO para a chave não depender do locale de quem abriu o Excel."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, (pd.Timestamp, datetime)):
        return valor.strftime("%Y-%m-%d")
    return str(valor).strip()


def chave_linha(linha):
    """Hash das 8 colunas de identidade. `linha` é um dict já formatado."""
    bruto = "|".join(linha.get(c, "") for c in COLS_CHAVE)
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:16]


# --- persistência da marcação ---
def carregar_estado():
    try:
        with open(ESTADO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data.get("chegou", {}) if isinstance(data, dict) else {}


def salvar_marcacao(chave, chegou, usuario=None):
    """Grava (ou remove) a marcação de uma linha. Devolve o estado completo."""
    estado = carregar_estado()
    if chegou:
        estado[chave] = {
            "chegou": True,
            "marcado_em": datetime.now().isoformat(timespec="seconds"),
            "marcado_por": usuario or os.getenv("USERNAME") or "",
        }
    else:
        estado.pop(chave, None)
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump({"chegou": estado}, f, indent=2, ensure_ascii=False, sort_keys=True)
    return estado


# --- leitura da planilha ---
def carregar_planilha(caminho=None):
    """Lê a aba de controle e devolve a lista de linhas já formatadas, com a
    chave e o `Chegou` resolvido pelo estado persistido."""
    caminho = caminho or config.get("arquivo_contratos")
    if not caminho or not os.path.exists(caminho):
        raise FileNotFoundError(f"Planilha de contratos não encontrada: {caminho}")

    df = pd.read_excel(caminho, sheet_name=ABA, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()

    faltando = [c for c in COLS_CHAVE if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas ausentes na aba '{ABA}': {', '.join(faltando)}")

    # linha sem Projeto é separador/rodapé da planilha, não uma nota
    df = df[df["Projeto"].notna()]

    estado = carregar_estado()
    registros = []
    for _, r in df.iterrows():
        linha = {c: _fmt(c, r[c]) for c in COLS_CHAVE}
        ts = r["Mês Fechamento"]
        linha["_ano"] = int(ts.year) if isinstance(ts, (pd.Timestamp, datetime)) else None
        linha["_mes"] = int(ts.month) if isinstance(ts, (pd.Timestamp, datetime)) else None
        chave = chave_linha(linha)
        marca = estado.get(chave)
        linha["_chave"] = chave
        linha["Chegou"] = bool(marca)
        linha["Marcado Em"] = marca.get("marcado_em") if marca else None
        linha["Marcado Por"] = marca.get("marcado_por") if marca else None
        registros.append(linha)
    return registros


def listar_meses(registros):
    """Meses de fechamento presentes na planilha, mais recente primeiro."""
    pares = {(r["_ano"], r["_mes"]) for r in registros
             if r["_ano"] and r["_mes"]}
    return [{"ano": a, "mes": m} for (a, m) in sorted(pares, reverse=True)]


def filtrar_mes(registros, ano=None, mes=None):
    if ano is None or mes is None:
        return registros
    return [r for r in registros if r["_ano"] == int(ano) and r["_mes"] == int(mes)]
