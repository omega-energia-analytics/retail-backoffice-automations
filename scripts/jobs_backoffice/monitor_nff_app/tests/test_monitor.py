"""Testes dos helpers puros de monitor.py.

Cobre os helpers extraídos pro nível do módulo: `_to_naive`, `_fmt_uc`,
`_status` e `_dias_para_vencer`. `consultar_faturas()` em si bate em
Snowflake/Graph (rede + VPN), então fica fora do escopo de teste unitário.
"""
from datetime import date, datetime

import pandas as pd
from pandas import Timestamp

import monitor


def test_to_naive_remove_timezone():
    # regressão: AP_ORACLE_VIEW passou a devolver TIMESTAMP com fuso; sem normalizar,
    # a comparação com o mês corrente (tz-naive) quebra.
    s = pd.Series(["2026-06-25T10:00:00+03:00", "2026-06-26T12:00:00+03:00"])
    out = monitor._to_naive(s)
    assert getattr(out.dtype, "tz", None) is None
    assert out.iloc[0] == Timestamp("2026-06-25 10:00:00")


def test_to_naive_sem_timezone_passa_direto():
    s = pd.Series(["2026-06-25", "2026-06-26"])
    out = monitor._to_naive(s)
    assert out.iloc[0] == Timestamp("2026-06-25")
    assert getattr(out.dtype, "tz", None) is None


def test_to_naive_dayfirst_interpreta_dd_mm_yyyy():
    s = pd.Series(["03/04/2026"])  # 3 de abril, não 4 de março
    out = monitor._to_naive(s, dayfirst=True)
    assert out.iloc[0] == Timestamp("2026-04-03")


def test_to_naive_valor_invalido_vira_nat():
    s = pd.Series(["", "lixo", None])
    out = monitor._to_naive(s)
    # errors='coerce' -> tudo NaT, sem levantar exceção
    assert out.isna().all()


def test_to_naive_misto_valido_e_invalido():
    s = pd.Series(["2026-06-25", "lixo"])
    out = monitor._to_naive(s)
    assert out.iloc[0] == Timestamp("2026-06-25")
    assert pd.isna(out.iloc[1])


def test_to_naive_formatos_iso_misturados():
    """Regressão da causa raiz: a AP_ORACLE_VIEW mistura '2026-05-04 11:31:08'
    (até ~maio/26) com '2026-07-21T00:00:00Z' (daí em diante) na MESMA coluna.

    `pd.to_datetime` sem format infere o padrão da primeira linha e coage o resto
    para NaT — todo pagamento recente sumia e a fatura virava 'A pagar'.
    """
    s = pd.Series([
        "2026-04-08 12:33:20",   # formato antigo
        "2026-05-04 11:31:08",   # formato antigo
        "2026-06-04T01:00:22Z",  # formato novo (virava NaT)
        "2026-07-21T00:00:00Z",  # formato novo (virava NaT)
    ])
    out = monitor._to_naive(s)
    assert out.notna().all(), f"NaT indevido: {out.tolist()}"
    assert out.iloc[0] == Timestamp("2026-04-08 12:33:20")
    assert out.iloc[3] == Timestamp("2026-07-21 00:00:00")
    assert getattr(out.dtype, "tz", None) is None

    # prova que o bug existia: o parse ingênuo perde as duas últimas
    ingenuo = pd.to_datetime(s, errors="coerce")
    assert int(ingenuo.isna().sum()) == 2


def test_to_naive_dayfirst_continua_mandando():
    """A segunda passada não pode roubar as datas brasileiras do fattureweb:
    '03/04/2026' com dayfirst=True é 3 de abril, não 4 de março."""
    out = monitor._to_naive(pd.Series(["03/04/2026", "25/12/2025"]), dayfirst=True)
    assert out.iloc[0] == Timestamp("2026-04-03")
    assert out.iloc[1] == Timestamp("2025-12-25")


def test_to_naive_lixo_continua_nat():
    out = monitor._to_naive(pd.Series(["", None, "lixo", "2026-07-21T00:00:00Z"]))
    assert out.iloc[:3].isna().all()
    assert out.iloc[3] == Timestamp("2026-07-21")


# ---------------------------------------------------------------------------
# _fmt_uc — normalização da Unidade Consumidora
# ---------------------------------------------------------------------------

def test_fmt_uc_remove_ponto_zero_de_float():
    # UC chega como float "12345.0" -> vira "12345"
    assert monitor._fmt_uc(12345.0) == "12345"
    assert monitor._fmt_uc("12345.0") == "12345"


def test_fmt_uc_preserva_string_normal():
    assert monitor._fmt_uc("UC-987") == "UC-987"
    assert monitor._fmt_uc("  12345  ") == "12345"  # faz strip


def test_fmt_uc_nan_vira_none():
    assert monitor._fmt_uc(float("nan")) is None
    assert monitor._fmt_uc(None) is None


# ---------------------------------------------------------------------------
# _fmt_nf — normalização da chave de merge por nota fiscal
# ---------------------------------------------------------------------------

def test_fmt_nf_nulos_viram_nan_e_nao_casam_no_merge():
    # regressão: `.astype(str)` transformava NULL em 'None' e vazio em '', e essas
    # strings casavam entre si no merge, cruzando notas que não têm nada a ver.
    s = monitor._fmt_nf(pd.Series(["123", None, "", "  ", float("nan")]))
    assert s.iloc[0] == "123"
    assert s.iloc[1:].isna().all()


def test_fmt_nf_tira_nulos_da_tabela_de_lookup():
    """O que impede o cruzamento fantasma é o groupby: chave NaN não forma grupo,
    então a linha sem nota some da tabela de lookup e nunca chega ao merge.

    Com `.astype(str)` (comportamento antigo) o NULL virava a string 'None', que
    É uma chave válida — sobrevivia ao dedup e casava com qualquer outra 'None'
    do outro lado. Atenção: o merge do pandas casa NaN com NaN, então normalizar
    sozinho não bastaria; é a eliminação no dedup que resolve.
    """
    bruto = pd.DataFrame({
        "NOTA_FISCAL": ["123", None, ""],
        "DATA": pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
    })

    antigo = bruto.assign(NOTA_FISCAL=bruto["NOTA_FISCAL"].astype(str).str.strip())
    antigo = antigo.sort_values("DATA", na_position="first").groupby(
        "NOTA_FISCAL", as_index=False).tail(1)
    assert "None" in set(antigo["NOTA_FISCAL"])  # chave lixo sobrevivia

    novo = bruto.assign(NOTA_FISCAL=monitor._fmt_nf(bruto["NOTA_FISCAL"]))
    novo = novo.sort_values("DATA", na_position="first").groupby(
        "NOTA_FISCAL", as_index=False).tail(1)
    assert set(novo["NOTA_FISCAL"]) == {"123"}  # só a nota real resta


def test_fmt_nf_faz_strip():
    assert monitor._fmt_nf(pd.Series(["  456  "])).iloc[0] == "456"


# ---------------------------------------------------------------------------
# _nf_key / _completar_por_chave_normalizada — 2º passe de chave da nota
# ---------------------------------------------------------------------------

def test_nf_key_trata_ponto_zero_e_zero_a_esquerda_como_mesma_nota():
    # a NFF passa por float em algum ponto ('.0') e a CPFL usa 9 dígitos com zero
    # à esquerda — as três grafias são a MESMA nota
    k = monitor._nf_key(pd.Series(["42937901.0", "042937901", "42937901"]))
    assert set(k) == {"42937901"}


def test_nf_key_descarta_chave_inutil():
    k = monitor._nf_key(pd.Series([None, "", "  ", "000", "0.0"]))
    assert k.isna().all()


