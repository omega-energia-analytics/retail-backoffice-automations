"""KPIs CUSD das usinas — lógica pura da aba KPIs (sem rede, sem Snowflake, sem pywebview).

FONTE ÚNICA = MONITOR DE NFF. A entrada é o `df_merged`/`df_projetos` do
`monitor_nff_app/monitor.carregar_base()`, já com `monitor.pagamento_efetivo()` aplicado
(colunas 'Pago', 'Data Pagamento Efetiva', 'Fonte Pagamento') e `monitor.marcar_substituidas()`
(colunas 'Fatura Válida', 'Substituída'). Assim universo de usinas
(PROJETOS FW/E-MAIL), NFF, "Pago", data de pagamento, Valor Oracle e "Fatura Zerada" são
exatamente os do painel do monitor — os KPIs só agregam de outro jeito (por fatura, e não pela
linha exibida de cada projeto/mês). Não recalcule nada disso aqui: se uma regra mudar, ela muda
no monitor e vale para os dois.

KPI 1 — % do valor das NFFs CUSD lançadas pela automação
    Universo: faturas com NFF no Oracle, pelo mês da DATA DA NFF (DATA_NFF = INVOICEDATE).
    Origem de cada NFF, cruzando com o log do quickinvoices pela chave normalizada:
        automação = está em algum log com o mesmo valor do Oracle
        ajustada  = está no log, mas com valor diferente (alguém mexeu na planilha depois)
        manual    = não está em nenhum log
    KPI = valor automação / valor total. "Ajustada" fica FORA do numerador de propósito: houve
    mão humana — e aparece separada para ninguém confundir com manual puro.
    Antes do primeiro log não há como saber a origem: esses meses saem como "sem log", e o mês
    do primeiro log é parcial (só conta NFF com data a partir dele).

KPI 2 — faturas CUSD não pagas no prazo
    Universo: faturas com vencimento no FattureWeb (prazo real da distribuidora), pelo mês do
    VENCIMENTO. "Pago" e a data são os do monitor:
        no prazo      = paga até o prazo
        atrasada      = paga depois do prazo
        vencida       = não paga e o prazo já passou (inclui fatura que nunca virou NFF)
        a vencer      = não paga e o prazo ainda não passou
        paga s/ data  = paga pela parcela do Oracle, sem data nenhuma: fora da contagem
        substituída   = refaturamento: a usina tem outra fatura válida da mesma competência
                        (regra do monitor, marcar_substituidas): fora da contagem, listada
        cancelada     = NFF cancelada no Oracle sem versão válida: fora da contagem, listada
        sem vencimento = sem vencimento no FattureWeb: não dá para julgar, fica listada pelo
                         mês de chegada e fora da contagem
    KPI = atrasadas + vencidas. Vencimento em sábado/domingo vale até o próximo dia útil
    (feriado não é tratado). Fatura zerada fica de fora (mesma regra do monitor). Pagamento
    pela parcela do Oracle tem data aproximada e sai sinalizado.
"""
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

META_KPI1_PCT = 90.0
META_KPI2_MAX = 2
INICIO_SERIE = "2026-01"  # primeiro mês exibido
TOL = 0.01                # centavo: abaixo disso é arredondamento entre as pontas

_NULOS = {"", "nan", "None", "NaN", "<NA>", "NaT"}

COLUNAS_ESPERADAS = [
    "NOTA_FISCAL", "ACRONIMO", "FONTE", "UC", "FATURA_VALOR", "TOTAL_DA_FATURA", "DATA_NFF",
    "VENCIMENTO_FW", "DATA_CHEGADA", "MES_REF_FW", "STATUS_NFF", "Pago",
    "Data Pagamento Efetiva", "Fonte Pagamento", "Substituída",
]


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

def _vazio(v):
    return v is None or (not isinstance(v, str) and pd.isna(v))


def nf_key(v):
    """Mesma chave do _nf_key do monitor de NFF: sem '.0' e sem zeros à esquerda."""
    if _vazio(v):
        return ""
    t = re.sub(r"\.0$", "", str(v).strip())
    return "" if t in _NULOS else t.lstrip("0")


def dinheiro(v):
    """Mesma regra do monitor._dinheiro: número passa; texto BR ('1.234,56') converte."""
    if _vazio(v):
        return None
    if isinstance(v, (int, float, np.number)):
        return float(v)
    t = str(v).strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def prazo_util(venc):
    """Vencimento em fim de semana vale até a segunda-feira seguinte.

    Mesma regra de `monitor_nff_app/monitor._prazo_util` (coluna "Prazo" do painel do monitor):
    KPI e painel precisam julgar "vencida" igual. Mudou aqui? Mude lá."""
    if pd.isna(venc):
        return venc
    return venc + pd.Timedelta(days=(7 - venc.weekday()) % 7 if venc.weekday() >= 5 else 0)


