"""Testes da lógica dos KPIs CUSD (observability/monitor_observability_app/kpis.py).

A entrada imita o `df_merged`/`df_projetos` do monitor_nff_app/monitor.carregar_base(), e o
"Pago" é calculado pelo próprio `monitor.pagamento_efetivo()` — não por uma cópia — porque a
garantia que interessa é bater com o painel do monitor. Nada de rede nem Snowflake.
"""
import json
from datetime import date

import pandas as pd

from testkit import load_job

k = load_job("observability/monitor_observability_app/kpis.py", "kpis_cusd")
monitor = load_job("monitor_nff_app/monitor.py", "monitor_nff_para_kpis")

HOJE = date(2026, 11, 12)

PROJETOS = pd.DataFrame(
    [["UFV A", "GO-PRG-01", "Equatorial GO", 5, "E-MAIL"],
     ["UFV B", "SP-ATN-01", "CPFL Paulista", 19, "E-MAIL"]],
    columns=["Projeto", "ACRONIMO", "Distribuidora", "Dia", "Forma Recebimento"],
)


def linha(**over):
    base = {
        "NOTA_FISCAL": None, "ACRONIMO": "GO-PRG-01", "FONTE": "MONITORAMENTO", "UC": "123",
        "FATURA_VALOR": None, "TOTAL_DA_FATURA": None, "DATA_NFF": None, "VENCIMENTO_FW": None,
        "DATA_CHEGADA": "2026-10-01", "DATA_DE_PAGAMENTO": None, "PAGAMENTO": None,
        "STATUS_INSTALLMENT": None, "DATA_STATUS_INSTALLMENT": None,
    }
    base.update(over)
    return base


def base_monitor(linhas):
    df = pd.DataFrame(linhas or [linha(NOTA_FISCAL="x")]).iloc[: len(linhas)]
    for c in ("DATA_NFF", "VENCIMENTO_FW", "DATA_CHEGADA", "DATA_DE_PAGAMENTO", "PAGAMENTO",
              "DATA_STATUS_INSTALLMENT"):
        df[c] = pd.to_datetime(df[c])
    return monitor.pagamento_efetivo(df)


def log(nffs, quando="2026-11-12T10:12:20-03:00", usuario="fulano"):
    return {"executado_em": quando, "usuario": usuario, "run_id": f"r-{quando}",
            "nffs": [{"nff": n, "valor": v} for n, v in nffs]}


def payload(linhas, logs=()):
    return k.montar_payload(base_monitor(linhas), PROJETOS,
                            list(logs) if logs is not None else None, hoje=HOJE)


def _status(p):
    return {r["nff"]: r["status"] for r in p["kpi2"]["linhas"]}


# ---------------------------------------------------------------------------
# normalização
# ---------------------------------------------------------------------------

def test_nf_key_igual_ao_monitor():
    s = pd.Series(["047744547", "17767235.0", " 0042 ", "nan"])
    esperado = monitor._nf_key(s).fillna("").tolist()
    assert [k.nf_key(v) for v in s] == esperado


def test_dinheiro_igual_ao_monitor():
    s = pd.Series(["32810,15", "1.234,56", 19142.04, "0,0"])
    assert [k.dinheiro(v) for v in s] == monitor._dinheiro(s).tolist()


def test_prazo_util_empurra_fim_de_semana():
    assert k.prazo_util(pd.Timestamp("2026-11-14")) == pd.Timestamp("2026-11-16")  # sábado
    assert k.prazo_util(pd.Timestamp("2026-11-15")) == pd.Timestamp("2026-11-16")  # domingo
    assert k.prazo_util(pd.Timestamp("2026-11-13")) == pd.Timestamp("2026-11-13")  # sexta


# ---------------------------------------------------------------------------
# universo = o do painel do monitor
# ---------------------------------------------------------------------------

def test_so_acronimos_de_projetos_entram():
    p = payload([
        linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-09", FATURA_VALOR=1.0),
        linha(NOTA_FISCAL="2", ACRONIMO="PI-JCO-01", VENCIMENTO_FW="2026-10-09", FATURA_VALOR=1.0),
    ])
    assert set(_status(p)) == {"1"}


def test_mesma_nota_duas_vezes_conta_uma_e_monitoramento_vence():
    p = payload([
        linha(NOTA_FISCAL="047", FONTE="FW_SUPLEMENTO", VENCIMENTO_FW="2026-10-09", FATURA_VALOR=1.0),
        linha(NOTA_FISCAL="47", FONTE="MONITORAMENTO", VENCIMENTO_FW="2026-10-09", FATURA_VALOR=1.0,
              DATA_DE_PAGAMENTO="2026-10-09"),
    ])
    assert p["kpi2"]["por_mes"]["2026-10"]["n_total"] == 1
    assert p["kpi2"]["por_mes"]["2026-10"]["n_no_prazo"] == 1