def test_nf_key_preserva_nota_nao_numerica():
    assert monitor._nf_key(pd.Series(["NF-123"])).iloc[0] == "NF-123"


def _fonte_pag(linhas):
    """Fonte de pagamento (formato do df_pag): NOTA_FISCAL + DATA_DE_PAGAMENTO."""
    df = pd.DataFrame(linhas, columns=["NOTA_FISCAL", "DATA_DE_PAGAMENTO"])
    df["DATA_DE_PAGAMENTO"] = pd.to_datetime(df["DATA_DE_PAGAMENTO"], errors="coerce")
    return df


def _alvo(linhas):
    """Alvo (formato do df_merged pós-merge exato)."""
    df = pd.DataFrame(linhas, columns=["NOTA_FISCAL", "DATA_DE_PAGAMENTO"])
    df["DATA_DE_PAGAMENTO"] = pd.to_datetime(df["DATA_DE_PAGAMENTO"], errors="coerce")
    return df


def test_completar_acha_pagamento_com_grafia_diferente():
    # monitoramento tem '42937901', Oracle tem '042937901' -> merge exato não casou
    df = _alvo([["42937901", None]])
    n, amb = monitor._completar_por_chave_normalizada(
        df, _fonte_pag([["042937901", "2026-06-11"]]), ["DATA_DE_PAGAMENTO"])
    assert n == 1 and amb == 0
    assert df.loc[0, "DATA_DE_PAGAMENTO"] == Timestamp("2026-06-11")


def test_completar_nao_sobrescreve_valor_existente():
    """Aditividade: linha que já casou no merge exato sai IDÊNTICA, mesmo que a
    chave normalizada aponte para outra data."""
    df = _alvo([["42937901", "2026-06-20"]])
    n, _ = monitor._completar_por_chave_normalizada(
        df, _fonte_pag([["042937901", "2026-06-11"]]), ["DATA_DE_PAGAMENTO"])
    assert n == 0
    assert df.loc[0, "DATA_DE_PAGAMENTO"] == Timestamp("2026-06-20")


def test_completar_descarta_chave_ambigua():
    """Duas notas de origem informativas com a mesma chave normalizada: não dá pra
    saber qual é a do projeto. Ficar sem pagamento é melhor que mostrar o de outra."""
    df = _alvo([["194412037", None]])
    n, amb = monitor._completar_por_chave_normalizada(
        df,
        _fonte_pag([["194412037", "2026-06-16"], ["194412037.0", "2026-06-11"]]),
        ["DATA_DE_PAGAMENTO"],
    )
    assert (n, amb) == (0, 1)
    assert pd.isna(df.loc[0, "DATA_DE_PAGAMENTO"])


def test_completar_desempata_ignorando_fonte_sem_informacao():
    """Caso real GO-MNU-01: no Oracle existem '194412037' (nota Cancelada, sem
    pagamento) e '194412037.0' (a paga). A linha que não informa nada não disputa a
    chave, então ela deixa de ser ambígua e o pagamento certo é encontrado."""
    df = _alvo([["194412037", None]])
    n, amb = monitor._completar_por_chave_normalizada(
        df,
        _fonte_pag([["194412037", None], ["194412037.0", "2026-06-16"]]),
        ["DATA_DE_PAGAMENTO"],
    )
    assert (n, amb) == (1, 0)
    assert df.loc[0, "DATA_DE_PAGAMENTO"] == Timestamp("2026-06-16")


def test_completar_com_fonte_vazia_nao_quebra():
    # degrau desligado (view sem as colunas novas) -> df_inst vem vazio
    df = _alvo([["42937901", None]])
    n, amb = monitor._completar_por_chave_normalizada(
        df, _fonte_pag([]), ["DATA_DE_PAGAMENTO"])
    assert (n, amb) == (0, 0)
    assert pd.isna(df.loc[0, "DATA_DE_PAGAMENTO"])


def test_completar_ignora_nota_nula_no_alvo():
    df = _alvo([[None, None], ["42937901", None]])
    n, _ = monitor._completar_por_chave_normalizada(
        df, _fonte_pag([["042937901", "2026-06-11"]]), ["DATA_DE_PAGAMENTO"])
    assert n == 1
    assert pd.isna(df.loc[0, "DATA_DE_PAGAMENTO"])
    assert df.loc[1, "DATA_DE_PAGAMENTO"] == Timestamp("2026-06-11")


# ---------------------------------------------------------------------------
# desempate de duplicatas por nota (na_position)
# ---------------------------------------------------------------------------

def test_dedup_por_nota_mantem_linha_com_data_e_nao_a_nula():
    """Regressão: a mesma nota tinha 2 linhas (uma com data, outra sem) e o
    `sort_values(...).tail(1)` elegia a SEM data, porque o pandas joga NaT pro
    fim por default. Resultado: apresentação/pagamento sumiam e o Status ficava
    errado. Com na_position='first' a linha preenchida sobrevive.
    """
    df = pd.DataFrame({
        "NOTA_FISCAL": ["111", "111", "222"],
        "DATA": pd.to_datetime([None, "2026-06-10", "2026-06-11"]),
    })
    out = (
        df.sort_values("DATA", na_position="first")
          .groupby("NOTA_FISCAL", as_index=False)
          .tail(1)
          .set_index("NOTA_FISCAL")
    )
    assert out.loc["111", "DATA"] == Timestamp("2026-06-10")
    assert out.loc["222", "DATA"] == Timestamp("2026-06-11")

    # e continua elegendo a MAIS RECENTE quando as duas têm data
    df2 = pd.DataFrame({
        "NOTA_FISCAL": ["111", "111"],
        "DATA": pd.to_datetime(["2026-06-01", "2026-06-20"]),
    })
    out2 = (
        df2.sort_values("DATA", na_position="first")
           .groupby("NOTA_FISCAL", as_index=False)
           .tail(1)
    )
    assert out2.iloc[0]["DATA"] == Timestamp("2026-06-20")


# ---------------------------------------------------------------------------
# _status — classificação da fatura no mês
# ---------------------------------------------------------------------------

HOJE = date(2026, 6, 25)


def _row(chegada, esperada):
    """Monta uma linha como o consultar_faturas monta antes do apply."""
    return pd.Series({
        "Data Chegada": pd.NaT if chegada is None else Timestamp(chegada),
        "Data Esperada": Timestamp(esperada),
    })


def test_status_chegou_no_prazo():
    # chegou no mesmo dia esperado (<=) -> Chegou
    assert monitor._status(_row("2026-06-20", "2026-06-20"), HOJE) == "Chegou"
    assert monitor._status(_row("2026-06-18", "2026-06-20"), HOJE) == "Chegou"


def test_status_chegou_atrasada():
    # chegou depois da data esperada
    assert monitor._status(_row("2026-06-22", "2026-06-20"), HOJE) == "Chegou atrasada"


def test_status_pendente_dentro_do_prazo():
    # não chegou, mas a data esperada ainda não passou (>= hoje) -> Pendente
    assert monitor._status(_row(None, "2026-06-28"), HOJE) == "Pendente"
    assert monitor._status(_row(None, "2026-06-25"), HOJE) == "Pendente"  # hoje conta


def test_status_atrasada_quando_prazo_passou():
    # não chegou e a data esperada já passou
    assert monitor._status(_row(None, "2026-06-20"), HOJE) == "Atrasada"


# ---------------------------------------------------------------------------
# _dias_para_vencer
# ---------------------------------------------------------------------------

def test_dias_para_vencer_futuro_positivo():
    assert monitor._dias_para_vencer(_row(None, "2026-06-28"), HOJE) == 3


