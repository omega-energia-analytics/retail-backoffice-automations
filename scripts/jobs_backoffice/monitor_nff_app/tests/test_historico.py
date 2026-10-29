"""Testes do histórico do painel (db.registrar_snapshot / buscar_historico).

Mesmo isolamento do test_db.py: MONITOR_NFF_DB_PATH aponta pra tmp_path, então
cada teste roda contra um banco descartável.

O que estes testes protegem, em uma frase: **o log só pode crescer quando algo
de fato mudou**. Um painel estável relido cinco vezes no dia não pode virar
cinco linhas, e uma mudança real não pode passar batida.
"""
import pytest

import db


@pytest.fixture
def db_isolado(tmp_path, monkeypatch):
    caminho = tmp_path / "controle_nff.db"
    monkeypatch.setenv("MONITOR_NFF_DB_PATH", str(caminho))
    db.init_db()
    return caminho


def linha(**kw):
    """Linha do painel para os testes.

    Só a identidade vem preenchida; TODO campo vigiado nasce vazio e cada teste
    declara o que quer observar. É de propósito: com default preenchido, uma
    fatura nova gravaria linhas que o teste não pediu e as contagens deixariam
    de dizer o que parecem dizer.
    """
    base = {
        'Projeto': 'Rio Quente I',
        'ACRONIMO': 'GO-RIQ-01',
        'Competência': '09/2026',
        'NFF': None,
    }
    base.update({c: None for c in db.CAMPOS_HISTORICO})
    base.update(kw)
    return base


# Mês do painel default. A maioria dos testes não se importa com qual é — só
# precisa que seja o mesmo entre chamadas, para a fatura reencontrar seu
# estado. Os testes que investigam o mês passam o seu explicitamente.
MES = '2026-09'


def registrar(linhas, observado_em, mes_painel=MES):
    return db.registrar_snapshot(linhas, observado_em, mes_painel)


# --- primeira aparição ---
def test_primeira_carga_grava_campos_preenchidos(db_isolado):
    n = registrar([linha(Status='Chegou', Pago=True)], "2026-10-14T08:00:00")
    # Status e Pago têm valor; os demais estão vazios e não geram linha
    assert n == 2
    campos = {h['campo'] for h in db.buscar_historico(incluir_carga_inicial=True)}
    assert campos == {'Status', 'Pago'}


def test_primeira_carga_nao_grava_campo_vazio(db_isolado):
    """Fatura que o painel ainda não tem nada a dizer sobre não entra no log."""
    assert registrar([linha()], "2026-10-14T08:00:00") == 0
    assert db.total_historico() == 0


def test_pago_false_conta_como_valor(db_isolado):
    """'A pagar' é informação, diferente de 'não sei' — tem que entrar."""
    registrar([linha(Pago=False)], "2026-10-14T08:00:00")
    assert [h['valor_para'] for h in db.buscar_historico(incluir_carga_inicial=True)] == ['nao']


def test_linha_sem_projeto_e_ignorada(db_isolado):
    assert registrar(
        [linha(Projeto=None, Status='Chegou')], "2026-10-14T08:00:00") == 0
    assert db.total_historico() == 0


# --- o coração: só grava mudança ---
def test_recarga_sem_mudanca_nao_grava_nada(db_isolado):
    l = linha(Status='Chegou', Pago=True)
    registrar([l], "2026-10-14T08:00:00")
    antes = db.total_historico()
    # mesma base relida mais quatro vezes no mesmo dia
    for ts in ("09:00:00", "11:30:00", "14:00:00", "17:45:00"):
        assert registrar([l], f"2026-10-14T{ts}") == 0
    assert db.total_historico() == antes


def test_mudanca_de_status_vira_uma_linha(db_isolado):
    registrar([linha(Status='Atrasada')], "2026-10-13T08:00:00")
    n = registrar([linha(Status='Chegou')], "2026-10-14T08:00:00")
    assert n == 1
    h = db.buscar_historico(incluir_carga_inicial=True)[0]
    assert (h['campo'], h['valor_de'], h['valor_para']) == ('Status', 'Atrasada', 'Chegou')


