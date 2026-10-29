"""Testes do job faturamento_parceiros/gera_nff_parceiros.py — monta a aba NFFs
do CreateQuickInvoices a partir dos Débitos de 'contratos completos.xlsx'.

Cobre só a lógica PURA (sem tocar em Excel/xlwings/disco):
  - `_clean`   : sanitização de chars ilegais p/ Excel
  - `_digitos` : extrai só dígitos (CNPJ -> díg.)
  - `_vazio`   : detecção de célula vazia (p/ contagem de pendências)
  - `_norm_un` : normaliza nome de Unidade p/ casar no de/para
  - `resolver_unidade` : PAGADOR -> valor da LOV do Oracle (+ registra não-mapeados)
  - `resolver_fornecedor` : FORNECEDOR -> Número do Fornecedor / ID Oracle (+ registra não-mapeados)
  - `resolver_nome_fornecedor` : FORNECEDOR -> grafia do cadastro do Oracle (col L)
  - `mapear_colunas`   : texto do cabeçalho (linha 8) -> índice da coluna
  - `montar_registros` : linhas de Débito -> 1 dict por NFF (o de/para inteiro)

O I/O (`ler_debitos`, `achar_destino`, `gravar`, `desbloquear_motw`,
`_achar_book_aberto`, `relatorio`, `main`) fica fora do escopo unitário — só roda
sob `if __name__ == "__main__"` / depende de Excel aberto.
"""
from datetime import date

import pytest

from testkit import load_job

job = load_job("faturamento_parceiros/gera_nff_parceiros.py", "gera_nff_parceiros")


# ---------------------------------------------------------------------------
# _clean
# ---------------------------------------------------------------------------

def test_clean_remove_chars_controle():
    assert job._clean("abc\x00\x07def") == "abcdef"


def test_clean_remove_zero_width_e_bom():
    assert job._clean("a​b‍c﻿") == "abc"


def test_clean_normaliza_nbsp_e_faz_strip():
    # \xa0 (NBSP) vira espaço comum; bordas sofrem strip
    assert job._clean("  a\xa0b  ") == "a b"


def test_clean_preserva_nao_string():
    assert job._clean(42) == 42
    assert job._clean(None) is None


# ---------------------------------------------------------------------------
# _digitos
# ---------------------------------------------------------------------------

def test_digitos_extrai_so_digitos_do_cnpj():
    assert job._digitos("30.997.588/0010-51 ") == "30997588001051"


def test_digitos_none_e_vazio_viram_none():
    assert job._digitos(None) is None
    assert job._digitos("") is None


def test_digitos_texto_sem_digito_vira_none():
    assert job._digitos("sem numero") is None


def test_digitos_aceita_valor_numerico():
    assert job._digitos(12345) == "12345"


# ---------------------------------------------------------------------------
# _vazio
# ---------------------------------------------------------------------------

def test_vazio_reconhece_none_e_string_em_branco():
    assert job._vazio(None) is True
    assert job._vazio("") is True
    assert job._vazio("   ") is True


def test_vazio_falso_para_conteudo_e_numeros():
    assert job._vazio("x") is False
    assert job._vazio(0) is False      # zero NÃO é vazio (é valor de NFF válido)


# ---------------------------------------------------------------------------
# _norm_un  (tira acento, caixa, pontuação/sufixo)
# ---------------------------------------------------------------------------

def test_norm_un_tira_acento_e_sobe_caixa():
    assert job._norm_un("Consórcio Serena GD 1") == "CONSORCIO SERENA GD 1"


def test_norm_un_colapsa_espacos():
    assert job._norm_un("  SERENA   GERACAO  ") == "SERENA GERACAO"


def test_norm_un_ignora_ponto_final_e_espaco():
    # com e sem ponto final caem na MESMA chave (S.A / S.A.)
    assert job._norm_un("Serena Geração S.A") == job._norm_un("Serena Geração S.A.")


def test_norm_un_none_vira_string_vazia():
    assert job._norm_un(None) == ""


# ---------------------------------------------------------------------------
# resolver_unidade  (de/para PAGADOR -> LOV do Oracle)
# ---------------------------------------------------------------------------

def test_resolver_unidade_casa_apesar_de_acento_e_caixa():
    nao_map = set()
    assert job.resolver_unidade("consórcio serena gd 1", nao_map) == "6001-CONSORCIO SERENA GD 1"
    assert nao_map == set()


def test_resolver_unidade_codigo_nao_sequencial():
    # a pegadinha: GD 9 = 6101 (não 6081), GD 12 = 6091 — vêm da aba _ADFDI_LOV
    nao_map = set()
    assert job.resolver_unidade("CONSÓRCIO SERENA GD 9", nao_map) == "6101-CONSORCIO SERENA GD 9"
    assert job.resolver_unidade("CONSÓRCIO SERENA GD 12", nao_map) == "6091-CONSORCIO SERENA GD 12"