# ---------------------------------------------------------------------------
# KPI 1
# ---------------------------------------------------------------------------

def test_kpi1_classifica_automacao_manual_ajustada():
    p = payload(
        [
            linha(NOTA_FISCAL="001", DATA_NFF="2026-11-12", FATURA_VALOR=100.0),  # no log, mesmo valor
            linha(NOTA_FISCAL="002", DATA_NFF="2026-11-13", FATURA_VALOR=50.0),   # fora do log
            linha(NOTA_FISCAL="003", DATA_NFF="2026-11-13", FATURA_VALOR=80.0),   # no log, outro valor
        ],
        logs=[log([("001", 100.0), ("003", 70.0)])],
    )
    m = p["kpi1"]["por_mes"]["2026-11"]
    assert (m["n_automacao"], m["n_manual"], m["n_ajustada"]) == (1, 1, 1)
    assert m["valor_total"] == 230.0
    assert m["pct"] == round(100 * 100 / 230, 1)   # ajustada fica fora do numerador
    origens = {r["nff"]: r["origem"] for r in p["kpi1"]["linhas"]}
    assert origens == {"001": "automacao", "002": "manual", "003": "ajustada"}


def test_kpi1_casa_nff_com_grafias_diferentes():
    p = payload([linha(NOTA_FISCAL="47744547", DATA_NFF="2026-11-12", FATURA_VALOR=10.0)],
                logs=[log([("047744547", 10.0)])])
    assert p["kpi1"]["por_mes"]["2026-11"]["n_automacao"] == 1


def test_kpi1_mesma_nff_em_varios_runs_aceita_qualquer_valor():
    p = payload([linha(NOTA_FISCAL="001", DATA_NFF="2026-11-13", FATURA_VALOR=99.0)],
                logs=[log([("001", 90.0)], quando="2026-11-12T10:00:00-03:00"),
                      log([("001", 99.0)], quando="2026-11-12T11:00:00-03:00")])
    m = p["kpi1"]["por_mes"]["2026-11"]
    assert (m["n_automacao"], m["n_ajustada"]) == (1, 0)
    assert p["logs"]["qtd_nffs"] == 1


def test_kpi1_meses_antes_do_log_sao_sem_log_e_mes_do_inicio_e_parcial():
    p = payload(
        [linha(NOTA_FISCAL="001", DATA_NFF="2026-10-20", FATURA_VALOR=10.0),
         linha(NOTA_FISCAL="002", DATA_NFF="2026-11-05", FATURA_VALOR=10.0),
         linha(NOTA_FISCAL="003", DATA_NFF="2026-11-12", FATURA_VALOR=10.0)],
        logs=[log([("003", 10.0)])],
    )
    assert p["kpi1"]["por_mes"]["2026-10"] == {"sem_log": True}
    nov = p["kpi1"]["por_mes"]["2026-11"]
    assert nov["parcial"] is True
    assert nov["n_automacao"] == 1 and nov["n_manual"] == 0   # a 002 não vira "manual" falso


def test_kpi1_sem_log_e_logs_indisponiveis():
    linhas = [linha(NOTA_FISCAL="001", DATA_NFF="2026-11-12", FATURA_VALOR=10.0)]
    assert all(m == {"sem_log": True} for m in payload(linhas, logs=[])["kpi1"]["por_mes"].values())
    p = payload(linhas, logs=None)
    assert p["logs"] is None and p["kpi1"]["por_mes"]["2026-11"] == {"sem_log": True}


# ---------------------------------------------------------------------------
# KPI 2 — "Pago" e data vêm do monitor.pagamento_efetivo
# ---------------------------------------------------------------------------

def test_kpi2_estados():
    venc = "2026-10-09"  # sexta-feira: prazo = vencimento
    p = payload([
        linha(NOTA_FISCAL="1", VENCIMENTO_FW=venc, FATURA_VALOR=100.0, DATA_DE_PAGAMENTO="2026-10-09"),
        linha(NOTA_FISCAL="2", VENCIMENTO_FW=venc, FATURA_VALOR=100.0, DATA_DE_PAGAMENTO="2026-10-14"),
        linha(NOTA_FISCAL="3", VENCIMENTO_FW=venc, FATURA_VALOR=100.0),
        linha(NOTA_FISCAL="4", VENCIMENTO_FW="2026-11-20", FATURA_VALOR=100.0),
    ])
    out = p["kpi2"]["por_mes"]["2026-10"]
    assert (out["n_no_prazo"], out["n_atrasada"], out["n_vencida"], out["kpi"]) == (1, 1, 1, 2)
    assert p["kpi2"]["por_mes"]["2026-11"]["n_a_vencer"] == 1
    assert _status(p) == {"2": "atrasada", "3": "vencida"}
    atraso = {r["nff"]: r["dias_atraso"] for r in p["kpi2"]["linhas"]}
    assert atraso == {"2": 5, "3": (pd.Timestamp(HOJE) - pd.Timestamp(venc)).days}