def test_pagamento_registra_transicao_booleana(db_isolado):
    registrar([linha(Pago=False)], "2026-10-14T08:00:00")
    registrar([linha(Pago=True)], "2026-10-16T09:40:00")
    pagos = [h for h in db.buscar_historico(incluir_carga_inicial=True) if h['campo'] == 'Pago']
    assert (pagos[0]['valor_de'], pagos[0]['valor_para']) == ('nao', 'sim')


def test_valor_que_volta_ao_anterior_grava_as_duas_mudancas(db_isolado):
    """Ida e volta são dois eventos — o log conta a história, não o estado."""
    registrar([linha(Status='Chegou')], "2026-10-14T08:00:00")
    registrar([linha(Status='Atrasada')], "2026-10-15T08:00:00")
    registrar([linha(Status='Chegou')], "2026-10-16T08:00:00")
    status = [h for h in db.buscar_historico(incluir_carga_inicial=True) if h['campo'] == 'Status']
    assert len(status) == 3


# --- estabilidade de representação (o que _txt protege) ---
def test_valor_em_texto_br_vira_numero(db_isolado):
    """`Total Fatura` chega do FattureWeb como TEXTO em formato brasileiro
    ('32810,15'), não como float — medido no banco real. Sem normalizar, o JS
    faz Number('32810,15') -> NaN e a tela mostra o texto cru."""
    registrar([linha(**{'Total Fatura': '32810,15'})], "2026-10-22T07:40:00")
    assert db.buscar_historico(incluir_carga_inicial=True)[0]['valor_para'] == '32810.15'


def test_texto_br_e_float_do_mesmo_valor_nao_divergem(db_isolado):
    """O caso que motivou a correção: as duas pontas são dinheiro e precisam
    virar a mesma coisa. 'Valor Oracle' vem float, 'Total Fatura' vem texto."""
    registrar([linha(**{'Total Fatura': '7575,10'})], "2026-10-22T07:40:00")
    assert registrar(
        [linha(**{'Total Fatura': 7575.1})], "2026-10-22T08:00:00") == 0


def test_separador_de_milhar_br(db_isolado):
    registrar([linha(**{'Total Fatura': '1.234,56'})], "2026-10-22T07:40:00")
    assert db.buscar_historico(incluir_carga_inicial=True)[0]['valor_para'] == '1234.56'


def test_zero_em_texto_br(db_isolado):
    """'0,0' aparecia cru na tela — é zero de verdade, não valor ausente."""
    registrar([linha(**{'Total Fatura': '0,0'})], "2026-10-22T07:40:00")
    assert db.buscar_historico(incluir_carga_inicial=True)[0]['valor_para'] == '0.00'


def test_valor_nao_numerico_vira_texto_cru(db_isolado):
    """Não descarta: quem ler o log tem que ver o que a fonte mandou."""
    registrar([linha(**{'Total Fatura': 'a combinar'})], "2026-10-22T07:40:00")
    assert db.buscar_historico(incluir_carga_inicial=True)[0]['valor_para'] == 'a combinar'


def test_campo_de_texto_com_virgula_nao_e_convertido(db_isolado):
    """Só os campos de dinheiro passam pela conversão — Status não."""
    registrar([linha(Status='Chegou, parcial')], "2026-10-22T07:40:00")
    assert db.buscar_historico(incluir_carga_inicial=True)[0]['valor_para'] == 'Chegou, parcial'


def test_float_com_ruido_de_ponto_flutuante_nao_vira_mudanca(db_isolado):
    registrar([linha(**{'Total Fatura': 19142.04})], "2026-10-14T08:00:00")
    n = registrar(
        [linha(**{'Total Fatura': 19142.039999999997})], "2026-10-15T08:00:00")
    assert n == 0