def test_dias_para_vencer_passado_negativo():
    assert monitor._dias_para_vencer(_row(None, "2026-06-20"), HOJE) == -5


def test_dias_para_vencer_none_se_ja_chegou():
    assert monitor._dias_para_vencer(_row("2026-06-22", "2026-06-20"), HOJE) is None


# ---------------------------------------------------------------------------
# montar_mes / listar_meses — recorte de mês (parte pura, sem rede)
# ---------------------------------------------------------------------------

HOJE_JUL = datetime(2026, 7, 21)  # "estamos em julho", cenário da demanda


def _df_projetos(linhas):
    """linhas: [(Projeto, ACRONIMO, Distribuidora, Dia, Forma)]"""
    return pd.DataFrame(
        linhas, columns=['Projeto', 'ACRONIMO', 'Distribuidora', 'Dia', 'Forma Recebimento']
    )


def _df_merged(linhas):
    """linhas: dicts com ACRONIMO/NOTA_FISCAL/DATA_REFERENCIA/DATA_DE_PAGAMENTO/PAGAMENTO/UC."""
    df = pd.DataFrame(
        linhas,
        columns=['ACRONIMO', 'NOTA_FISCAL', 'DATA_REFERENCIA', 'DATA_DE_PAGAMENTO', 'PAGAMENTO', 'UC']
    )
    for c in ('DATA_REFERENCIA', 'DATA_DE_PAGAMENTO', 'PAGAMENTO'):
        df[c] = pd.to_datetime(df[c], errors='coerce')
    return df


def _por_acronimo(records):
    return {r['ACRONIMO']: r for r in records}


def test_montar_mes_recorta_o_mes_escolhido():
    # regressão da demanda: em julho, conseguir ver a fatura de junho.
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-05', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '123'},
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '222', 'DATA_REFERENCIA': '2026-07-05', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '123'},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    jul = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 7, hoje=HOJE_JUL))
    assert jun['A-01']['NFF'] == '111'
    assert jul['A-01']['NFF'] == '222'


def test_montar_mes_data_esperada_relativa_ao_mes_escolhido():
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 15, 'FW')])
    jun = _por_acronimo(monitor.montar_mes(_df_merged([]), projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Data Esperada'] == '15/06/2026'  # e não 15/07


def test_montar_mes_default_e_mes_corrente():
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 15, 'FW')])
    r = _por_acronimo(monitor.montar_mes(_df_merged([]), projetos, hoje=HOJE_JUL))
    assert r['A-01']['Data Esperada'] == '15/07/2026'


def test_montar_mes_fatura_passada_no_prazo_fica_chegou():
    # chegou 08/06, esperada 10/06 -> Chegou, mesmo hoje sendo julho
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1'},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Status'] == 'Chegou'


