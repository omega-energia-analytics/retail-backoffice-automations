"""Testes do Quick Invoices Usinas no monitor (quick_invoices.py).

Cobre só a lógica pura e o contrato das peças novas — nada aqui toca Snowflake, SharePoint ou
Excel. O que depende deles (buscar/enviar de ponta a ponta) fica para o teste manual descrito
no README.
"""
import json
from datetime import date

import pandas as pd
import pytest

import quick_invoices as qi
from app import quick_invoices_log as qlog


# ---------------------------------------------------------------------------
# validações de entrada
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dias,esperado", [(30, 30), ("7", 7), (" 90 ", 90), (1, 1), (365, 365)])
def test_validar_dias_aceita(dias, esperado):
    assert qi.validar_dias(dias) == esperado


@pytest.mark.parametrize("dias", [0, -3, 366, "abc", "", None, "3.5"])
def test_validar_dias_rejeita(dias):
    with pytest.raises(ValueError):
        qi.validar_dias(dias)


def test_validar_data_fim():
    hoje = date(2026, 11, 24)
    assert qi.validar_data_fim(None, hoje) == hoje
    assert qi.validar_data_fim("", hoje) == hoje
    assert qi.validar_data_fim("2026-11-20", hoje) == date(2026, 11, 20)
    with pytest.raises(ValueError):
        qi.validar_data_fim("20/11/2026", hoje)


# ---------------------------------------------------------------------------
# chaves para o SQL do Oracle — nada que não seja número chega ao SQL
# ---------------------------------------------------------------------------

def test_montar_in_sql_so_aceita_digitos():
    lista = qi.montar_in_sql({"123", "456", "1'; DROP TABLE X;--", "12 34", "abc", None, ""})
    assert lista == "'123','456'"


def test_montar_in_sql_vazio():
    assert qi.montar_in_sql(set()) == ""


# ---------------------------------------------------------------------------
# normaliza_nff — mesma regra do _nf_key do monitor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("valor", ["047744547", "47744547", "47744547.0", " 47744547 ", 47744547.0])
def test_normaliza_nff_mesma_nota(valor):
    assert qlog.normaliza_nff(valor) == "47744547"


@pytest.mark.parametrize("valor", [None, "", "000", float("nan")])
def test_normaliza_nff_inutil_vira_none(valor):
    assert qlog.normaliza_nff(valor) is None


# ---------------------------------------------------------------------------
# classificar — três status: Nova / Já no Oracle / Processada. Oracle manda sobre o log
# ---------------------------------------------------------------------------

LOGS = {"222": {"run_id": "r1", "executado_em": "2026-11-20T09:30:00-03:00", "usuario": "fulana"}}


def test_classificar_nova():
    assert qi.classificar("111", {}, LOGS)[0] == qi.STATUS_NOVA


def test_classificar_ja_no_oracle():
    assert qi.classificar("111", {"111": True}, LOGS)[0] == qi.STATUS_ORACLE


def test_classificar_so_cancelada_no_oracle_fica_nova_com_aviso():
    """Só versão cancelada não conta como lançada: continua Nova, e o detalhe avisa."""
    status, detalhe = qi.classificar("111", {"111": False}, LOGS)
    assert status == qi.STATUS_NOVA
    assert "cancelada" in detalhe


def test_classificar_processada_traz_quem_e_quando():
    status, detalhe = qi.classificar("222", {}, LOGS)
    assert status == qi.STATUS_PROCESSADA
    assert "fulana" in detalhe and "20/11/2026 09:30" in detalhe


def test_classificar_oracle_ganha_do_log():
    assert qi.classificar("222", {"222": True}, LOGS)[0] == qi.STATUS_ORACLE


def test_classificar_sem_oracle_cai_no_log():
    """Consulta ao Oracle falhou (None): o log ainda protege contra duplicar o que a equipe enviou."""
    assert qi.classificar("222", None, LOGS)[0] == qi.STATUS_PROCESSADA
    assert qi.classificar("111", None, LOGS)[0] == qi.STATUS_NOVA


# ---------------------------------------------------------------------------
# montar_linhas
# ---------------------------------------------------------------------------