def test_diferenca_de_centavo_vira_mudanca(db_isolado):
    registrar([linha(**{'Valor Oracle': 7525.59})], "2026-10-14T08:00:00")
    n = registrar([linha(**{'Valor Oracle': 7525.60})], "2026-10-15T08:00:00")
    assert n == 1


def test_nan_e_tratado_como_vazio(db_isolado):
    """Coluna numérica vazia do pandas chega como NaN, não None."""
    registrar([linha(**{'Total Fatura': float('nan')})], "2026-10-14T08:00:00")
    assert db.total_historico() == 0


def test_espaco_em_branco_nao_vira_mudanca(db_isolado):
    registrar([linha(Status='Chegou')], "2026-10-14T08:00:00")
    assert registrar([linha(Status='  Chegou  ')], "2026-10-15T08:00:00") == 0


# --- identidade: a 2ª NFF do mês é outra fatura ---
def test_segunda_nff_no_mesmo_mes_e_fatura_propria(db_isolado):
    """Chave é (projeto, competência, NFF). Uma nota nova no mesmo mês não pode
    aparecer como se a primeira tivesse mudado de número."""
    registrar(
        [linha(NFF='047744547', Status='Chegou')], "2026-10-14T08:00:00")
    n = registrar(
        [linha(NFF='047744547', Status='Chegou'),
         linha(NFF='047999001', Status='Chegou')], "2026-10-20T08:00:00")
    # a primeira não mudou; só a segunda entrou, como novata
    assert n == 1
    assert [h['nff'] for h in db.buscar_historico(incluir_carga_inicial=True)] == ['047999001', '047744547']


def test_fatura_sem_nff_reencontra_seu_estado(db_isolado):
    """NFF ausente vira '' e não NULL — senão a linha nunca casaria consigo
    mesma e 'apareceu' se repetiria a cada carga."""
    registrar([linha(NFF=None, Status='Pendente')], "2026-10-14T08:00:00")
    assert registrar(
        [linha(NFF=None, Status='Pendente')], "2026-10-15T08:00:00") == 0


def test_linha_do_tempo_de_uma_usina_com_segunda_nff(db_isolado):
    """A 2ª emissão do mês tem história própria, sem embaralhar a da 1ª."""
    registrar(
        [linha(NFF='047744547', Status='Chegou', Pago=False)], "2026-10-14T08:00:00")
    registrar(
        [linha(NFF='047744547', Status='Chegou', Pago=True),
         linha(NFF='047999001', Status='Chegou', Pago=False)], "2026-10-20T08:00:00")
    primeira = [(h['campo'], h['valor_para'])
                for h in db.buscar_historico('047744547', incluir_carga_inicial=True)]
    segunda = [(h['campo'], h['valor_para'])
               for h in db.buscar_historico('047999001', incluir_carga_inicial=True)]
    assert primeira == [('Pago', 'sim'), ('Pago', 'nao'), ('Status', 'Chegou')]
    assert segunda == [('Pago', 'nao'), ('Status', 'Chegou')]


def test_mesmo_projeto_em_competencias_diferentes_nao_se_misturam(db_isolado):
    registrar([linha(**{'Competência': '08/2026', 'Status': 'Chegou'})],
                          "2026-09-10T08:00:00")
    n = registrar([linha(**{'Competência': '09/2026', 'Status': 'Atrasada'})],
                              "2026-10-14T08:00:00")
    # competência nova = fatura nova, entra como novata e não como mudança de status
    assert n == 1
    assert db.buscar_historico(incluir_carga_inicial=True)[0]['valor_de'] is None