def test_montar_mes_sem_fatura_no_mes_passado_fica_atrasada():
    # esperada 10/06 já passou (hoje 21/07) e nada chegou -> Atrasada
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    jun = _por_acronimo(monitor.montar_mes(_df_merged([]), projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Status'] == 'Atrasada'
    assert jun['A-01']['NFF'] is None


def test_montar_mes_mes_vazio_nao_quebra():
    # blindagem: mês sem nenhuma fatura não pode estourar no .dt.strftime
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    r = _por_acronimo(monitor.montar_mes(_df_merged([]), projetos, 2026, 7, hoje=HOJE_JUL))
    assert r['A-01']['Data Chegada'] is None
    assert not r['A-01']['Pago']


def test_montar_mes_pago_por_qualquer_fonte():
    projetos = _df_projetos([
        ('Usina A', 'A-01', 'CPFL', 10, 'FW'),
        ('Usina B', 'B-01', 'COELBA', 10, 'E-MAIL'),
    ])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-05', 'DATA_DE_PAGAMENTO': '2026-06-20', 'PAGAMENTO': None, 'UC': '1'},
        {'ACRONIMO': 'B-01', 'NOTA_FISCAL': '222', 'DATA_REFERENCIA': '2026-06-06', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': '2026-06-22', 'UC': '2'},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Pago']
    assert jun['A-01']['Data Pagamento'] == '20/06/2026'
    assert jun['B-01']['Pago']
    assert jun['B-01']['Data Pagamento'] == '22/06/2026'


# ---------------------------------------------------------------------------
# _depara_uc_por_endereco — resgata UC que trocou de código na distribuidora
# ---------------------------------------------------------------------------

def _uc_end(pares):
    """pares: [(UC, ENDERECO)]"""
    return pd.DataFrame(pares, columns=['UC', 'ENDERECO'])


def test_depara_endereco_resgata_uc_que_trocou_de_codigo():
    """Caso real: a CPFL migrou a UC da SP-SLU-01 de '4003500102' para
    '556837603586' na competência 06/2026. O endereço não mudou, então a UC nova
    herda o acrônimo da antiga."""
    df = _uc_end([
        ('4003500102',   'CRT 142D, S/N1 TP - TP - STA LUCIA SANTA LUCIA - SP 14825-000'),
        ('556837603586', 'CRT 142D, S/N1 TP - TP - STA LUCIA SANTA LUCIA - SP 14825-000'),
    ])
    novos, amb = monitor._depara_uc_por_endereco(df, {'4003500102': 'SP-SLU-01'})
    assert novos == {'556837603586': 'SP-SLU-01'}
    assert amb == 0


def test_depara_endereco_desambigua_usinas_da_mesma_cidade():
    """Araraquara tem duas usinas; o CRT no endereço separa: 166A é a SP-ARQ-03 e
    166B a SP-ARQ-04. O de/para não pode trocar uma pela outra."""
    df = _uc_end([
        ('4003559327',   'CRT 166A, S/N1 TP - TP - ARARAQUARA ARARAQUARA - SP 14800-870'),
        ('4003530133',   'CRT 166B, S/N1 TP - TP - ARARAQUARA ARARAQUARA - SP 14800-000'),
        ('559670503544', 'CRT 166A, S/N1 TP - TP - ARARAQUARA ARARAQUARA - SP 14800-870'),
        ('558369503568', 'CRT 166B, S/N1 TP - TP - ARARAQUARA ARARAQUARA - SP 14800-000'),
    ])
    novos, amb = monitor._depara_uc_por_endereco(
        df, {'4003559327': 'SP-ARQ-03', '4003530133': 'SP-ARQ-04'})
    assert novos == {'559670503544': 'SP-ARQ-03', '558369503568': 'SP-ARQ-04'}
    assert amb == 0


def test_depara_endereco_descarta_endereco_compartilhado():
    """Salvaguarda 1 (caso real Morro Agudo): SP-ATN-01 e SP-ATN-02 têm o MESMO
    endereço. Não há como saber de qual usina é a fatura — fica de fora."""
    end = 'CRT 060D, S/N1 TP - TP - MRO AGUDO MORRO AGUDO - SP 14640-000'
    df = _uc_end([('4003454946', end), ('4003454904', end), ('554676603556', end)])
    novos, amb = monitor._depara_uc_por_endereco(
        df, {'4003454946': 'SP-ATN-01', '4003454904': 'SP-ATN-02'})
    assert novos == {}
    assert amb == 1


def test_depara_endereco_nao_confunde_pontuacao_diferente():
    """A normalização é leve de propósito: 'TP - TP -' e 'TP TP' são endereços de
    usinas DIFERENTES em Morro Agudo. Achatar pontuação colaria as duas."""
    df = _uc_end([
        ('4003454946',   'CRT 060D, S/N1 TP - TP - MRO AGUDO MORRO AGUDO - SP 14640-000'),
        ('4003454755',   'CRT 060D, S/N1 TP TP MRO AGUDO MORRO AGUDO - SP 14640-000'),
        ('554871803557', 'CRT 060D, S/N1 TP TP MRO AGUDO MORRO AGUDO - SP 14640-000'),
    ])
    novos, amb = monitor._depara_uc_por_endereco(
        df, {'4003454946': 'SP-ATN-01', '4003454755': 'SP-ATN-03'})
    assert novos == {'554871803557': 'SP-ATN-03'}   # e nunca SP-ATN-01
    assert amb == 0


def test_depara_endereco_normaliza_caixa_e_espacos():
    df = _uc_end([
        ('4003500102',   '  crt 142d,   s/n1 sta lucia  '),
        ('556837603586', 'CRT 142D, S/N1 STA LUCIA'),
    ])
    novos, _ = monitor._depara_uc_por_endereco(df, {'4003500102': 'SP-SLU-01'})
    assert novos == {'556837603586': 'SP-SLU-01'}


def test_depara_endereco_descarta_uc_com_enderecos_divergentes():
    """Salvaguarda 2: se os endereços de uma UC órfã levam a acrônimos diferentes,
    não há resposta única — fica de fora."""
    df = _uc_end([
        ('4003500102', 'ENDERECO A'), ('4003559327', 'ENDERECO B'),
        ('999999999999', 'ENDERECO A'), ('999999999999', 'ENDERECO B'),
    ])
    novos, _ = monitor._depara_uc_por_endereco(
        df, {'4003500102': 'SP-SLU-01', '4003559327': 'SP-ARQ-03'})
    assert novos == {}


def test_depara_endereco_ignora_endereco_vazio_e_nao_sobrescreve():
    # endereço vazio não vira chave; UC que já tem acrônimo não é tocada
    df = _uc_end([('4003500102', ''), ('556837603586', None), ('4003559327', 'X')])
    novos, _ = monitor._depara_uc_por_endereco(
        df, {'4003500102': 'SP-SLU-01', '4003559327': 'SP-ARQ-03'})
    assert novos == {}


# ---------------------------------------------------------------------------
# _cascata_datas — DATA_REFERENCIA (de que mês é) vs DATA_CHEGADA (quando chegou)
# ---------------------------------------------------------------------------

def _df_fontes(linhas):
    """Linhas com as 5 fontes de data que alimentam as duas cascatas."""
    cols = ['DATA_DA_APRESENTACAO_DA_FATURA', 'DATA_APRES_FW', 'MES_REF_FW',
            'DATA_EMISSAO_FW', 'DATA_INVOICE']
    df = pd.DataFrame(linhas, columns=cols)
    for c in cols:
        df[c] = pd.to_datetime(df[c], errors='coerce')
    return df


def test_cascata_apresentacao_vence_tudo():
    """CPFL/Equatorial preenchem apresentação: param no 1º degrau nas duas cascatas,
    então nada muda pra elas."""
    df = monitor._cascata_datas(_df_fontes([{
        'DATA_DA_APRESENTACAO_DA_FATURA': '2026-06-08', 'DATA_APRES_FW': '2026-06-09',
        'MES_REF_FW': '2026-05-01', 'DATA_EMISSAO_FW': '2026-06-05',
        'DATA_INVOICE': '2026-07-27',
    }]))
    assert df.loc[0, 'DATA_REFERENCIA'] == Timestamp('2026-06-08')
    assert df.loc[0, 'DATA_CHEGADA'] == Timestamp('2026-06-08')


def test_cascata_competencia_vence_lancamento_contabil_no_mes():
    """Regressão CELPE: sem apresentação em nenhuma fonte, o mês tem que sair da
    COMPETÊNCIA, não do INVOICEDATE (lançamento contábil). Antes a fatura de
    competência 06 caía em julho, junho ficava vazio e virava falso 'Atrasada'."""
    df = monitor._cascata_datas(_df_fontes([{
        'DATA_DA_APRESENTACAO_DA_FATURA': None, 'DATA_APRES_FW': None,
        'MES_REF_FW': '2026-06-01', 'DATA_EMISSAO_FW': '2026-07-10',
        'DATA_INVOICE': '2026-07-13',
    }]))
    assert df.loc[0, 'DATA_REFERENCIA'] == Timestamp('2026-06-01')   # junho, não julho


def test_cascata_chegada_usa_emissao_e_nunca_competencia():
    """A data de chegada tem que ser a EMISSÃO real (10/07), não o dia 1º da
    competência — competência não é data de chegada."""
    df = monitor._cascata_datas(_df_fontes([{
        'DATA_DA_APRESENTACAO_DA_FATURA': None, 'DATA_APRES_FW': None,
        'MES_REF_FW': '2026-06-01', 'DATA_EMISSAO_FW': '2026-07-10',
        'DATA_INVOICE': '2026-07-13',
    }]))
    assert df.loc[0, 'DATA_CHEGADA'] == Timestamp('2026-07-10')
    assert df.loc[0, 'DATA_CHEGADA'] != df.loc[0, 'DATA_REFERENCIA']  # perguntas diferentes


def test_cascata_sem_emissao_cai_no_lancamento():
    df = monitor._cascata_datas(_df_fontes([{
        'DATA_DA_APRESENTACAO_DA_FATURA': None, 'DATA_APRES_FW': None,
        'MES_REF_FW': '2026-06-01', 'DATA_EMISSAO_FW': None, 'DATA_INVOICE': '2026-07-13',
    }]))
    assert df.loc[0, 'DATA_REFERENCIA'] == Timestamp('2026-06-01')
    assert df.loc[0, 'DATA_CHEGADA'] == Timestamp('2026-07-13')


def test_cascata_suplemento_ignora_apresentacao_do_monitoramento():
    # no suplemento FW a coluna do monitoramento existe mas nunca deve ser usada
    df = monitor._cascata_datas(_df_fontes([{
        'DATA_DA_APRESENTACAO_DA_FATURA': '2026-01-01', 'DATA_APRES_FW': None,
        'MES_REF_FW': '2026-06-01', 'DATA_EMISSAO_FW': '2026-07-10',
        'DATA_INVOICE': '2026-07-13',
    }]), com_monitoramento=False)
    assert df.loc[0, 'DATA_REFERENCIA'] == Timestamp('2026-06-01')
    assert df.loc[0, 'DATA_CHEGADA'] == Timestamp('2026-07-10')


def test_cascata_competencias_distintas_nao_empilham_no_mesmo_mes():
    """O empilhamento que fazia fatura DESAPARECER: competências 05 e 06 lançadas as
    duas em julho no Oracle. Pela competência cada uma vai pro seu mês, e o
    groupby(ACRONIMO).tail(1) deixa de descartar uma."""
    df = monitor._cascata_datas(_df_fontes([
        {'DATA_DA_APRESENTACAO_DA_FATURA': None, 'DATA_APRES_FW': None,
         'MES_REF_FW': '2026-05-01', 'DATA_EMISSAO_FW': '2026-06-26', 'DATA_INVOICE': '2026-07-06'},
        {'DATA_DA_APRESENTACAO_DA_FATURA': None, 'DATA_APRES_FW': None,
         'MES_REF_FW': '2026-06-01', 'DATA_EMISSAO_FW': '2026-07-10', 'DATA_INVOICE': '2026-07-13'},
    ]))
    assert df['DATA_REFERENCIA'].dt.month.tolist() == [5, 6]   # antes era [7, 7]


# ---------------------------------------------------------------------------
# Cenários fim-a-fim das CELPE (casos reais de jun/2026)
# ---------------------------------------------------------------------------

def _df_merged_chegada(linhas):
    """df_merged com DATA_REFERENCIA e DATA_CHEGADA separadas."""
    cols = ['ACRONIMO', 'NOTA_FISCAL', 'DATA_REFERENCIA', 'DATA_CHEGADA',
            'DATA_DE_PAGAMENTO', 'PAGAMENTO', 'UC']
    df = pd.DataFrame(linhas, columns=cols)
    for c in ('DATA_REFERENCIA', 'DATA_CHEGADA', 'DATA_DE_PAGAMENTO', 'PAGAMENTO'):
        df[c] = pd.to_datetime(df[c], errors='coerce')
    return df


def test_montar_mes_celpe_paga_aparece_no_mes_em_que_chegou():
    """PE-VEN-01: competência 06/2026, chegou 10/07, paga 14/07, prazo dia 20.

    A aba é por mês de CHEGADA, então a fatura aparece em JULHO — o mês em que a
    Neiva de fato a recebeu — e no prazo (10/07 <= 20/07). Ancorando na competência
    ela caía em junho como 'Chegou atrasada' (10/07 vs 20/06) e julho ficava com uma
    linha 'Atrasada' em branco, apesar de a fatura ter chegado adiantada.
    """
    projetos = _df_projetos([('UFV Venturosa I', 'PE-VEN-01', 'CELPE', 20, 'E-MAIL')])
    merged = _df_merged_chegada([{
        'ACRONIMO': 'PE-VEN-01', 'NOTA_FISCAL': '419547035',
        'DATA_REFERENCIA': '2026-06-01', 'DATA_CHEGADA': '2026-07-10',
        'DATA_DE_PAGAMENTO': '2026-07-14', 'PAGAMENTO': '2026-07-14', 'UC': '8276958',
    }])
    jul = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 7, hoje=HOJE_JUL))['PE-VEN-01']
    assert jul['NFF'] == '419547035'
    assert jul['Data Chegada'] == '10/07/2026'      # e não 01/06 (competência)
    assert jul['Status'] == 'Chegou'                # 10/07 <= 20/07
    assert jul['Pago'] and jul['Data Pagamento'] == '14/07/2026'

    # e junho NÃO fica com a linha fantasma: nada chegou em junho pra essa usina
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))['PE-VEN-01']
    assert jun['NFF'] is None