def test_resolver_unidade_sufixo_sa_com_ponto():
    nao_map = set()
    assert job.resolver_unidade("Serena Geração S.A.", nao_map) == "1001-SERENA GERACAO"


def test_resolver_unidade_desconhecido_mantem_nome_e_registra():
    nao_map = set()
    assert job.resolver_unidade("  Consórcio Fantasma  ", nao_map) == "Consórcio Fantasma"
    assert nao_map == {"Consórcio Fantasma"}


def test_resolver_unidade_vazio_nao_polui_nao_mapeados():
    nao_map = set()
    assert job.resolver_unidade("", nao_map) == ""
    assert job.resolver_unidade(None, nao_map) is None
    assert nao_map == set()


# ---------------------------------------------------------------------------
# resolver_fornecedor  (de/para FORNECEDOR -> Número do Fornecedor / ID Oracle)
# ---------------------------------------------------------------------------

def test_resolver_fornecedor_casa_apesar_de_acento_caixa_sufixo():
    # acento/caixa/ponto do sufixo não importam (chaves normalizadas por _norm_un)
    nao_map = set()
    assert job.resolver_fornecedor("serena geração s.a.", nao_map) == "91495030"
    assert nao_map == set()


def test_resolver_fornecedor_desconhecido_retorna_none_e_registra():
    # sem de/para: col M fica em branco (None) e o fornecedor entra em nao_mapeados
    nao_map = set()
    assert job.resolver_fornecedor("  Fornecedor Fantasma  ", nao_map) is None
    assert nao_map == {"Fornecedor Fantasma"}


def test_resolver_fornecedor_vazio_nao_polui_nao_mapeados():
    nao_map = set()
    assert job.resolver_fornecedor("", nao_map) is None
    assert job.resolver_fornecedor(None, nao_map) is None
    assert nao_map == set()


# ---------------------------------------------------------------------------
# mapear_colunas  (texto do cabeçalho -> índice; 1ª ocorrência vence)
# ---------------------------------------------------------------------------

def test_mapear_colunas_indice_1_based_na_ordem_do_cabecalho():
    headers = list(job.DST_HEADERS.values())
    mapa = job.mapear_colunas(headers)
    assert mapa["id_cabecalho"] == 1
    assert mapa["unidade_negocio"] == 2
    assert len(mapa) == len(job.DST_HEADERS)


def test_mapear_colunas_primeira_ocorrencia_vence():
    # 'Descrição' aparece 2x na aba real (cabeçalho e linha); a 1ª (Q) deve vencer
    headers = ["Descrição"] + list(job.DST_HEADERS.values())
    mapa = job.mapear_colunas(headers)
    assert mapa["descricao"] == 1


def test_mapear_colunas_ignora_none_mas_conta_a_coluna():
    # None é pulado como texto, mas ainda ocupa uma posição (enumerate start=1)
    headers = [None] + list(job.DST_HEADERS.values())
    mapa = job.mapear_colunas(headers)
    assert mapa["id_cabecalho"] == 2


def test_mapear_colunas_erro_quando_falta_cabecalho():
    headers = list(job.DST_HEADERS.values())[:-1]   # remove 'Combinação de Distribuição'
    with pytest.raises(ValueError, match="não encontrados"):
        job.mapear_colunas(headers)


# ---------------------------------------------------------------------------
# montar_registros  (o de/para inteiro: 1 dict por NFF)
# ---------------------------------------------------------------------------

# idx = campo -> posição na linha de origem (ordem arbitrária, como faz ler_debitos)
IDX = {
    "pagador": 0, "nota": 1, "valor": 2, "fornecedor": 3,
    "cnpj": 4, "descricao": 5, "charge": 6, "tipo_nota": 7,
}


def _row(pagador="CONSÓRCIO SERENA GD 1", nota="NF-123", valor=1000.0,
         fornecedor="Fornecedor X", cnpj="30.997.588/0010-51",
         descricao="Serviço Y", charge="1234-5678", tipo_nota="Débito"):
    return (pagador, nota, valor, fornecedor, cnpj, descricao, charge, tipo_nota)


