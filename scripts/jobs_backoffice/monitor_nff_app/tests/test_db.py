"""Testes de db.py — camada SQLite de controle de NFFs.

Toda função usa config.get("db_path") pra achar o banco. Aqui a gente aponta
esse caminho pra um arquivo em tmp_path (via env var MONITOR_NFF_DB_PATH, que
tem prioridade máxima na cascata do config), então cada teste roda contra um
banco descartável e isolado — sem tocar no controle_nff.db real do usuário.
"""
import pytest

import db


@pytest.fixture
def db_isolado(tmp_path, monkeypatch):
    """Banco SQLite descartável + tabela criada."""
    caminho = tmp_path / "controle_nff.db"
    monkeypatch.setenv("MONITOR_NFF_DB_PATH", str(caminho))
    db.init_db()
    return caminho


def test_init_db_cria_pasta_e_tabela(tmp_path, monkeypatch):
    # caminho aponta pra subpasta inexistente: conn_ctx deve criá-la
    caminho = tmp_path / "sub" / "nova" / "controle_nff.db"
    monkeypatch.setenv("MONITOR_NFF_DB_PATH", str(caminho))
    db.init_db()
    assert caminho.exists()
    assert db.total_registros() == 0


def test_inserir_nffs_retorna_inseridas(db_isolado):
    inseridas = db.inserir_nffs(["NFF-1", "NFF-2", "NFF-3"], "2026-06-25T10:00:00")
    assert sorted(inseridas) == ["NFF-1", "NFF-2", "NFF-3"]
    assert db.total_registros() == 3


def test_inserir_nffs_ignora_duplicadas(db_isolado):
    db.inserir_nffs(["NFF-1", "NFF-2"], "2026-06-25T10:00:00")
    # NFF-1 já existe; só NFF-3 é nova. O INSERT OR IGNORE não conta a duplicada.
    inseridas = db.inserir_nffs(["NFF-1", "NFF-3"], "2026-06-25T11:00:00")
    assert inseridas == ["NFF-3"]
    assert db.total_registros() == 3


def test_inserir_duplicada_nao_sobrescreve_data_envio(db_isolado):
    db.inserir_nffs(["NFF-1"], "2026-06-25T10:00:00")
    db.inserir_nffs(["NFF-1"], "2026-06-25T23:59:59")
    # OR IGNORE preserva o registro original — data_envio não muda
    assert db.buscar("NFF-1")["data_envio"] == "2026-06-25T10:00:00"


def test_buscar_existente_e_inexistente(db_isolado):
    db.inserir_nffs(["NFF-42"], "2026-06-25T10:00:00")
    achada = db.buscar("NFF-42")
    assert achada == {"numero_nff": "NFF-42", "data_envio": "2026-06-25T10:00:00"}
    assert db.buscar("NFF-NAO-EXISTE") is None


def test_nffs_existentes_retorna_set(db_isolado):
    db.inserir_nffs(["A", "B", "C"], "2026-06-25T10:00:00")
    existentes = db.nffs_existentes()
    assert existentes == {"A", "B", "C"}
    assert isinstance(existentes, set)


def test_listar_todas_ordena_por_data_desc(db_isolado):
    db.inserir_nffs(["antiga"], "2026-06-20T08:00:00")
    db.inserir_nffs(["recente"], "2026-06-25T08:00:00")
    db.inserir_nffs(["media"], "2026-06-22T08:00:00")
    ordem = [r["numero_nff"] for r in db.listar_todas()]
    assert ordem == ["recente", "media", "antiga"]


def test_total_registros_em_banco_vazio(db_isolado):
    assert db.total_registros() == 0