# --- adoção: a fatura que ganhou nota ---
def test_fatura_que_ganha_nff_continua_a_mesma(db_isolado):
    """O caso que a chave com NFF criava: a fatura existe no painel antes de ter
    nota. Ganhar a nota não pode parti-la em duas — 'Atrasada -> Chegou' é
    justamente a transição que a aba existe pra mostrar."""
    registrar([linha(NFF=None, Status='Atrasada')], "2026-10-13T08:00:00")
    registrar([linha(NFF='047744547', Status='Chegou')], "2026-10-14T08:00:00")
    hist = db.buscar_historico('GO-RIQ-01', incluir_carga_inicial=True)
    status = [h for h in hist if h['campo'] == 'Status']
    assert (status[0]['valor_de'], status[0]['valor_para']) == ('Atrasada', 'Chegou')
    # e todo o histórico agora está sob a nota, não espalhado entre '' e ela
    assert {h['nff'] for h in hist} == {'047744547'}


def test_chegada_da_nota_vira_evento(db_isolado):
    registrar([linha(NFF=None, Status='Atrasada')], "2026-10-13T08:00:00")
    registrar([linha(NFF='047744547', Status='Chegou')], "2026-10-14T08:00:00")
    nff_evt = [h for h in db.buscar_historico(incluir_carga_inicial=True) if h['campo'] == 'NFF']
    assert len(nff_evt) == 1
    assert (nff_evt[0]['valor_de'], nff_evt[0]['valor_para']) == (None, '047744547')


def test_adocao_nao_rouba_historico_de_nota_ja_existente(db_isolado):
    """Se a nota já tem história própria, a sem-nota é outra fatura — adotar
    embaralharia duas histórias."""
    registrar([linha(NFF='047744547', Status='Chegou')], "2026-10-10T08:00:00")
    registrar([
        linha(NFF='047744547', Status='Chegou'),
        linha(NFF=None, Status='Atrasada'),  # 2ª fatura do mês, ainda sem nota
    ], "2026-10-13T08:00:00")
    n = registrar([
        linha(NFF='047744547', Status='Chegou'),
        linha(NFF=None, Status='Atrasada'),
    ], "2026-10-14T08:00:00")
    assert n == 0
    # a órfã continua órfã; a nota não absorveu o 'Atrasada' dela
    assert {h['nff'] for h in db.buscar_historico(incluir_carga_inicial=True)} == {'047744547', ''}


def test_adocao_persiste_sem_mudanca_na_mesma_carga(db_isolado):
    """Adoção sem nenhuma mudança nova ainda tem que ser gravada — senão a
    fatura volta a ser órfã na carga seguinte."""
    registrar([linha(NFF=None, Status='Chegou')], "2026-10-13T08:00:00")
    # mesma situação, só que agora com nota: nada mudou além da nota chegar
    registrar([linha(NFF='047744547', Status='Chegou')], "2026-10-14T08:00:00")
    # recarga seguinte não pode re-adotar nem regravar nada
    assert registrar(
        [linha(NFF='047744547', Status='Chegou')], "2026-10-15T08:00:00") == 0
    assert {h['nff'] for h in db.buscar_historico(incluir_carga_inicial=True)} == {'047744547'}


def test_adocao_respeita_competencia(db_isolado):
    """Órfã de agosto não pode ser adotada pela nota de setembro."""
    registrar([linha(**{'Competência': '08/2026'}, Status='Atrasada')],
                          "2026-09-13T08:00:00")
    registrar([linha(**{'Competência': '09/2026'}, NFF='047744547',
                                 Status='Chegou')], "2026-10-14T08:00:00")
    por_comp = {(h['competencia'], h['nff']) for h in db.buscar_historico(incluir_carga_inicial=True)}
    assert por_comp == {('08/2026', ''), ('09/2026', '047744547')}


# --- busca ---
def test_busca_por_acronimo(db_isolado):
    registrar([
        linha(Status='Chegou'),
        linha(Projeto='Chui I', ACRONIMO='RS-CHU-01', Status='Atrasada'),
    ], "2026-10-14T08:00:00")
    achados = db.buscar_historico('GO-RIQ-01', incluir_carga_inicial=True)
    assert {h['acronimo'] for h in achados} == {'GO-RIQ-01'}