def meses_da_serie(hoje, inicio=INICIO_SERIE):
    return [m.strftime("%Y-%m") for m in pd.period_range(inicio, hoje.strftime("%Y-%m"), freq="M")]


# ---------------------------------------------------------------------------
# Log do quickinvoices
# ---------------------------------------------------------------------------

def indice_logs(logs):
    """chave -> {valores, usuario, executado_em, run_id} da PRIMEIRA vez que a NFF foi escrita.

    `valores` junta o valor de todos os runs: a NFF é "automação" se o Oracle bate com qualquer
    um deles (a mesma nota entra em vários runs porque a janela do quickinvoices se sobrepõe).
    Devolve também a data do primeiro log, a partir da qual a origem pode ser julgada.
    """
    idx, inicio = {}, None
    for reg in sorted(logs or [], key=lambda r: r.get("executado_em") or ""):
        quando = reg.get("executado_em")
        if quando:
            dia = datetime.fromisoformat(quando).date()
            inicio = dia if inicio is None else min(inicio, dia)
        for n in reg.get("nffs") or []:
            chave = nf_key(n.get("nff"))
            if not chave:
                continue
            item = idx.setdefault(chave, {
                "valores": [], "usuario": reg.get("usuario"),
                "executado_em": quando, "run_id": reg.get("run_id"),
            })
            valor = dinheiro(n.get("valor"))
            if valor is not None:
                item["valores"].append(valor)
    return idx, inicio


def origem(chave, valor_oracle, idx):
    item = idx.get(chave)
    if not item:
        return "manual"
    if valor_oracle is None or pd.isna(valor_oracle) or not item["valores"]:
        return "automacao"
    return "automacao" if any(abs(v - valor_oracle) <= TOL for v in item["valores"]) else "ajustada"


# ---------------------------------------------------------------------------
# Base (vinda do monitor de NFF)
# ---------------------------------------------------------------------------

def preparar(df_merged, df_projetos):
    """Recorta o universo do painel do monitor e deixa uma linha por NFF.

    Universo = acrônimos de `df_projetos` (o carregar_base já deixa só FW/E-MAIL; as usinas
    N/A — as mesmas de nff_bloqueados — ficam de fora, como no painel).
    """
    d = df_merged.copy()
    for c in COLUNAS_ESPERADAS:
        if c not in d.columns:
            d[c] = None

    projetos = df_projetos[["ACRONIMO", "Distribuidora"]].copy()
    projetos["ACRONIMO"] = projetos["ACRONIMO"].astype(str).str.strip()
    distribuidora = projetos.drop_duplicates("ACRONIMO").set_index("ACRONIMO")["Distribuidora"]

    d["ACRONIMO"] = d["ACRONIMO"].astype(str).str.strip()
    d = d[d["ACRONIMO"].isin(distribuidora.index)].copy()
    d["CHAVE"] = d["NOTA_FISCAL"].map(nf_key)
    d = d[d["CHAVE"] != ""].copy()

    # A mesma nota pode aparecer mais de uma vez no df_merged. Fica uma por NFF, com a mesma
    # preferência do painel: linha do monitoramento vence a suplementar.
    d["_PRIO"] = d["FONTE"].eq("MONITORAMENTO").astype(int)
    d["_PAGO"] = d["Pago"].fillna(False).astype(bool).astype(int)
    d = d.sort_values(["_PRIO", "_PAGO"]).groupby("CHAVE").tail(1).copy()

    for c in ("DATA_NFF", "VENCIMENTO_FW", "DATA_CHEGADA", "Data Pagamento Efetiva"):
        d[c] = pd.to_datetime(d[c], errors="coerce")
    d["VALOR_ORACLE"] = pd.to_numeric(d["FATURA_VALOR"], errors="coerce")
    d["TOTAL_FW"] = pd.to_numeric(d["TOTAL_DA_FATURA"].map(dinheiro), errors="coerce")
    d["ZERADA"] = d["TOTAL_FW"].eq(0)  # = 'Fatura Zerada' do monitor
    d["PAGO"] = d["Pago"].fillna(False).astype(bool)
    d["CANCELADA"] = d["STATUS_NFF"].eq("Cancelada") & ~d["PAGO"]  # = 'NFF Cancelada' do monitor
    d["SUBSTITUIDA"] = d["Substituída"].fillna(False).astype(bool)
    d["TEM_NFF"] = (d["VALOR_ORACLE"].notna() | d["DATA_NFF"].notna()) & ~d["STATUS_NFF"].eq("Cancelada")
    d["DATA_PAGAMENTO"] = d["Data Pagamento Efetiva"]
    d["FONTE_PAGAMENTO"] = d["Fonte Pagamento"]
    d["NFF"] = d["NOTA_FISCAL"]
    d["USINA"] = d["ACRONIMO"]
    d["DISTRIBUIDORA"] = d["ACRONIMO"].map(distribuidora)
    d["VALOR"] = d["VALOR_ORACLE"].fillna(d["TOTAL_FW"])
    return d