def test_montar_mes_competencia_fica_visivel_na_coluna():
    """A competência não pode se perder quando a aba passa a ser por chegada: é ela
    que identifica QUAL fatura é a linha e denuncia competência pulada."""
    projetos = _df_projetos([('UFV Venturosa I', 'PE-VEN-01', 'CELPE', 20, 'E-MAIL')])
    merged = _df_merged_chegada([{
        'ACRONIMO': 'PE-VEN-01', 'NOTA_FISCAL': '419547035',
        'DATA_REFERENCIA': '2026-06-01', 'DATA_CHEGADA': '2026-07-10',
        'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '8276958',
    }])
    merged['MES_REF_FW'] = pd.to_datetime(['2026-06-01'])
    jul = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 7, hoje=HOJE_JUL))['PE-VEN-01']
    assert jul['Competência'] == '06/2026'


def test_montar_mes_sem_competencia_nao_quebra():
    # base/fixture sem MES_REF_FW: coluna sai None, resto do fluxo intacto
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1'},
    ])
    assert 'MES_REF_FW' not in merged.columns
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Competência'] is None
    assert jun['A-01']['NFF'] == '111'


def test_montar_mes_celpe_nao_paga_fica_a_pagar_e_nao_atrasada():
    """PE-PES-01: competência 06/2026, chegou 17/07, sem pagamento, prazo dia 21.
    O status é 'chegou' + 'A pagar' — a fatura existe, o que falta é o pagamento."""
    projetos = _df_projetos([('UFV Pesqueira I', 'PE-PES-01', 'CELPE', 21, 'E-MAIL')])
    merged = _df_merged_chegada([{
        'ACRONIMO': 'PE-PES-01', 'NOTA_FISCAL': '420512143',
        'DATA_REFERENCIA': '2026-06-01', 'DATA_CHEGADA': '2026-07-17',
        'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '7296717',
    }])
    jul = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 7, hoje=HOJE_JUL))['PE-PES-01']
    assert jul['NFF'] == '420512143'
    assert jul['Data Chegada'] == '17/07/2026'
    assert jul['Status'] == 'Chegou'    # 17/07 <= 21/07
    assert jul['Status'] != 'Atrasada'  # o que NÃO pode mais acontecer
    assert not jul['Pago']


def test_montar_mes_ancora_e_a_chegada_nao_a_referencia():
    """Regressão direta do bug de jul/2026: 12 usinas CELPE/COELBA/CEMIG marcadas
    'Atrasada' com NFF vazio numa aba onde as faturas JÁ tinham chegado.

    A fatura tem competência 06 e chegou em 07. Ancorada na DATA_REFERENCIA ela ia
    pra aba de junho e julho ficava vazio; ancorada na chegada, vai pra julho.
    """
    projetos = _df_projetos([('UFV Gravatá', 'PE-GRA-01', 'CELPE', 20, 'E-MAIL')])
    merged = _df_merged_chegada([{
        'ACRONIMO': 'PE-GRA-01', 'NOTA_FISCAL': '419546912',
        'DATA_REFERENCIA': '2026-06-01', 'DATA_CHEGADA': '2026-07-10',
        'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '9359873',
    }])
    jul = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 7, hoje=HOJE_JUL))
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jul['PE-GRA-01']['NFF'] == '419546912'   # aparece onde chegou
    assert jun['PE-GRA-01']['NFF'] is None          # e não onde é a competência
    assert jul['PE-GRA-01']['Status'] != 'Atrasada'


def test_montar_mes_cpfl_com_apresentacao_nao_muda_de_mes():
    """Aditividade pra quem preenche apresentação (CPFL/Equatorial/Enel): as duas
    cascatas compartilham os 2 primeiros degraus, então chegada == referência e o
    recorte cai no MESMO mês de antes da mudança de âncora."""
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL Paulista', 10, 'FW')])
    merged = _df_merged_chegada([{
        'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111',
        'DATA_REFERENCIA': '2026-06-08', 'DATA_CHEGADA': '2026-06-08',
        'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1',
    }])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    jul = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 7, hoje=HOJE_JUL))
    assert jun['A-01']['NFF'] == '111'
    assert jun['A-01']['Status'] == 'Chegou'   # 08/06 <= 10/06
    assert jul['A-01']['NFF'] is None


def test_montar_mes_duas_faturas_no_mesmo_mes_nao_somem():
    """Caso real BA-BAR-01: TRÊS faturas chegaram em maio/2026 (competências 02, 03 e
    04 — duas delas cobrança atrasada). O painel é uma linha por projeto/mês, então
    exibe a de competência mais recente; as outras têm que deixar rastro em vez de
    desaparecer, que era o comportamento antigo do groupby(...).tail(1).
    """
    projetos = _df_projetos([('UFV Barreiras', 'BA-BAR-01', 'COELBA', 18, 'E-MAIL')])
    merged = _df_merged_chegada([
        {'ACRONIMO': 'BA-BAR-01', 'NOTA_FISCAL': '965335681', 'DATA_REFERENCIA': '2026-02-01',
         'DATA_CHEGADA': '2026-05-26', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '70278379'},
        {'ACRONIMO': 'BA-BAR-01', 'NOTA_FISCAL': '965335693', 'DATA_REFERENCIA': '2026-03-01',
         'DATA_CHEGADA': '2026-05-26', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '70278379'},
        {'ACRONIMO': 'BA-BAR-01', 'NOTA_FISCAL': '965742358', 'DATA_REFERENCIA': '2026-04-01',
         'DATA_CHEGADA': '2026-05-27', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '70278379'},
    ])
    mai = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 5, hoje=HOJE_JUL))['BA-BAR-01']
    assert mai['NFF'] == '965742358'          # competência mais recente das três
    assert mai['Faturas no Mês'] == 3
    assert set(mai['NFF Adicionais'].split(', ')) == {'965335681', '965335693'}