def test_busca_por_nff(db_isolado):
    registrar([
        linha(NFF='047744547', Status='Chegou'),
        linha(Projeto='Chui I', ACRONIMO='RS-CHU-01', NFF='999', Status='Chegou'),
    ], "2026-10-14T08:00:00")
    assert {h['nff'] for h in db.buscar_historico('047744547', incluir_carga_inicial=True)} == {'047744547'}


def test_busca_por_projeto_e_case_insensitive(db_isolado):
    registrar([linha(Status='Chegou')], "2026-10-14T08:00:00")
    assert [h['projeto'] for h in db.buscar_historico('rio quente', incluir_carga_inicial=True)] == ['Rio Quente I']


def test_busca_parcial_casa(db_isolado):
    """Pedaço do acrônimo basta — ninguém digita o código inteiro."""
    registrar([
        linha(Status='Chegou'),
        linha(Projeto='Chui I', ACRONIMO='RS-CHU-01', Status='Chegou'),
    ], "2026-10-14T08:00:00")
    assert {h['acronimo'] for h in db.buscar_historico('RIQ', incluir_carga_inicial=True)} == {'GO-RIQ-01'}


def test_busca_sem_termo_devolve_tudo(db_isolado):
    registrar([
        linha(Status='Chegou'),
        linha(Projeto='Chui I', ACRONIMO='RS-CHU-01', Status='Chegou'),
    ], "2026-10-14T08:00:00")
    assert len(db.buscar_historico(incluir_carga_inicial=True)) == db.total_historico()


def test_busca_ordena_mais_recente_primeiro(db_isolado):
    registrar([linha(Status='Atrasada')], "2026-10-13T08:00:00")
    registrar([linha(Status='Chegou')], "2026-10-14T08:00:00")
    assert [h['valor_para'] for h in db.buscar_historico('GO-RIQ-01', incluir_carga_inicial=True)] == ['Chegou', 'Atrasada']


def test_busca_respeita_limite(db_isolado):
    for i in range(10):
        registrar([linha(Status=f'S{i}')], f"2026-10-{10+i}T08:00:00")
    assert len(db.buscar_historico('GO-RIQ-01', limite=3)) == 3


def test_linha_do_tempo_de_uma_usina(db_isolado):
    """O caso de uso que motivou a aba: seguir uma usina ao longo do período."""
    ago = {'Competência': '08/2026'}
    # ainda não chegou
    registrar([linha(**ago, Status='Pendente', Pago=False)],
                          "2026-09-01T08:00:00")
    # chegou, com nota e valor
    registrar(
        [linha(**ago, Status='Chegou', Pago=False,
               **{'Data Chegada': '09/09/2026', 'Total Fatura': 19142.04})],
        "2026-09-09T08:00:00")
    # pagou
    registrar(
        [linha(**ago, Status='Chegou', Pago=True,
               **{'Data Chegada': '09/09/2026', 'Total Fatura': 19142.04,
                  'Fonte Pagamento': 'ORACLE_PAYMENTS'})],
        "2026-09-11T08:00:00")
    linha_do_tempo = [(h['campo'], h['valor_para'])
                      for h in reversed(db.buscar_historico('GO-RIQ-01', incluir_carga_inicial=True))]
    assert linha_do_tempo == [
        ('Status', 'Pendente'), ('Pago', 'nao'),
        ('Status', 'Chegou'), ('Data Chegada', '09/09/2026'),
        ('Total Fatura', '19142.04'),
        ('Pago', 'sim'), ('Fonte Pagamento', 'ORACLE_PAYMENTS'),
    ]


# --- carga inicial ---
def test_carga_inicial_fica_fora_por_padrao(db_isolado):
    """A primeira carga registra o acervo inteiro ('tudo apareceu'). Mostrar
    isso afoga a mudança de verdade — foi o que a primeira tela real mostrou."""
    registrar([
        linha(Status='Chegou'),
        linha(Projeto='Chui I', ACRONIMO='RS-CHU-01', Status='Chegou'),
    ], "2026-10-22T07:40:00")
    assert db.buscar_historico() == []
    assert len(db.buscar_historico(incluir_carga_inicial=True)) == 2