# ---------------------------------------------------------------------------
# KPI 1
# ---------------------------------------------------------------------------

def kpi1(d, idx, inicio, meses):
    por_mes = {m: {"sem_log": True} for m in meses}
    if inicio is None:
        return {"por_mes": por_mes, "linhas": []}

    base = d[d["TEM_NFF"] & d["DATA_NFF"].notna()].copy()
    base = base[base["DATA_NFF"].dt.date >= inicio]
    base["MES"] = base["DATA_NFF"].dt.strftime("%Y-%m")
    base["ORIGEM"] = [origem(c, v, idx) for c, v in zip(base["CHAVE"], base["VALOR_ORACLE"])]
    base["VALOR_LOG"] = [
        (idx[c]["valores"][-1] if c in idx and idx[c]["valores"] else None) for c in base["CHAVE"]]
    base["USUARIO_LOG"] = [idx[c]["usuario"] if c in idx else None for c in base["CHAVE"]]

    mes_inicio = inicio.strftime("%Y-%m")
    for m in meses:
        if m < mes_inicio:
            continue
        g = base[base["MES"] == m]
        valor = g.groupby("ORIGEM")["VALOR_ORACLE"].sum()
        qtd = g["ORIGEM"].value_counts()
        total = float(g["VALOR_ORACLE"].sum())
        auto = float(valor.get("automacao", 0.0))
        por_mes[m] = {
            "sem_log": False,
            "parcial": m == mes_inicio and inicio.day > 1,
            "valor_total": round(total, 2),
            "valor_automacao": round(auto, 2),
            "valor_ajustada": round(float(valor.get("ajustada", 0.0)), 2),
            "valor_manual": round(float(valor.get("manual", 0.0)), 2),
            "n_automacao": int(qtd.get("automacao", 0)),
            "n_ajustada": int(qtd.get("ajustada", 0)),
            "n_manual": int(qtd.get("manual", 0)),
            "pct": round(100 * auto / total, 1) if total > 0 else None,
        }

    cols = ["MES", "NFF", "USINA", "DISTRIBUIDORA", "DATA_NFF", "VALOR_ORACLE", "VALOR_LOG",
            "ORIGEM", "USUARIO_LOG"]
    return {"por_mes": por_mes, "linhas": _registros(base.sort_values(["MES", "ORIGEM", "USINA"]), cols)}


# ---------------------------------------------------------------------------
# KPI 2
# ---------------------------------------------------------------------------