def _df():
    return pd.DataFrame({
        "NOTA_FISCAL": ["047744547", "222.0", "333", "444"],
        "CLIENTE_APELIDO": ["6001-CONSORCIO SERENA GD 1", "6011-CONSORCIO SERENA GD 2", None, "6001-CONSORCIO SERENA GD 1"],
        "DISTRIBUIDORA_SIGLA": ["CPFL", "CEMIG DISTRIBUICAO S.A", "CEMIG DISTRIBUICAO S.A", "CPFL"],
        "NUMERO_DO_FORNECEDOR": ["10933", "069811800", "069811800", "10933"],
        "DISTRIBUIDORA_CNPJ": ["33050196000188", "06981180000116", "06981180000116", "33050196000188"],
        "TOTAL_DA_FATURA": [19142.04, "7.525,59", 100.0, 0.0],
        "DATA_DE_EMISSAO_DA_FATURA": pd.to_datetime(["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]),
        "DATA_DE_VENCIMENTO": pd.to_datetime(["2026-11-20", "2026-11-21", "2026-11-22", None]),
    }, index=[10, 11, 12, 13])


def test_montar_linhas_classifica_e_marca_selecao_padrao():
    acr = pd.Series(["GO-AAA-01", None, "GO-CCC-01", "GO-DDD-01"], index=[10, 11, 12, 13])
    linhas = {l["_id"]: l for l in qi.montar_linhas(_df(), acr, oracle={"47744547": True}, logs=LOGS)}

    assert linhas[10]["Status"] == qi.STATUS_ORACLE            # chave normalizada casa '047744547'
    assert linhas[11]["Status"] == qi.STATUS_PROCESSADA        # '222.0' casa '222'
    assert linhas[12]["Status"] == qi.STATUS_NOVA
    assert linhas[13]["Status"] == qi.STATUS_NOVA

    # só "Nova" E sem alerta vem marcada: a 12 tem unidade vazia, a 13 tem valor zerado
    assert [i for i, l in linhas.items() if l["Selecionada"]] == []
    assert "unidade de negócio vazio" in linhas[12]["Alertas"]
    assert "valor zerado" in linhas[13]["Alertas"]
    assert linhas[10]["Acrônimo"] == "GO-AAA-01"
    assert linhas[11]["Valor"] == 7525.59                      # texto BR vira número


def test_montar_linhas_processada_mostra_data_hora_e_quem_enviou():
    [l] = qi.montar_linhas(_df().loc[[11]], None, oracle={}, logs=LOGS)
    assert l["Status"] == qi.STATUS_PROCESSADA
    assert l["Processada Em"] == "2026-11-20T09:30:00-03:00"
    assert l["Processada Por"] == "fulana"
    assert l["Selecionada"] is False                            # já processada: não vem marcada


def test_montar_linhas_nao_processada_nao_tem_data():
    [l] = qi.montar_linhas(_df().loc[[12]].assign(CLIENTE_APELIDO="x"), None, oracle={}, logs=LOGS)
    assert l["Status"] == qi.STATUS_NOVA
    assert l["Processada Em"] is None and l["Processada Por"] is None


def test_montar_linhas_so_cancelada_no_oracle_nao_vem_marcada():
    """Pode haver motivo para relançar, mas quem decide é a pessoa, depois de conferir."""
    df = _df().loc[[10]]
    [l] = qi.montar_linhas(df, None, oracle={"47744547": False}, logs={})
    assert l["Status"] == qi.STATUS_NOVA and l["Selecionada"] is False and l["Padrão"] is False


def test_montar_linhas_nova_sem_defeito_vem_marcada():
    df = _df().loc[[10]]
    [l] = qi.montar_linhas(df, None, oracle={}, logs={})
    assert l["Status"] == qi.STATUS_NOVA and l["Selecionada"] is True and l["Alertas"] == []
    assert l["Padrão"] is True


def test_montar_linhas_e_serializavel_sem_nan():
    """O pywebview serializa com json.dumps; NaN sairia como literal inválido para o JS."""
    linhas = qi.montar_linhas(_df(), None, oracle={}, logs={})
    texto = json.dumps(linhas, allow_nan=False)  # levanta se houver NaN/Inf
    assert "NaN" not in texto


def test_resumir():
    linhas = qi.montar_linhas(_df(), None, oracle={"47744547": True}, logs=LOGS)
    r = qi.resumir(linhas)
    assert r["total"] == 4
    assert r["por_status"] == {qi.STATUS_ORACLE: 1, qi.STATUS_PROCESSADA: 1, qi.STATUS_NOVA: 2}
    assert r["com_alerta"] == 2
    assert r["valor_total"] == round(19142.04 + 7525.59 + 100.0, 2)


# ---------------------------------------------------------------------------
# barradas / incompletas
# ---------------------------------------------------------------------------

def test_montar_barradas_bloqueadas():
    df = pd.DataFrame({
        "ACRONIMO": ["PI-JCO-01"], "NOTA_FISCAL": ["999"], "CLIENTE_APELIDO": ["CONSORCIO GD 1"],
        "TOTAL_DA_FATURA": [50.0], "DATA_DE_EMISSAO_DA_FATURA": pd.to_datetime(["2026-11-01"]),
    })
    [b] = qi.montar_barradas(df, "Usina em nff_bloqueados")
    assert b["Acrônimo"] == "PI-JCO-01" and b["Motivo"] == "Usina em nff_bloqueados"
    json.dumps(b, allow_nan=False)


def test_montar_barradas_incompleta_diz_o_que_falta():
    df = pd.DataFrame({
        "NOTA_FISCAL": ["999"], "CLIENTE_APELIDO": ["CONSORCIO GD 1"], "DISTRIBUIDORA_SIGLA": [None],
        "DISTRIBUIDORA_CNPJ": [None], "TOTAL_DA_FATURA": [50.0],
        "DATA_DE_EMISSAO_DA_FATURA": pd.to_datetime(["2026-11-01"]),
        "DATA_DE_VENCIMENTO_DA_FATURA": pd.to_datetime(["2026-11-20"]),
    })
    [b] = qi.montar_barradas(df, "incompleta")
    assert "fornecedor" in b["Motivo"] and "CNPJ" in b["Motivo"]
    assert "valor" not in b["Motivo"]


def test_montar_barradas_vazio():
    assert qi.montar_barradas(None, "x") == []
    assert qi.montar_barradas(pd.DataFrame(), "x") == []


# ---------------------------------------------------------------------------
# validar_envio — o que protege a planilha
# ---------------------------------------------------------------------------

def _por_id(n=3, **extra):
    base = {"Status": qi.STATUS_NOVA, "NFF": "1"}
    return {i: {**base, **extra} for i in range(n)}


def test_validar_envio_ok_preserva_ordem_e_tira_repetidas():
    assert qi.validar_envio([2, 0, 2, 1], _por_id()) == [2, 0, 1]


def test_validar_envio_vazio():
    with pytest.raises(ValueError, match="Nenhuma NFF"):
        qi.validar_envio([], _por_id())


def test_validar_envio_id_de_outra_busca():
    with pytest.raises(ValueError, match="última busca"):
        qi.validar_envio([0, 99], _por_id())


def test_validar_envio_permite_reenviar_o_que_acabou_de_ir():
    """Quem aborta antes do Upload precisa poder mandar de novo, e como o envio substitui a
    planilha, repetir não duplica nada lá."""
    assert qi.validar_envio([0], _por_id(Status=qi.STATUS_PROCESSADA)) == [0]


def test_validar_envio_barra_acima_da_capacidade_da_planilha():
    """Acima do limite o xlwings estoura no meio da escrita, depois de limpar as colunas."""
    por_id = _por_id(qi.LIMITE_LINHAS_PLANILHA + 1)
    ids = list(por_id)
    assert len(qi.validar_envio(ids[:qi.LIMITE_LINHAS_PLANILHA], por_id)) == qi.LIMITE_LINHAS_PLANILHA
    with pytest.raises(ValueError, match="lotes"):
        qi.validar_envio(ids, por_id)


# ---------------------------------------------------------------------------
# logs: índice de NFFs já lançadas
# ---------------------------------------------------------------------------

def _reg(run_id, quando, usuario, *nffs):
    return {"run_id": run_id, "executado_em": quando, "usuario": usuario,
            "nffs": [{"nff": n} for n in nffs]}


def test_nffs_lancadas_normaliza_e_fica_com_o_run_mais_recente():
    antigo = _reg("a", "2026-11-10T08:00:00-03:00", "ana", "047744547")
    novo = _reg("b", "2026-11-12T08:00:00-03:00", "bia", "47744547.0", "555")
    indice = qlog.nffs_lancadas([novo, antigo])      # ordem de entrada não importa
    assert indice["47744547"]["usuario"] == "bia"
    assert "555" in indice


def test_nffs_lancadas_mesmo_run_lido_duas_vezes_conta_uma():
    r = _reg("a", "2026-11-10T08:00:00-03:00", "ana", "1")
    assert qlog.nffs_lancadas([r, dict(r)]) == qlog.nffs_lancadas([r])


def test_nffs_lancadas_ignora_lixo():
    assert qlog.nffs_lancadas([None, "x", {"run_id": "z"}, {"run_id": "y", "nffs": [{"nff": None}]}]) == {}


def test_ler_logs_locais_pendentes_e_enviados_com_corte_por_data(tmp_path):
    for sub, nome, nff in [("pendentes", "20261120T100000_u_m_aaaaaa.json", "1"),
                           ("enviados", "20261101T100000_u_m_bbbbbb.json", "2"),
                           ("enviados", "20261123T100000_u_m_cccccc.json", "3")]:
        (tmp_path / sub).mkdir(exist_ok=True)
        (tmp_path / sub / nome).write_text(json.dumps(_reg(nome, "2026-11-20T10:00:00", "u", nff)), encoding="utf-8")
    (tmp_path / "enviados" / "20261122T100000_u_m_dddddd.json").write_text("{quebrado", encoding="utf-8")

    todos = qlog.ler_logs_locais(tmp_path)
    assert sorted(r["nffs"][0]["nff"] for r in todos) == ["1", "2", "3"]     # corrompido ignorado

    recentes = qlog.ler_logs_locais(tmp_path, desde=date(2026, 11, 15))
    assert sorted(r["nffs"][0]["nff"] for r in recentes) == ["1", "3"]


def test_ler_logs_locais_sem_pasta(tmp_path):
    assert qlog.ler_logs_locais(tmp_path / "nao_existe") == []


@pytest.mark.parametrize("nome,esperado", [
    ("20261112T094312_fulano_PC-01_ab12cd.json", date(2026, 11, 12)),
    ("qualquer.json", None),
    ("20261399T094312_x.json", None),
])
def test_data_do_nome(nome, esperado):
    assert qlog._data_do_nome(nome) == esperado


# ---------------------------------------------------------------------------
# registrar_run devolve o desfecho
# ---------------------------------------------------------------------------

CONF = {"model_parameters": {"input_files": {"shp": {"drive_id": "d"}},
                             "log_quick_invoices": {"pasta_shp": "p"}}}


def _df_log():
    return pd.DataFrame({"NOTA_FISCAL": ["1"], "TOTAL_DA_FATURA": [10.0]})


def test_registrar_run_status_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(qlog, "obter_token_graph", lambda: "t")
    monkeypatch.setattr(qlog, "upload_sharepoint", lambda t, d, p: lambda n, c: None)
    assert qlog.registrar_run(_df_log(), CONF, pasta=tmp_path) == "ok"


def test_registrar_run_status_pendente_sem_rede(tmp_path, monkeypatch):
    def sem_token():
        raise ConnectionError("sem VPN")
    monkeypatch.setattr(qlog, "obter_token_graph", sem_token)
    assert qlog.registrar_run(_df_log(), CONF, pasta=tmp_path) == "pendente"


def test_registrar_run_status_falhou_sem_log_local(tmp_path):
    assert qlog.registrar_run(object(), CONF, pasta=tmp_path) == "falhou"