def test_mudanca_posterior_aparece_sem_a_carga_inicial(db_isolado):
    registrar([linha(Status='Atrasada')], "2026-10-22T07:40:00")
    registrar([linha(Status='Chegou')], "2026-10-23T08:00:00")
    visivel = db.buscar_historico()
    assert len(visivel) == 1
    assert (visivel[0]['valor_de'], visivel[0]['valor_para']) == ('Atrasada', 'Chegou')


def test_carga_inicial_em_banco_vazio(db_isolado):
    assert db.carga_inicial_em() is None
    assert db.buscar_historico() == []


def test_carga_inicial_nao_desliza_para_a_segunda_carga(db_isolado):
    """O corte é a PRIMEIRA gravação e fica onde está — senão, a cada carga nova
    a anterior viraria 'inicial' e sumiria da tela."""
    registrar([linha(Status='Atrasada')], "2026-10-22T07:40:00")
    registrar([linha(Status='Chegou')], "2026-10-23T08:00:00")
    registrar([linha(Status='Atrasada')], "2026-10-24T08:00:00")
    assert db.carga_inicial_em() == "2026-10-22T07:40:00"
    assert len(db.buscar_historico()) == 2


def test_busca_por_termo_respeita_o_corte(db_isolado):
    registrar([linha(Status='Atrasada')], "2026-10-22T07:40:00")
    registrar([linha(Status='Chegou')], "2026-10-23T08:00:00")
    assert len(db.buscar_historico('GO-RIQ-01')) == 1
    assert len(db.buscar_historico('GO-RIQ-01', incluir_carga_inicial=True)) == 2


# --- isolamento entre as duas tabelas ---
def test_historico_nao_interfere_no_controle_nff(db_isolado):
    db.inserir_nffs(["NFF-1"], "2026-10-14T08:00:00")
    registrar([linha(Status='Chegou')], "2026-10-14T08:00:00")
    assert db.total_registros() == 1
    assert db.total_historico() == 1


def test_init_db_e_idempotente_com_dados(db_isolado):
    registrar([linha(Status='Chegou')], "2026-10-14T08:00:00")
    db.init_db()  # reabrir o app não pode apagar o histórico
    assert db.total_historico() == 1


def test_historico_sobrevive_a_reabertura_do_app(db_isolado):
    """O ponto da aba: fechar e abrir não zera nada, e a carga seguinte continua
    de onde parou em vez de regravar tudo como novidade."""
    registrar([linha(Status='Atrasada')], "2026-10-13T08:00:00")
    db.init_db()  # app reaberto
    n = registrar([linha(Status='Chegou')], "2026-10-14T08:00:00")
    assert n == 1
    assert [h['valor_de'] for h in db.buscar_historico(incluir_carga_inicial=True)][0] == 'Atrasada'



# --- mês do painel na identidade (regressão do vai-e-volta infinito) ---
def test_fatura_sem_competencia_nao_colapsa_entre_meses(db_isolado):
    """O bug que a primeira tela real mostrou: PE-BMD-01 ia 'Pendente ->
    Atrasada' e 'Atrasada -> Pendente' NO MESMO SEGUNDO.

    Fatura que ainda não chegou não tem competência nem nota, então a chave era
    (projeto, '', '') e todos os meses dela colapsavam numa só. O mesmo projeto
    aparece 'Pendente' no mês corrente e 'Atrasada' num mês vencido, então cada
    mês sobrescrevia o outro — a cada carga, para sempre.
    """
    sem_dados = dict(NFF=None, **{'Competência': None})
    # a mesma carga vê o projeto em dois meses, com status diferentes
    registrar([linha(**sem_dados, Status='Atrasada')], "2026-10-22T07:49:04", '2026-08')
    registrar([linha(**sem_dados, Status='Pendente')], "2026-10-22T07:49:04", '2026-10')
    # recarga idêntica: nada mudou de verdade, nada pode ser gravado
    n = (registrar([linha(**sem_dados, Status='Atrasada')], "2026-10-22T07:50:04", '2026-08')
         + registrar([linha(**sem_dados, Status='Pendente')], "2026-10-22T07:50:04", '2026-10'))
    assert n == 0