def test_kpi2_pagamento_do_monitoramento_conta_como_pago():
    p = payload([linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-09", FATURA_VALOR=1.0,
                       PAGAMENTO="2026-10-08")])
    assert p["kpi2"]["por_mes"]["2026-10"]["n_no_prazo"] == 1


def test_kpi2_parcela_paga_usa_data_aproximada_e_sinaliza():
    p = payload([linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-09", FATURA_VALOR=1.0,
                       STATUS_INSTALLMENT="Totalmente paga", DATA_STATUS_INSTALLMENT="2026-10-20")])
    (r,) = p["kpi2"]["linhas"]
    assert r["status"] == "atrasada" and r["data_aproximada"] is True
    assert p["kpi2"]["por_mes"]["2026-10"]["n_data_aproximada"] == 1


def test_kpi2_parcela_paga_sem_data_fica_fora_da_contagem():
    p = payload([linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-09", FATURA_VALOR=1.0,
                       STATUS_INSTALLMENT="Totalmente paga")])
    m = p["kpi2"]["por_mes"]["2026-10"]
    assert m["kpi"] == 0 and m["n_paga_sem_data"] == 1


def test_kpi2_fim_de_semana_paga_na_segunda_esta_no_prazo():
    p = payload([linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-10", FATURA_VALOR=1.0,  # sábado
                       DATA_DE_PAGAMENTO="2026-10-12")])
    assert p["kpi2"]["por_mes"]["2026-10"]["n_no_prazo"] == 1


def test_kpi2_atraso_conta_a_partir_do_prazo_util():
    p = payload([linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-10", FATURA_VALOR=1.0,
                       DATA_DE_PAGAMENTO="2026-10-15")])
    (r,) = p["kpi2"]["linhas"]
    assert (r["prazo"], r["dias_atraso"]) == ("2026-10-12", 3)


def test_kpi2_fatura_sem_nff_vencida_conta():
    p = payload([linha(NOTA_FISCAL="9", VENCIMENTO_FW="2026-10-09", TOTAL_DA_FATURA="1.500,00")])
    (r,) = p["kpi2"]["linhas"]
    assert r["status"] == "vencida" and r["sem_nff"] is True and r["valor"] == 1500.0


def test_kpi2_marca_nff_lancada_depois_do_vencimento():
    p = payload([
        linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-09", DATA_NFF="2026-10-14", FATURA_VALOR=1.0,
              DATA_DE_PAGAMENTO="2026-10-20"),
        linha(NOTA_FISCAL="2", VENCIMENTO_FW="2026-10-09", DATA_NFF="2026-10-05", FATURA_VALOR=1.0,
              DATA_DE_PAGAMENTO="2026-10-13"),
    ])
    rs = {r["nff"]: r for r in p["kpi2"]["linhas"]}
    assert rs["1"]["nff_tardia"] is True and rs["2"]["nff_tardia"] is False
    m = p["kpi2"]["por_mes"]["2026-10"]
    assert (m["kpi"], m["n_nff_tardia"]) == (2, 1)


def test_kpi2_sem_vencimento_fica_listada_pela_chegada_e_fora_da_conta():
    p = payload([linha(NOTA_FISCAL="1", FATURA_VALOR=1.0, DATA_CHEGADA="2026-10-03")])
    m = p["kpi2"]["por_mes"]["2026-10"]
    assert (m["kpi"], m["n_total"], m["n_sem_vencimento"]) == (0, 0, 1)
    assert _status(p) == {"1": "sem_vencimento"}


def test_kpi2_zerada_e_anterior_a_serie_ficam_de_fora():
    p = payload([
        linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-09", TOTAL_DA_FATURA="0,0", FATURA_VALOR=0.0),
        linha(NOTA_FISCAL="2", VENCIMENTO_FW="2025-06-10", FATURA_VALOR=10.0, DATA_CHEGADA="2025-06-01"),
    ])
    assert p["kpi2"]["linhas"] == []
    assert p["kpi2"]["n_vencidas_agora"] == 0


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------

def test_payload_e_json_valido_e_serie_vai_de_jan_ate_o_mes_atual():
    p = payload([linha(NOTA_FISCAL="1", VENCIMENTO_FW="2026-10-09", FATURA_VALOR=1.0, DATA_NFF="2026-11-12")],
                logs=[log([("1", 1.0)])])
    json.dumps(p, allow_nan=False)
    assert p["meses"][0] == "2026-01" and p["meses"][-1] == "2026-11"


def test_payload_com_base_vazia():
    p = payload([], logs=[])
    assert p["kpi2"]["por_mes"]["2026-11"]["kpi"] == 0
    json.dumps(p, allow_nan=False)