def test_montar_registros_de_para_completo():
    hoje = date(2026, 7, 3)
    # fornecedor mapeado no de/para -> col M vem preenchida e nada cai em não-mapeados
    registros, sem_valor, sem_nota, nao_map, nao_map_forn = job.montar_registros(
        IDX, [_row(fornecedor="Serena Geração S.A.")], hoje)

    assert (sem_valor, sem_nota, nao_map, nao_map_forn) == (0, 0, set(), set())
    assert registros == [{
        "id_cabecalho": 1,
        "unidade_negocio": "6001-CONSORCIO SERENA GD 1",
        "numero_nff": "NF-123",
        "moeda_nff": "BRL",
        "valor_nff": 1000.0,
        "data_nff": hoje,
        "fornecedor": "SERENA GERACAO S.A",  # grafia do Oracle via de/para (col L)
        "numero_fornecedor": "91495030",   # ID Oracle via de/para (col M)
        "local_fornecedor": "30997588001051",
        "moeda_pgto": "BRL",
        "tipo_nff": "Padrão",            # NÃO "Standard"
        "descricao": "Serviço Y",
        "cond_pgto": "Imediato",
        "data_cond": hoje,               # hoje entra em data_nff E data_cond
        "grupo_pgto": "Método Direto",
        "tipo_linha": "Item",
        "valor_linha": 1000.0,
        "combinacao_dist": "1234-5678",
    }]


def test_montar_registros_numero_fornecedor_vem_do_de_para():
    # col M ('Número do Fornecedor'): ID Oracle quando há de/para, None quando não há
    registros, _, _, _, nao_map_forn = job.montar_registros(
        IDX,
        [_row(fornecedor="ATHON GERACAO DISTRIBUIDA S/A"), _row(fornecedor="Fornecedor X")],
        date(2026, 7, 3),
    )
    assert registros[0]["numero_fornecedor"] == "16511"   # mapeado
    assert registros[1]["numero_fornecedor"] is None      # sem de/para -> col M em branco
    assert nao_map_forn == {"Fornecedor X"}               # não-mapeado é registrado p/ o aviso


def test_montar_registros_nome_fornecedor_sai_na_grafia_do_oracle():
    # col L ('Fornecedor'): a origem escreve sem o ponto final e com caixa/acento
    # variados; o Oracle só aceita a grafia do cadastro dele. Era o ajuste que a
    # Neiva fazia na mão, linha a linha, a cada geração.
    registros, *_ = job.montar_registros(
        IDX,
        [_row(fornecedor="athon geracao distribuida ii s.a"),   # sem o ponto final
         _row(fornecedor="Sol Go Cezarina Ltda"),               # Oracle tem "LTDA."
         _row(fornecedor="Fornecedor X")],                      # sem de/para
        date(2026, 7, 3),
    )
    assert registros[0]["fornecedor"] == "ATHON GERACAO DISTRIBUIDA II S.A."
    assert registros[1]["fornecedor"] == "SOL GO CEZARINA LTDA."
    assert registros[2]["fornecedor"] == "Fornecedor X"   # sem de/para: sai como veio


def test_montar_registros_fornecedor_casa_nas_duas_grafias_da_origem():
    # EMANA e SUNO divergem entre origem e Oracle num sufixo que _norm_un não remove
    # (só tira pontuação do FIM), por isso as duas grafias são chaves do de/para.
    registros, _, _, _, nao_map_forn = job.montar_registros(
        IDX,
        [_row(fornecedor="EMANA PIAUI LOCACAO DE EQUIPAMENTOS LTDA"),
         _row(fornecedor="EMANA PIAUI LOCACAO DE EQUIPAMENTOS LTDA EPP"),
         _row(fornecedor="SUNO ENERGIAS LIMPAS FUNDO DE INVESTIMENTO IMOBILIARIO IS")],
        date(2026, 7, 3),
    )
    assert [r["numero_fornecedor"] for r in registros] == ["15244", "15244", "17490"]
    assert registros[0]["fornecedor"] == registros[1]["fornecedor"] == \
        "EMANA PIAUI LOCACAO DE EQUIPAMENTOS LTDA EPP"
    assert registros[2]["fornecedor"].endswith("RESPONSABILIDADE LIMITADA")
    assert nao_map_forn == set()


def test_montar_registros_id_cabecalho_incrementa():
    rows = [_row(nota="A"), _row(nota="B"), _row(nota="C")]
    registros, *_ = job.montar_registros(IDX, rows, date(2026, 7, 3))
    assert [r["id_cabecalho"] for r in registros] == [1, 2, 3]


def test_montar_registros_conta_sem_valor_e_sem_nota():
    rows = [_row(valor=None, nota=""), _row(valor=50.0, nota="NF-1")]
    _, sem_valor, sem_nota, _, _ = job.montar_registros(IDX, rows, date(2026, 7, 3))
    assert (sem_valor, sem_nota) == (1, 1)


def test_montar_registros_pagador_desconhecido_vai_para_nao_mapeados():
    rows = [_row(pagador="Consórcio Fantasma")]
    registros, _, _, nao_map, _ = job.montar_registros(IDX, rows, date(2026, 7, 3))
    assert registros[0]["unidade_negocio"] == "Consórcio Fantasma"
    assert nao_map == {"Consórcio Fantasma"}