def test_mesmo_mes_do_painel_ainda_detecta_mudanca(db_isolado):
    """A correção não pode cegar o log: dentro do mesmo mês, mudança é mudança."""
    registrar([linha(Status='Pendente')], "2026-10-22T07:49:04", '2026-10')
    n = registrar([linha(Status='Atrasada')], "2026-10-23T07:49:04", '2026-10')
    assert n == 1


def test_meses_diferentes_tem_historicos_independentes(db_isolado):
    registrar([linha(Status='Pendente')], "2026-10-22T08:00:00", '2026-09')
    registrar([linha(Status='Chegou')], "2026-10-22T08:00:00", '2026-10')
    registrar([linha(Status='Atrasada')], "2026-10-23T08:00:00", '2026-09')
    por_mes = {}
    for h in db.buscar_historico(incluir_carga_inicial=True):
        por_mes.setdefault(h['mes_painel'], []).append(h['valor_para'])
    assert por_mes['2026-09'] == ['Atrasada', 'Pendente']
    assert por_mes['2026-10'] == ['Chegou']


def test_adocao_nao_cruza_meses(db_isolado):
    """Órfã de um mês não é adotada pela nota que chegou noutro."""
    registrar([linha(NFF=None, Status='Atrasada')], "2026-10-22T08:00:00", '2026-08')
    registrar([linha(NFF='047744547', Status='Chegou')], "2026-10-22T08:00:00", '2026-10')
    chaves = {(h['mes_painel'], h['nff']) for h in db.buscar_historico(incluir_carga_inicial=True)}
    assert chaves == {('2026-08', ''), ('2026-10', '047744547')}


def test_adocao_funciona_dentro_do_mesmo_mes(db_isolado):
    registrar([linha(NFF=None, Status='Atrasada')], "2026-10-22T08:00:00", '2026-10')
    registrar([linha(NFF='047744547', Status='Chegou')], "2026-10-23T08:00:00", '2026-10')
    status = [h for h in db.buscar_historico(incluir_carga_inicial=True)
              if h['campo'] == 'Status']
    assert (status[0]['valor_de'], status[0]['valor_para']) == ('Atrasada', 'Chegou')


# --- ordem e filtro de mês (regressão do "só aparece 2023") ---
def test_ordem_nao_usa_id_de_insercao(db_isolado):
    """`id` é ordem de INSERÇÃO. Numa carga, todas as linhas têm o mesmo
    `observado_em` e a gravação varre os meses do mais recente ao mais antigo,
    então `ORDER BY id DESC` punha o mês MAIS ANTIGO no topo — com o corte em
    `limite`, a tela só mostrava 2023."""
    for mes in ('2026-10', '2026-09', '2023-07'):   # ordem real da gravação
        registrar([linha(Status='Chegou')], "2026-10-22T08:00:00", mes)
    topo = db.buscar_historico(incluir_carga_inicial=True)[0]
    assert topo['mes_painel'] == '2026-10'


def test_limite_pega_os_meses_recentes(db_isolado):
    for mes in ('2026-10', '2026-09', '2023-07'):
        registrar([linha(Status='Chegou')], "2026-10-22T08:00:00", mes)
    assert {h['mes_painel'] for h in
            db.buscar_historico(limite=1, incluir_carga_inicial=True)} == {'2026-10'}


def test_carga_mais_recente_vem_antes_de_mes_mais_novo(db_isolado):
    """Entre cargas, o que manda é quando foi observado — uma mudança de hoje
    num mês antigo é mais relevante que a carga inicial do mês corrente."""
    registrar([linha(Status='Chegou')], "2026-10-22T08:00:00", '2026-10')
    registrar([linha(Status='Atrasada')], "2026-10-23T08:00:00", '2023-07')
    assert db.buscar_historico(incluir_carga_inicial=True)[0]['mes_painel'] == '2023-07'


