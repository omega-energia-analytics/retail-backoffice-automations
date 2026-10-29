"""Testes de config.py — resolução portável de configuração.

Invariante central: a prioridade de cada valor é
    variável de ambiente  >  settings.json  >  default
Esses testes protegem essa cascata e a persistência no settings.json, sem tocar
no settings.json real do usuário (tudo é redirecionado pra tmp_path).
"""
import json

import pytest

import config


@pytest.fixture
def settings_isolado(tmp_path, monkeypatch):
    """Redireciona o settings.json pra um arquivo temporário e limpa as env vars
    MONITOR_NFF_* — garante que cada teste parte de um estado conhecido."""
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SETTINGS_PATH", str(settings_path))
    for chave in config.DEFAULTS:
        monkeypatch.delenv(config._ENV_PREFIX + chave.upper(), raising=False)
    return settings_path


def test_get_retorna_default_sem_env_nem_settings(settings_isolado):
    # nada definido -> cai no default
    assert config.get("aba") == config.DEFAULTS["aba"]
    assert config.get("header_linha") == config.DEFAULTS["header_linha"]


def test_get_settings_sobrepoe_default(settings_isolado):
    settings_isolado.write_text(json.dumps({"aba": "OUTRA_ABA"}), encoding="utf-8")
    assert config.get("aba") == "OUTRA_ABA"


def test_get_env_sobrepoe_settings(settings_isolado, monkeypatch):
    settings_isolado.write_text(json.dumps({"aba": "ABA_DO_JSON"}), encoding="utf-8")
    monkeypatch.setenv("MONITOR_NFF_ABA", "ABA_DO_ENV")
    # env tem prioridade máxima
    assert config.get("aba") == "ABA_DO_ENV"


def test_get_ignora_env_vazia(settings_isolado, monkeypatch):
    # env var setada como "" não deve sobrepor o settings/default (regra `not in (None, "")`)
    settings_isolado.write_text(json.dumps({"aba": "ABA_DO_JSON"}), encoding="utf-8")
    monkeypatch.setenv("MONITOR_NFF_ABA", "")
    assert config.get("aba") == "ABA_DO_JSON"


def test_get_ignora_valor_vazio_no_settings(settings_isolado):
    # valor "" no settings também é ignorado -> cai no default
    settings_isolado.write_text(json.dumps({"aba": ""}), encoding="utf-8")
    assert config.get("aba") == config.DEFAULTS["aba"]


def test_get_settings_corrompido_cai_no_default(settings_isolado):
    # JSON inválido não pode derrubar o app — _load engole e devolve {}
    settings_isolado.write_text("{ isso não é json", encoding="utf-8")
    assert config.get("aba") == config.DEFAULTS["aba"]


def test_set_many_persiste_e_cria_pasta(tmp_path, monkeypatch):
    # aponta pra subpasta inexistente: set_many deve criá-la
    sub = tmp_path / "nao_existe_ainda"
    monkeypatch.setattr(config, "SETTINGS_DIR", str(sub))
    monkeypatch.setattr(config, "SETTINGS_PATH", str(sub / "settings.json"))

    config.set_many({"aba": "NFFs_v2", "header_linha": 9})

    salvo = json.loads((sub / "settings.json").read_text(encoding="utf-8"))
    assert salvo == {"aba": "NFFs_v2", "header_linha": 9}


def test_set_many_ignora_none_e_faz_merge(settings_isolado):
    settings_isolado.write_text(json.dumps({"aba": "original"}), encoding="utf-8")
    config.set_many({"aba": None, "header_linha": 12})
    salvo = json.loads(settings_isolado.read_text(encoding="utf-8"))
    # aba=None foi ignorado (preserva o original); header_linha foi adicionado
    assert salvo == {"aba": "original", "header_linha": 12}


def test_como_dict_cobre_todas_as_chaves(settings_isolado):
    snap = config.como_dict()
    assert set(snap.keys()) == set(config.DEFAULTS.keys())