def kpi2(d, hoje, meses):
    hoje = pd.Timestamp(hoje)
    vivas = d[~d["ZERADA"]].copy()  # zerada: nada a pagar

    # Sem vencimento no FattureWeb não dá para julgar prazo: lista pelo mês de chegada (a
    # âncora do painel do monitor), fora da contagem, para a ausência ficar visível.
    sem_venc = vivas[vivas["VENCIMENTO_FW"].isna() & vivas["DATA_CHEGADA"].notna()].copy()
    sem_venc["MES"] = sem_venc["DATA_CHEGADA"].dt.strftime("%Y-%m")
    sem_venc = sem_venc[sem_venc["MES"] >= meses[0]].copy()
    sem_venc["STATUS"] = np.select(
        [~sem_venc["PAGO"] & sem_venc["SUBSTITUIDA"], sem_venc["CANCELADA"]],
        ["substituida", "cancelada"], default="sem_vencimento")

    base = vivas[vivas["VENCIMENTO_FW"].notna()].copy()
    base["MES"] = base["VENCIMENTO_FW"].dt.strftime("%Y-%m")
    # Só a série exibida: fatura antiga (o monitor não tem data de entrada em operação das
    # usinas) inflaria o badge de vencidas com coisa que ninguém vai mais pagar.
    base = base[base["MES"] >= meses[0]].copy()
    base["PRAZO"] = pd.to_datetime(base["VENCIMENTO_FW"].map(prazo_util))

    pago, data_pg = base["PAGO"], base["DATA_PAGAMENTO"]
    base["STATUS"] = np.select(
        [pago & data_pg.notna() & (data_pg <= base["PRAZO"]),
         pago & data_pg.notna(),
         pago,
         base["SUBSTITUIDA"],   # refaturada: a versão válida é que conta (regra do monitor)
         base["CANCELADA"],     # NFF cancelada no Oracle, sem versão válida
         base["PRAZO"] < hoje],
        ["no_prazo", "atrasada", "paga_sem_data", "substituida", "cancelada", "vencida"],
        default="a_vencer")
    referencia = data_pg.where(pago & data_pg.notna(), hoje)
    base["DIAS_ATRASO"] = np.where(
        base["STATUS"].isin(["atrasada", "vencida"]), (referencia - base["PRAZO"]).dt.days, None)

    todas = pd.concat([base, sem_venc], ignore_index=True)
    todas["SEM_NFF"] = ~todas["TEM_NFF"].astype(bool)
    # Causa nº 1 de atraso em 2026 (83 de 181 pagas com atraso, medido em 12/11/2026): a NFF só
    # entrou no Oracle depois do vencimento da distribuidora. Nas pagas no prazo isso é zero.
    todas["NFF_TARDIA"] = todas["DATA_NFF"].notna() & todas["PRAZO"].notna() & (todas["DATA_NFF"] > todas["PRAZO"])
    todas["DATA_APROXIMADA"] = todas["FONTE_PAGAMENTO"].eq("ORACLE_INSTALLMENT")

    por_mes = {}
    for m in meses:
        g = todas[todas["MES"] == m]
        n = g["STATUS"].value_counts()
        fora = g[g["STATUS"].isin(["atrasada", "vencida"])]
        por_mes[m] = {
            "n_total": int((~g["STATUS"].isin(["sem_vencimento", "substituida", "cancelada"])).sum()),
            "n_no_prazo": int(n.get("no_prazo", 0)),
            "n_atrasada": int(n.get("atrasada", 0)),
            "n_vencida": int(n.get("vencida", 0)),
            "n_a_vencer": int(n.get("a_vencer", 0)),
            "n_paga_sem_data": int(n.get("paga_sem_data", 0)),
            "n_sem_vencimento": int(n.get("sem_vencimento", 0)),
            "n_substituida": int(n.get("substituida", 0)),
            "n_cancelada": int(n.get("cancelada", 0)),
            "kpi": int(len(fora)),
            "valor_fora": round(float(fora["VALOR"].fillna(0).sum()), 2),
            "n_nff_tardia": int(fora["NFF_TARDIA"].sum()),
            "n_sem_nff": int(fora["SEM_NFF"].sum()),
            "n_data_aproximada": int(fora["DATA_APROXIMADA"].sum()),
        }

    cols = ["MES", "NFF", "USINA", "DISTRIBUIDORA", "VENCIMENTO_FW", "PRAZO", "DATA_PAGAMENTO",
            "FONTE_PAGAMENTO", "VALOR", "STATUS", "DIAS_ATRASO", "SEM_NFF", "NFF_TARDIA",
            "DATA_APROXIMADA", "DATA_NFF", "DATA_CHEGADA"]
    problemas = todas[todas["STATUS"].isin(
        ["atrasada", "vencida", "paga_sem_data", "sem_vencimento", "substituida", "cancelada"])]
    return {
        "por_mes": por_mes,
        "linhas": _registros(problemas.sort_values(["MES", "STATUS", "USINA"]), cols),
        "n_vencidas_agora": int((base["STATUS"] == "vencida").sum()),
    }


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

def _json(v):
    if _vazio(v):
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return round(float(v), 2)
    return v


def _registros(df, cols):
    for c in cols:
        if c not in df.columns:
            df = df.assign(**{c: None})
    return [{c.lower(): _json(v) for c, v in zip(cols, linha)} for linha in df[cols].itertuples(index=False)]


def montar_payload(df_merged, df_projetos, logs, hoje=None):
    """`logs=None` = não foi possível ler os logs: KPI 1 sai vazio, KPI 2 segue."""
    hoje = hoje or date.today()
    meses = meses_da_serie(hoje)
    d = preparar(df_merged, df_projetos)
    idx, inicio = indice_logs(logs or [])
    return {
        "hoje": hoje.strftime("%Y-%m-%d"),
        "meses": meses,
        "metas": {"kpi1_pct": META_KPI1_PCT, "kpi2_max": META_KPI2_MAX},
        "logs": None if logs is None else {
            "qtd_runs": len(logs),
            "inicio": inicio.strftime("%Y-%m-%d") if inicio else None,
            "qtd_nffs": len(idx),
        },
        "kpi1": kpi1(d, idx, inicio if logs is not None else None, meses),
        "kpi2": kpi2(d, hoje, meses),
    }