def test_filtro_por_mes(db_isolado):
    registrar([linha(Status='Chegou')], "2026-10-22T08:00:00", '2026-10')
    registrar([linha(Status='Atrasada')], "2026-10-22T08:00:00", '2023-07')
    r = db.buscar_historico(incluir_carga_inicial=True, mes_painel='2023-07')
    assert [h['valor_para'] for h in r] == ['Atrasada']


def test_filtro_por_mes_combina_com_busca(db_isolado):
    registrar([linha(Status='Chegou'),
               linha(Projeto='Chui I', ACRONIMO='RS-CHU-01', Status='Chegou')],
              "2026-10-22T08:00:00", '2026-10')
    r = db.buscar_historico('GO-RIQ-01', incluir_carga_inicial=True, mes_painel='2026-10')
    assert {h['acronimo'] for h in r} == {'GO-RIQ-01'}


def test_meses_historico_mais_recente_primeiro(db_isolado):
    for mes in ('2023-07', '2026-10', '2025-01'):
        registrar([linha(Status='Chegou')], "2026-10-22T08:00:00", mes)
    assert db.meses_historico() == ['2026-10', '2025-01', '2023-07']


def test_busca_por_usina_alcanca_todos_os_meses(db_isolado):
    """O objetivo da aba: a linha do tempo da usina não pode ser cortada pelo
    limite por causa de meses de outras usinas."""
    for mes in ('2026-10', '2026-09', '2026-08'):
        registrar([linha(Status='Chegou'),
                   linha(Projeto='Chui I', ACRONIMO='RS-CHU-01', Status='Chegou')],
                  "2026-10-22T08:00:00", mes)
    r = db.buscar_historico('GO-RIQ-01', incluir_carga_inicial=True)
    assert {h['mes_painel'] for h in r} == {'2026-10', '2026-09', '2026-08'}


# --- busca por NFF: grafias do Oracle ---

def test_nff_digitos_normaliza_as_tres_grafias():
    """O Oracle devolve a mesma NFF como '016351936', '17767235.0' e
    '014.492.028'. Todas têm que reduzir ao mesmo número que o usuário digita."""
    assert db.nff_digitos('016351936') == '16351936'
    assert db.nff_digitos('17767235.0') == '17767235'
    assert db.nff_digitos('014.492.028') == '14492028'
    assert db.nff_digitos(None) == ''
    assert db.nff_digitos('000') == ''


@pytest.mark.parametrize('gravado,digitado', [
    ('016351936', '16351936'),   # Oracle corta o zero à esquerda
    ('016351936', '016351936'),
    ('014.492.028', '14492028'),  # usuário digita sem os pontos
    ('014.492.028', '014.492.028'),
])
def test_busca_acha_nff_em_qualquer_grafia(db_isolado, gravado, digitado):
    registrar([linha(NFF=gravado, Status='Chegou')], "2026-10-22T08:00:00")
    r = db.buscar_historico(digitado, incluir_carga_inicial=True)
    assert [h['nff'] for h in r] == [gravado]


def test_busca_por_acronimo_nao_vira_busca_por_digito(db_isolado):
    """'SP-DES-01' tem dígitos dentro. Se o ramo numérico da busca aceitasse
    qualquer termo com dígito, ele reduziria a '1' e o LIKE '%1%' devolveria
    quase toda NFF do banco — 82 acrônimos para quem pediu um."""
    registrar([linha(ACRONIMO='SP-DES-01', NFF='016351936', Status='Chegou'),
               linha(Projeto='Chui I', ACRONIMO='RS-CHU-01', NFF='017767235',
                     Status='Chegou')],
              "2026-10-22T08:00:00")
    r = db.buscar_historico('SP-DES-01', incluir_carga_inicial=True)
    assert {h['acronimo'] for h in r} == {'SP-DES-01'}
