"""Testes do log do Quick Invoices (app/quick_invoices_log.py).

Cobre a lógica pura e o ciclo local -> pendentes -> enviados, com upload falso.
Nada aqui toca rede, Graph ou Excel.
"""
import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app import quick_invoices_log as qlog

AGORA = datetime(2026, 11, 12, 9, 43, 12, tzinfo=timezone.utc)


def _df(**over):
    base = {
        "NOTA_FISCAL": ["047744547", "17767235.0"],
        "TOTAL_DA_FATURA": [19142.04, "7.525,59"],
        "DISTRIBUIDORA_SIGLA": ["COMPANHIA PAULISTA DE FORCA E LUZ", np.nan],
        "CLIENTE_APELIDO": ["6001-CONSORCIO SERENA GD 1", "6011-CONSORCIO SERENA GD 2"],
        "DATA_DE_EMISSAO_DA_FATURA": [pd.Timestamp("2026-11-03"), date(2026, 11, 4)],
        "DATA_DE_VENCIMENTO": [pd.Timestamp("2026-11-20"), None],
    }
    base.update(over)
    return pd.DataFrame(base)


def _registro(df=None, **kw):
    return qlog.montar_registro(
        _df() if df is None else df, usuario="fulano", maquina="PC-01", agora=AGORA, **kw
    )


# ---------------------------------------------------------------------------
# montar_registro
# ---------------------------------------------------------------------------

def test_registro_tem_cabecalho_do_run():
    reg = _registro(parametros={"days": 30, "to_date": datetime(2026, 11, 12, 9, 0)})
    assert reg["versao"] == qlog.VERSAO_FORMATO
    assert reg["usuario"] == "fulano"
    assert reg["maquina"] == "PC-01"
    assert reg["executado_em"] == "2026-11-12T09:43:12+00:00"
    assert reg["parametros"] == {"days": 30, "to_date": "2026-11-12T09:00:00"}
    assert reg["run_id"].startswith("20261112T094312_fulano_PC-01_")


def test_nff_perde_ponto_zero_mas_mantem_zero_a_esquerda():
    nffs = [n["nff"] for n in _registro()["nffs"]]
    assert nffs == ["047744547", "17767235"]


def test_valor_aceita_numero_e_texto_brasileiro():
    reg = _registro()
    assert [n["valor"] for n in reg["nffs"]] == [19142.04, 7525.59]
    assert reg["valor_total"] == 26667.63
    assert reg["qtd_nffs"] == 2


def test_valor_que_nao_converte_fica_cru_e_fora_do_total():
    reg = _registro(_df(TOTAL_DA_FATURA=[100.0, "abc"]))
    assert reg["nffs"][1]["valor"] == "abc"
    assert reg["valor_total"] == 100.0


def test_datas_viram_iso_e_nulo_vira_none():
    n1, n2 = _registro()["nffs"]
    assert (n1["emissao"], n1["vencimento"]) == ("2026-11-03", "2026-11-20")
    assert (n2["emissao"], n2["vencimento"]) == ("2026-11-04", None)


def test_nan_vira_none_e_json_fica_valido():
    reg = _registro()
    assert reg["nffs"][1]["fornecedor"] is None
    # allow_nan=False explode se sobrar algum NaN no registro
    json.dumps(reg, allow_nan=False, default=str)


def test_run_sem_nff_tambem_e_registrado():
    reg = _registro(_df().iloc[0:0])
    assert reg["qtd_nffs"] == 0
    assert reg["valor_total"] == 0
    assert reg["nffs"] == []


def test_usuario_com_caractere_estranho_nao_quebra_nome_do_arquivo():
    reg = qlog.montar_registro(_df(), usuario="DOM\\fulano", maquina="PC 01", agora=AGORA)
    assert "\\" not in reg["run_id"] and " " not in reg["run_id"]
    assert reg["usuario"] == "DOM\\fulano"  # o campo guarda o original


# ---------------------------------------------------------------------------
# salvar_local / enviar_pendentes
# ---------------------------------------------------------------------------

def test_salvar_local_grava_em_pendentes(tmp_path):
    reg = _registro()
    arquivo = qlog.salvar_local(reg, tmp_path)
    assert arquivo.parent == tmp_path / "pendentes"
    assert json.loads(arquivo.read_text(encoding="utf-8"))["run_id"] == reg["run_id"]


def test_enviados_saem_de_pendentes(tmp_path):
    qlog.salvar_local(_registro(), tmp_path)
    recebidos = {}
    enviados, falhas = qlog.enviar_pendentes(lambda n, c: recebidos.update({n: c}), tmp_path)
    assert len(enviados) == 1 and falhas == []
    assert list((tmp_path / "pendentes").glob("*.json")) == []
    assert (tmp_path / "enviados" / enviados[0]).exists()
    assert json.loads(recebidos[enviados[0]])["usuario"] == "fulano"


def test_falha_de_upload_mantem_pendente_e_nao_para_os_outros(tmp_path):
    a = qlog.salvar_local(_registro(), tmp_path)
    b = qlog.salvar_local(_registro(), tmp_path)

    def upload(nome, conteudo):
        if nome == a.name:
            raise ConnectionError("sem rede")

    enviados, falhas = qlog.enviar_pendentes(upload, tmp_path)
    assert enviados == [b.name]
    assert [f[0] for f in falhas] == [a.name]
    assert a.exists()


def test_sem_pasta_de_pendentes_nao_faz_nada(tmp_path):
    assert qlog.enviar_pendentes(lambda n, c: None, tmp_path) == ([], [])


# ---------------------------------------------------------------------------
# registrar_run — nunca derruba o quickinvoices
# ---------------------------------------------------------------------------

CONF = {
    "model_parameters": {
        "input_files": {"shp": {"drive_id": "drive"}},
        "log_quick_invoices": {"pasta_shp": "pasta/log"},
    }
}


def test_registrar_run_sem_rede_deixa_pendente_e_nao_levanta(tmp_path, monkeypatch, capsys):
    def sem_token():
        raise ConnectionError("sem VPN")

    monkeypatch.setattr(qlog, "obter_token_graph", sem_token)
    qlog.registrar_run(_df(), CONF, parametros={"days": 7}, pasta=tmp_path)
    assert len(list((tmp_path / "pendentes").glob("*.json"))) == 1
    assert "sobe no próximo run" in capsys.readouterr().out


def test_registrar_run_sobe_tambem_os_pendentes_antigos(tmp_path, monkeypatch):
    qlog.salvar_local(_registro(), tmp_path)  # run anterior que não subiu
    recebidos = []
    monkeypatch.setattr(qlog, "obter_token_graph", lambda: "token")
    monkeypatch.setattr(
        qlog, "upload_sharepoint", lambda token, drive, pasta: lambda n, c: recebidos.append(n)
    )
    qlog.registrar_run(_df(), CONF, pasta=tmp_path)
    assert len(recebidos) == 2
    assert list((tmp_path / "pendentes").glob("*.json")) == []


def test_registrar_run_sem_chave_no_conf_nao_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(qlog, "obter_token_graph", lambda: "token")
    qlog.registrar_run(_df(), {"model_parameters": {}}, pasta=tmp_path)
    assert len(list((tmp_path / "pendentes").glob("*.json"))) == 1


def test_registrar_run_com_df_quebrado_nao_levanta(tmp_path, capsys):
    qlog.registrar_run(object(), CONF, pasta=tmp_path)
    assert "não foi possível gravar o log local" in capsys.readouterr().out