def test_montar_mes_fatura_unica_nao_ganha_adicionais():
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged_chegada([{
        'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
        'DATA_CHEGADA': '2026-06-08', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1',
    }])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))['A-01']
    assert jun['Faturas no Mês'] == 1
    assert jun['NFF Adicionais'] is None


def test_montar_mes_projeto_sem_fatura_tem_contagem_zero():
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    jun = _por_acronimo(monitor.montar_mes(_df_merged([]), projetos, 2026, 6, hoje=HOJE_JUL))['A-01']
    assert jun['Faturas no Mês'] == 0
    assert jun['NFF Adicionais'] is None
    assert jun['Status'] == 'Atrasada'


def test_montar_mes_sem_data_chegada_cai_na_referencia():
    """Blindagem/compat: fixture (ou base antiga) sem DATA_CHEGADA usa a
    DATA_REFERENCIA, que era o comportamento anterior."""
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1'},
    ])
    assert 'DATA_CHEGADA' not in merged.columns
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Data Chegada'] == '08/06/2026'
    assert jun['A-01']['Status'] == 'Chegou'


# ---------------------------------------------------------------------------
# 3º degrau de pagamento — status da parcela no Oracle (AP_INSTALLMENTS)
# ---------------------------------------------------------------------------

def _df_merged_inst(linhas):
    """Igual a _df_merged, mas com as colunas do 3º degrau de pagamento
    (STATUS_INSTALLMENT / DATA_STATUS_INSTALLMENT)."""
    df = pd.DataFrame(
        linhas,
        columns=['ACRONIMO', 'NOTA_FISCAL', 'DATA_REFERENCIA', 'DATA_DE_PAGAMENTO', 'PAGAMENTO',
                 'UC', 'STATUS_INSTALLMENT', 'DATA_STATUS_INSTALLMENT']
    )
    for c in ('DATA_REFERENCIA', 'DATA_DE_PAGAMENTO', 'PAGAMENTO', 'DATA_STATUS_INSTALLMENT'):
        df[c] = pd.to_datetime(df[c], errors='coerce')
    return df


def test_montar_mes_pago_pelo_status_da_parcela():
    """Regressão da causa raiz: a AP_ORACLE_VIEW só sabia de pagamento por
    PAYMENT_DATE (AP_PAYMENTS). Quando o Oracle quita a PARCELA e o pagamento não
    chega naquela tabela, as duas fontes antigas ficam vazias e a fatura aparecia
    como "A pagar" mesmo paga — 2.372 faturas só em jun/2026 (SP-ARQ-04 e
    GO-PRG-01 foram os casos que levantaram isso).
    """
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'E-MAIL')])
    merged = _df_merged_inst([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1',
         'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': '2026-06-11 12:06:19'},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Pago']
    assert jun['A-01']['Data Pagamento'] == '11/06/2026'  # aproximada: UPDATED_AT da parcela
    assert jun['A-01']['Fonte Pagamento'] == 'ORACLE_INSTALLMENT'


def test_montar_mes_parcela_nao_paga_continua_a_pagar():
    # o degrau novo não pode marcar como pago o que o Oracle diz não estar pago
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'E-MAIL')])
    merged = _df_merged_inst([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1',
         'STATUS_INSTALLMENT': 'Não paga', 'DATA_STATUS_INSTALLMENT': '2026-06-18 17:53:22'},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert not jun['A-01']['Pago']
    assert jun['A-01']['Data Pagamento'] is None
    assert jun['A-01']['Fonte Pagamento'] is None


def test_montar_mes_parcela_paga_sem_data_ainda_conta_como_pago():
    """Parcela paga com UPDATED_AT nulo/ilegível: continua PAGA, só sem data.
    Sem o `| pago_parcela` no cálculo de Pago, a fatura voltaria a "A pagar"."""
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'E-MAIL')])
    merged = _df_merged_inst([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1',
         'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': None},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Pago']
    assert jun['A-01']['Data Pagamento'] is None
    assert jun['A-01']['Fonte Pagamento'] == 'ORACLE_INSTALLMENT'


def test_montar_mes_degrau_novo_e_aditivo():
    """Aditividade: quem já tinha pagamento pelos degraus 1/2 sai IDÊNTICO — a data
    real vence a aproximada da parcela, mesmo com a parcela também dizendo paga."""
    projetos = _df_projetos([
        ('Usina A', 'A-01', 'CPFL', 10, 'E-MAIL'),
        ('Usina B', 'B-01', 'COELBA', 10, 'E-MAIL'),
    ])
    merged = _df_merged_inst([
        # degrau 1 (Oracle payments) + parcela paga com data DIFERENTE
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-05',
         'DATA_DE_PAGAMENTO': '2026-06-20', 'PAGAMENTO': None, 'UC': '1',
         'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': '2026-06-11'},
        # degrau 2 (monitoramento) + parcela paga com data DIFERENTE
        {'ACRONIMO': 'B-01', 'NOTA_FISCAL': '222', 'DATA_REFERENCIA': '2026-06-06',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': '2026-06-22', 'UC': '2',
         'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': '2026-06-11'},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['Data Pagamento'] == '20/06/2026'
    assert jun['A-01']['Fonte Pagamento'] == 'ORACLE_PAYMENTS'
    assert jun['B-01']['Data Pagamento'] == '22/06/2026'
    assert jun['B-01']['Fonte Pagamento'] == 'MONITORAMENTO'


def test_montar_mes_sem_colunas_de_parcela_nao_quebra():
    """Blindagem: quando a ap_oracle_view ainda não expõe o status, carregar_base
    desliga o degrau e o df_merged chega SEM essas colunas. Tem que seguir
    funcionando com o comportamento de antes do fix."""
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'E-MAIL')])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1'},
    ])
    assert 'STATUS_INSTALLMENT' not in merged.columns
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert not jun['A-01']['Pago']
    assert jun['A-01']['Fonte Pagamento'] is None
    assert jun['A-01']['NFF'] == '111'  # resto do fluxo intacto


def _df_merged_fonte(linhas):
    """Igual a _df_merged, mas cada dict traz também a coluna FONTE
    ('MONITORAMENTO' ou 'FW_SUPLEMENTO')."""
    df = pd.DataFrame(
        linhas,
        columns=['ACRONIMO', 'NOTA_FISCAL', 'DATA_REFERENCIA', 'DATA_DE_PAGAMENTO', 'PAGAMENTO', 'UC', 'FONTE']
    )
    for c in ('DATA_REFERENCIA', 'DATA_DE_PAGAMENTO', 'PAGAMENTO'):
        df[c] = pd.to_datetime(df[c], errors='coerce')
    return df


def test_montar_mes_suplemento_fw_resgata_quando_sem_monitoramento():
    # cenário da demanda: nota chegou por e-mail, foi cadastrada no FW e paga no
    # Oracle, mas não subiu pro monitoramento. A linha suplementar deve resgatá-la
    # (deixa de ser "Atrasada" em branco e passa a exibir NFF/UC/Pago).
    projetos = _df_projetos([('Usina B', 'B-01', 'COELBA', 10, 'E-MAIL')])
    merged = _df_merged_fonte([
        {'ACRONIMO': 'B-01', 'NOTA_FISCAL': '777', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': '2026-06-20', 'PAGAMENTO': None, 'UC': '999', 'FONTE': 'FW_SUPLEMENTO'},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['B-01']['NFF'] == '777'
    assert jun['B-01']['UC'] == '999'
    assert jun['B-01']['Pago']
    assert jun['B-01']['Status'] == 'Chegou'  # chegou 08/06 <= esperada 10/06


def test_montar_mes_monitoramento_vence_suplemento_no_mesmo_mes():
    # aditividade: quando o mesmo ACRONIMO/mês tem linha de monitoramento E
    # suplementar, o monitoramento vence — mesmo com o suplemento tendo
    # DATA_REFERENCIA mais recente. Saída idêntica à de antes do fix.
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged_fonte([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-05',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1', 'FONTE': 'MONITORAMENTO'},
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '999', 'DATA_REFERENCIA': '2026-06-28',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1', 'FONTE': 'FW_SUPLEMENTO'},
    ])
    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))
    assert jun['A-01']['NFF'] == '111'  # e não '999'


def test_listar_meses_inclui_corrente_e_ordena_desc():
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '1', 'DATA_REFERENCIA': '2026-05-05', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1'},
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '2', 'DATA_REFERENCIA': '2026-06-05', 'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1'},
    ])
    meses = monitor.listar_meses(merged, hoje=HOJE_JUL)
    assert meses[0] == {'ano': 2026, 'mes': 7}          # corrente entra e vem 1º
    assert {'ano': 2026, 'mes': 6} in meses
    assert {'ano': 2026, 'mes': 5} in meses
    chaves = [(m['ano'], m['mes']) for m in meses]
    assert chaves == sorted(chaves, reverse=True)


# ---------------------------------------------------------------------------
# Leitura de pagamentos: UMA query recortada, com fallback pro caminho antigo.
# Ver _carregar_pagamentos — antes eram duas leituras da AP_ORACLE_VIEW inteira
# (1.004.303 + 975.691 linhas pra usar 1.113).
# ---------------------------------------------------------------------------

def _df_recortado():
    """Shape de stg_pagamentos_usinas.sql: os DOIS blocos na mesma linha, com as
    colunas de parcela nulas quando não há evidência positiva de pagamento."""
    return pd.DataFrame([
        {'NOTA_FISCAL': '111', 'FATURA_VALOR': 100.0, 'DATA_DE_PAGAMENTO': '2026-06-20',
         'DATA_INVOICE': '2026-06-01', 'STATUS_INSTALLMENT': 'Totalmente paga',
         'DATA_STATUS_INSTALLMENT': '2026-06-11'},
        {'NOTA_FISCAL': '222', 'FATURA_VALOR': 200.0, 'DATA_DE_PAGAMENTO': None,
         'DATA_INVOICE': '2026-06-02', 'STATUS_INSTALLMENT': None,
         'DATA_STATUS_INSTALLMENT': None},
    ])


def _fake_read_sql(mapa):
    """read_sql falso que despacha pelo NOME LÓGICO da query (os testes patcham
    _get_query pra devolver o próprio nome). Valor do mapa pode ser um DataFrame ou
    uma exceção, pra simular query indisponível. Devolve (função, lista_de_chamadas)."""
    chamadas = []

    def _read(sql, conn):
        chamadas.append(sql)
        r = mapa[sql]
        if isinstance(r, Exception):
            raise r
        return r.copy()

    return _read, chamadas


def test_prep_pag_nao_deixa_parcela_vazar_pro_bloco_de_pagamento():
    # se STATUS_INSTALLMENT viajasse dentro de df_pag, o merge de df_inst em
    # carregar_base criaria sufixos _x/_y e o 3º degrau parava de ser lido
    out = monitor._prep_pag(_df_recortado())
    assert list(out.columns) == monitor.COLS_PAG
    assert len(out) == 2
    assert out.set_index('NOTA_FISCAL').loc['111', 'DATA_DE_PAGAMENTO'] == Timestamp('2026-06-20')


def test_prep_pag_elege_a_linha_paga_quando_a_nota_repete():
    # regressão do na_position='first': com o default do pandas o NaT vai pro FIM e o
    # tail(1) elegia a linha SEM pagamento — a fatura aparecia como não paga
    df = pd.DataFrame([
        {'NOTA_FISCAL': '111', 'FATURA_VALOR': 100.0, 'DATA_DE_PAGAMENTO': '2026-06-20', 'DATA_INVOICE': '2026-06-01'},
        {'NOTA_FISCAL': '111', 'FATURA_VALOR': 100.0, 'DATA_DE_PAGAMENTO': None, 'DATA_INVOICE': '2026-06-01'},
    ])
    out = monitor._prep_pag(df)
    assert len(out) == 1
    assert out.iloc[0]['DATA_DE_PAGAMENTO'] == Timestamp('2026-06-20')


def test_prep_inst_guarda_so_a_evidencia_positiva():
    out = monitor._prep_inst(_df_recortado())
    assert list(out['NOTA_FISCAL']) == ['111']          # a 222 vem com NULL no CASE
    assert out.iloc[0]['DATA_STATUS_INSTALLMENT'] == Timestamp('2026-06-11')


def test_prep_inst_no_caminho_antigo_e_no_op():
    # stg_pagamentos_installment.sql já filtra no servidor: nada pode ser descartado aqui
    df = pd.DataFrame([
        {'NOTA_FISCAL': '111', 'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': '2026-06-11'},
        {'NOTA_FISCAL': '222', 'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': '2026-06-12'},
    ])
    out = monitor._prep_inst(df)
    assert list(out['NOTA_FISCAL']) == ['111', '222']


def test_prep_inst_descarta_nota_nula():
    # nota nula viraria chave 'None'/'nan' e casaria com outra nota nula no merge
    df = pd.DataFrame([
        {'NOTA_FISCAL': None, 'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': '2026-06-11'},
        {'NOTA_FISCAL': '222', 'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': '2026-06-12'},
    ])
    out = monitor._prep_inst(df)
    assert list(out['NOTA_FISCAL']) == ['222']


def test_carregar_pagamentos_le_a_view_uma_vez_so(monkeypatch):
    read, chamadas = _fake_read_sql({'pagamentos_usinas': _df_recortado()})
    monkeypatch.setattr(monitor, '_get_query', lambda nome, mp: nome)
    monkeypatch.setattr(monitor.pd, 'read_sql', read)

    df_pag, df_inst = monitor._carregar_pagamentos(object(), {})

    assert chamadas == ['pagamentos_usinas']           # era 2x a AP_ORACLE_VIEW inteira
    assert len(df_pag) == 2
    assert list(df_inst['NOTA_FISCAL']) == ['111']


def test_carregar_pagamentos_cai_pro_caminho_antigo(monkeypatch):
    """A query recortada depende de colunas recentes na view e cruza com
    MONITORAMENTO_CUSD_AWS/FATTUREWEB_USINAS: se falhar, o monitor tem que voltar ao
    comportamento anterior (duas queries) em vez de ficar sem pagamento."""
    read, chamadas = _fake_read_sql({
        'pagamentos_usinas': RuntimeError('invalid identifier STATUS_PAGAMENTO_INSTALLMENT'),
        'pagamentos': pd.DataFrame([
            {'NOTA_FISCAL': '111', 'FATURA_VALOR': 100.0, 'DATA_DE_PAGAMENTO': '2026-06-20', 'DATA_INVOICE': '2026-06-01'},
            {'NOTA_FISCAL': '222', 'FATURA_VALOR': 200.0, 'DATA_DE_PAGAMENTO': None, 'DATA_INVOICE': '2026-06-02'},
        ]),
        'pagamentos_installment': pd.DataFrame([
            {'NOTA_FISCAL': '111', 'STATUS_INSTALLMENT': 'Totalmente paga', 'DATA_STATUS_INSTALLMENT': '2026-06-11'},
        ]),
    })
    monkeypatch.setattr(monitor, '_get_query', lambda nome, mp: nome)
    monkeypatch.setattr(monitor.pd, 'read_sql', read)

    df_pag, df_inst = monitor._carregar_pagamentos(object(), {})

    assert chamadas == ['pagamentos_usinas', 'pagamentos', 'pagamentos_installment']
    assert len(df_pag) == 2
    assert list(df_pag.columns) == monitor.COLS_PAG
    assert list(df_inst['NOTA_FISCAL']) == ['111']


def test_carregar_pagamentos_fallback_sem_parcela_nao_quebra(monkeypatch):
    """Pior caso: recorte E parcela indisponíveis. Pagamento segue por AP_PAYMENTS e o
    df_inst sai vazio COM as colunas certas (senão o merge em carregar_base quebra)."""
    read, chamadas = _fake_read_sql({
        'pagamentos_usinas': RuntimeError('sem grant em MONITORAMENTO_CUSD_AWS'),
        'pagamentos': pd.DataFrame([
            {'NOTA_FISCAL': '111', 'FATURA_VALOR': 100.0, 'DATA_DE_PAGAMENTO': '2026-06-20', 'DATA_INVOICE': '2026-06-01'},
        ]),
        'pagamentos_installment': RuntimeError('invalid identifier STATUS_PAGAMENTO_INSTALLMENT'),
    })
    monkeypatch.setattr(monitor, '_get_query', lambda nome, mp: nome)
    monkeypatch.setattr(monitor.pd, 'read_sql', read)

    df_pag, df_inst = monitor._carregar_pagamentos(object(), {})

    assert len(df_pag) == 1
    assert df_inst.empty
    assert list(df_inst.columns) == monitor.COLS_INST


def test_montar_mes_valor_oracle_divergente_do_fattureweb():
    """Caso real (NFF 047744547): 19.142,04 no FattureWeb, 7.525,59 no Oracle.

    'Pago' vem do Oracle e 'Total Fatura' do FattureWeb, então o painel dava a entender
    que os 19.142,04 foram quitados quando o que entrou na AP foi 7.525,59. A coluna
    'Valor Oracle' expõe as duas pontas e 'Divergência Valor' quantifica a diferença.
    """
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '047744547', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': '2026-06-20', 'PAGAMENTO': None, 'UC': '1'},
    ])
    merged['TOTAL_DA_FATURA'] = [19142.04]
    merged['FATURA_VALOR'] = [7525.59]

    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))['A-01']
    assert jun['Total Fatura'] == 19142.04
    assert jun['Valor Oracle'] == 7525.59
    assert jun['Divergência Valor'] == 11616.45
    assert jun['Pago']                      # o pagamento continua sendo reportado


def test_montar_mes_valor_oracle_igual_nao_divergencia():
    # mesmo valor nas duas pontas: diferença 0, a UI não marca nada
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': '2026-06-20', 'PAGAMENTO': None, 'UC': '1'},
    ])
    merged['TOTAL_DA_FATURA'] = [1500.00]
    merged['FATURA_VALOR'] = [1500.00]

    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))['A-01']
    assert jun['Divergência Valor'] == 0.0


def test_montar_mes_sem_valor_oracle_nao_quebra():
    """Fatura que ainda não foi lançada no Oracle (e fixture antiga sem a coluna):
    'Valor Oracle' e 'Divergência Valor' saem None em vez de acusar divergência do
    total inteiro."""
    projetos = _df_projetos([('Usina A', 'A-01', 'CPFL', 10, 'FW')])
    merged = _df_merged([
        {'ACRONIMO': 'A-01', 'NOTA_FISCAL': '111', 'DATA_REFERENCIA': '2026-06-08',
         'DATA_DE_PAGAMENTO': None, 'PAGAMENTO': None, 'UC': '1'},
    ])
    assert 'FATURA_VALOR' not in merged.columns

    jun = _por_acronimo(monitor.montar_mes(merged, projetos, 2026, 6, hoje=HOJE_JUL))['A-01']
    assert jun['Valor Oracle'] is None
    assert jun['Divergência Valor'] is None
    assert jun['NFF'] == '111'


def test_completar_recupera_valor_da_fatura_com_zero_a_esquerda():
    """Caso real do painel: NFF com ZERO À ESQUERDA vinha 'paga' com 'Valor Oracle' vazio.

    O monitoramento guarda '047744547' e o Oracle '47744547', então o merge exato falha e
    quem recupera é este passe. Recuperando só a data, o valor ficava em branco — o padrão
    que apareceu na tela (só NFF sem zero à esquerda traziam valor).
    """
    df = pd.DataFrame([{'NOTA_FISCAL': '047744547', 'FATURA_VALOR': None}])
    fonte = pd.DataFrame([{'NOTA_FISCAL': '47744547', 'FATURA_VALOR': 7525.59}])
    n, amb = monitor._completar_por_chave_normalizada(df, fonte, ['FATURA_VALOR'])
    assert (n, amb) == (1, 0)
    assert df.loc[0, 'FATURA_VALOR'] == 7525.59


def test_completar_valor_em_chamada_separada_da_data():
    """Por que FATURA_VALOR NÃO entra na mesma chamada da data (regressão GO-MNU-01).

    FATURA_VALOR vem preenchido em toda linha de AP, inclusive na nota Cancelada. Junto
    na mesma lista, a salvaguarda 1 (`.notna().any()`) deixaria a Cancelada disputar a
    chave, ela voltaria a ser ambígua e o pagamento HOJE recuperado se perderia.
    Separadas, a data segue sendo encontrada e só o valor é descartado por ambiguidade.
    """
    fonte = pd.DataFrame([
        # nota Cancelada: sem pagamento, mas COM valor
        {'NOTA_FISCAL': '194412037', 'DATA_DE_PAGAMENTO': pd.NaT, 'FATURA_VALOR': 0.0},
        {'NOTA_FISCAL': '194412037.0', 'DATA_DE_PAGAMENTO': Timestamp('2026-06-16'), 'FATURA_VALOR': 1500.0},
    ])

    # juntas: a Cancelada volta à disputa e o pagamento se PERDE — o que não queremos
    df_junto = pd.DataFrame([{'NOTA_FISCAL': '194412037', 'DATA_DE_PAGAMENTO': pd.NaT, 'FATURA_VALOR': None}])
    n_junto, amb_junto = monitor._completar_por_chave_normalizada(
        df_junto, fonte, ['DATA_DE_PAGAMENTO', 'FATURA_VALOR'])
    assert (n_junto, amb_junto) == (0, 1)
    assert pd.isna(df_junto.loc[0, 'DATA_DE_PAGAMENTO'])

    # separadas (o que carregar_base faz): a data é encontrada; só o valor fica ambíguo
    df = pd.DataFrame([{'NOTA_FISCAL': '194412037', 'DATA_DE_PAGAMENTO': pd.NaT, 'FATURA_VALOR': None}])
    n_pag, _ = monitor._completar_por_chave_normalizada(df, fonte, ['DATA_DE_PAGAMENTO'])
    n_val, amb_val = monitor._completar_por_chave_normalizada(df, fonte, ['FATURA_VALOR'])
    assert n_pag == 1
    assert df.loc[0, 'DATA_DE_PAGAMENTO'] == Timestamp('2026-06-16')
    assert (n_val, amb_val) == (0, 1)          # valor descartado, e é o pior caso aceitável
    assert pd.isna(df.loc[0, 'FATURA_VALOR'])
