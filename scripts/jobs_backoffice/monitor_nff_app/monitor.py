import os
import sys
import warnings
import requests
import yaml
import pandas as pd
import snowflake.connector as snowflake
from datetime import datetime
from dotenv import load_dotenv

# sobe 2 níveis: monitor_nff_app -> jobs_backoffice -> retail-apps
RETAIL_APPS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(RETAIL_APPS_ROOT)

from utils.utils_usinas import log_error

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable.*")

PROJECT_ROOT = RETAIL_APPS_ROOT  # conf/ e sql/ ficam em retail-apps/

PROJETOS = [
    ['GUI02','PI-GUI-02','Equatorial PI',7,'FW'],
    ['UFV Santa Lucia I','SP-SLU-01','CPFL Paulista',11,'E-MAIL'],
    ['UFV Rincão','SP-RIN-01','CPFL Paulista',15,'E-MAIL'],
    ['UFV Boa Esperança do Sul II','SP-BES-02','CPFL Paulista',12,'E-MAIL'],
    ['UFV Dourado III','SP-DOR-03','CPFL Paulista',12,'E-MAIL'],
    ['UFV Descalvado I','SP-DES-01','CPFL Paulista',14,'E-MAIL'],
    ['UFV Altair I','SP-ALT-01','CPFL Paulista',11,'E-MAIL'],
    ['UFV Morro Agudo 101','SP-ATN-01','CPFL Paulista',19,'E-MAIL'],
    ['UFV Morro Agudo 102','SP-ATN-02','CPFL Paulista',18,'E-MAIL'],
    ['UFV Morro Agudo 103','SP-ATN-03','CPFL Paulista',18,'E-MAIL'],
    ['SERENA 01','PI-SRN-01','Equatorial PI',9,'N/A'],
    ['JUNCO','PI-JCO-01','Equatorial PI',7,'N/A'],
    ['UFV Araraquara IV','SP-ARQ-04','CPFL Paulista',13,'E-MAIL'],
    ['UFV Araraquara III','SP-ARQ-03','CPFL Paulista',19,'E-MAIL'],
    ['UFV Piacatu I','SP-PIA-01','CPFL Paulista',13,'E-MAIL'],
    ['UFV Guapó 1','GO-HLX-01.1','Equatorial GO',20,'E-MAIL'],
    ['UFV Guapó 2','GO-HLX-01.2','Equatorial GO',20,'E-MAIL'],
    ['UFV Guapó 3','GO-HLX-01.3','Equatorial GO',20,'E-MAIL'],
    ['UFV Guapó 4','GO-HLX-01.4','Equatorial GO',20,'E-MAIL'],
    ['UFV Guapó 5','GO-HLX-01.5','Equatorial GO',20,'E-MAIL'],
    ['UFV Miguelópolis','SP-MIG-01','CPFL Paulista',14,'E-MAIL'],
    ['UFV Porangatu I','GO-PRG-01','Equatorial GO',11,'E-MAIL'],
    ['UFV Getulina II','SP-GET-02','CPFL Paulista',18,'E-MAIL'],
    ['SERRA DO RAMALHO','BA-SRR-01','COELBA',20,'E-MAIL'],
    ['UFV SMP 101','PA-ATN-01','Equatorial PA',8,'FW'],
    ['UFV SMP 102','PA-ATN-02','Equatorial PA',8,'FW'],
    ['UFV SMP 103','PA-ATN-03','Equatorial PA',8,'FW'],
    ['UFV SMP 104','PA-ATN-04','Equatorial PA',8,'FW'],
    ['UFV SMP 105','PA-ATN-05','Equatorial PA',8,'FW'],
    ['UFV SMP 106','PA-ATN-06','Equatorial PA',7,'FW'],
    ['UFV SMP 107','PA-ATN-07','Equatorial PA',8,'FW'],
    ['UFV Boa Esperança do Sul V','SP-BES-05','CPFL Paulista',22,'E-MAIL'],
    ['UFV Avanhandava I','SP-AVA-01','CPFL Paulista',19,'E-MAIL'],
    ['UFV GOY 400','RJ-ATN-01','Enel RJ',14,'FW'],
    ['UFV Pompéia II','SP-POM-02','CPFL Paulista',18,'E-MAIL'],
    ['UFV TIM 201','MA-ATN-01','Equatorial MA',8,'FW'],
    ['UFV TIM 202','MA-ATN-02','Equatorial MA',7,'FW'],
    ['UFV TIM 203','MA-ATN-03','Equatorial MA',8,'FW'],
    ['UFV TIM 204','MA-ATN-04','Equatorial MA',9,'FW'],
    ['UFV TIM 205','MA-ATN-05','Equatorial MA',8,'FW'],
    ['UFV CXPO DO OURO','MT-TOV-01','EMT',8,'FW'],
    ['UFV Nova Crixás II','GO-NVC-02','Equatorial GO',10,'E-MAIL'],
    ['UFV Nova Crixás I','GO-NVC-01','Equatorial GO',10,'E-MAIL'],
    ['UFV Minaçu I','GO-MNU-01','Equatorial GO',8,'E-MAIL'],
    ['UFV Cezarina 1','GO-HLX-02.1','Equatorial GO',10,'E-MAIL'],
    ['UFV Cezarina 2','GO-HLX-02.2','Equatorial GO',10,'E-MAIL'],
    ['UFV Cezarina 3','GO-HLX-02.3','Equatorial GO',10,'E-MAIL'],
    ['UFV Cezarina 4','GO-HLX-02.4','Equatorial GO',10,'E-MAIL'],
    ['UFV Cezarina 5','GO-HLX-02.5','Equatorial GO',10,'E-MAIL'],
    # Rio Quente: entraram em operação em jun/jul 2026 e nunca apareceram no painel
    # porque não casavam no MONITORAMENTO_CUSD_AWS (sem CLIENTE_APELIDO no snapshot).
    # A USINAS_GERACAO casa pela UC nova, então agora só faltava a entrada aqui.
    # Dia e forma de recebimento (E-MAIL) informados pela Neiva.
    ['UFV Rio Quente I','GO-RIQ-01','Equatorial GO',15,'E-MAIL'],
    ['UFV Rio Quente II','GO-RIQ-02','Equatorial GO',6,'E-MAIL'],
    ['UFV Rio Quente IV','GO-RIQ-04','Equatorial GO',15,'E-MAIL'],
    ['UFV CPP 101','PA-ATN-08','Equatorial PA',3,'FW'],
    ['UFV CPP 102','PA-ATN-09','Equatorial PA',4,'FW'],
    ['UFV CPP 103','PA-ATN-10','Equatorial PA',4,'FW'],
    ['UFV CPP 104','PA-ATN-11','Equatorial PA',6,'FW'],
    ['UFV CPP 105','PA-ATN-12','Equatorial PA',4,'FW'],
    ['UFV CPP 106','PA-ATN-13','Equatorial PA',4,'FW'],
    ['UFV CPP 107','PA-ATN-14','Equatorial PA',4,'FW'],
    ['UFV GOY 701','RJ-ATN-02','Enel RJ',13,'FW'],
    ['UFV SOLONOPOLE','CE-TOV-01','ENEL CE',13,'FW'],
    ['UFV Venturosa I','PE-VEN-01','CELPE',20,'E-MAIL'],
    ['UFV Apolo Sanharo II','PE-APS-02','CELPE',21,'E-MAIL'],
    ['UFV Aliança I','PE-ALI-01','CELPE',25,'E-MAIL'],
    ['UFV Rio do Antônio I','BA-RAN-01','COELBA',20,'E-MAIL'],
    ['UFV Rio do Antônio II','BA-RAN-02','COELBA',18,'E-MAIL'],
    ['UFV Novo Planalto II','GO-NVP-02','Equatorial GO',25,'E-MAIL'],
    ['UFV Pesqueira I','PE-PES-01','CELPE',21,'E-MAIL'],
    ['UFV Iramaia I','BA-IRM-01','COELBA',23,'E-MAIL'],
    ['UFV Barreiras','BA-BAR-01','COELBA',18,'E-MAIL'],
    ['UFV Beberibe','CE-HLX-02','Enel CE',10,'FW'],
    ['UFV Brejo Madre de Deus I','PE-BMD-01','CELPE',22,'E-MAIL'],
    ['UFV ITABIRA','MG-SUN-01','CEMIG',5,'E-MAIL'],
    ['SERENA 04','PI-SRN-04','Equatorial PI',2,'N/A'],
    ['UFV JCD 101','PA-ATN-15','Equatorial PA',2,'FW'],
    ['UFV JCD 102','PA-ATN-16','Equatorial PA',2,'FW'],
    ['UFV JCD 103','PA-ATN-17','Equatorial PA',2,'FW'],
    ['UFV JCD 104','PA-ATN-18','Equatorial PA',2,'FW'],
    ['UFV JCD 105','PA-ATN-19','Equatorial PA',2,'FW'],
    ['UFV JCD 106','PA-ATN-20','Equatorial PA',2,'FW'],
    ['UFV JCD 107','PA-ATN-21','Equatorial PA',2,'FW'],
    ['UFV JCD 108','PA-ATN-22','Equatorial PA',2,'FW'],
    ['UFV JCD 109','PA-ATN-23','Equatorial PA',2,'FW'],
    ['UFV Novo Planalto I','GO-NVP-01','Equatorial GO',5,'E-MAIL'],
    ['UFV Gravatá','PE-GRA-01','CELPE',20,'E-MAIL']
]

def _init_connections():
    print("[monitor] carregando .env...")
    load_dotenv()
    tenant_id = os.getenv("TENANT_ID")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    if not all([tenant_id, client_id, client_secret]):
        raise ValueError("Variáveis de ambiente Microsoft ausentes (TENANT_ID/CLIENT_ID/CLIENT_SECRET).")

    print("[monitor] solicitando token Microsoft...")
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    token_data = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default'
    }
    r = requests.post(token_url, data=token_data, timeout=15)
    r.raise_for_status()
    access_token = r.json()['access_token']
    print("[monitor] token Microsoft OK")

    sf_account = os.getenv("SF_ACCOUNT")
    sf_user = os.getenv("SF_USERNAME")
    if not sf_account or not sf_user:
        raise ValueError("Variáveis Snowflake ausentes (SF_ACCOUNT/SF_USERNAME).")

    print(f"[monitor] conectando Snowflake (account={sf_account}, user={sf_user})...")
    print("[monitor] >>> vai abrir browser pra autenticar (externalbrowser) <<<")
    conn = snowflake.connect(
        account=sf_account,
        user=sf_user,
        authenticator="externalbrowser",
        warehouse=os.getenv("SF_WAREHOUSE"),
        database=os.getenv("SF_DATABASE"),
        schema=os.getenv("SF_SCHEMA"),
        clientStoreTemporaryCredential=True
    )
    print("[monitor] Snowflake conectado")
    return access_token, conn


def _get_conf():
    with open(os.path.join(PROJECT_ROOT, "conf", "conf_cusd_invoices.yml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _get_query(query_name, model_parameters):
    qp = os.path.join(PROJECT_ROOT, "sql", model_parameters["queries"][query_name])
    with open(qp, "r", encoding="utf-8") as f:
        return f.read()

def _to_naive(series, dayfirst=False):
    """Parseia pra datetime e remove o timezone, se houver.

    A AP_ORACLE_VIEW (RETAIL_DEV) passou a devolver TIMESTAMP com fuso; sem
    normalizar, o DATA_REFERENCIA vira tz-aware e a comparação com o mês
    corrente (tz-naive) quebra com "Cannot compare tz-naive and tz-aware".
    A saída final é só data (%d/%m/%Y), então descartar o fuso é seguro.

    [fix] Segunda passada em ISO8601. A AP_ORACLE_VIEW hoje mistura DOIS
    formatos na mesma coluna: '2026-05-04 11:31:08' nos registros até ~maio/2026
    e '2026-07-21T00:00:00Z' daí em diante. `pd.to_datetime` sem format INFERE o
    padrão da primeira linha não-nula e coage o resto para NaT — como as antigas
    vêm primeiro, TODO pagamento recente virava NaT e a fatura aparecia como não
    paga. A primeira passada continua mandando (preserva o dayfirst brasileiro do
    fattureweb); a segunda só recupera o que sobrou como NaT.
    """
    s = pd.to_datetime(series, errors='coerce', dayfirst=dayfirst)
    if getattr(s.dtype, 'tz', None) is not None:
        s = s.dt.tz_localize(None)

    # Segunda passada só preenche o que ficou NaT. Rodar o parser ISO8601 na série
    # inteira é seguro: data brasileira ('03/04/2026') não é ISO e vira NaT lá, então
    # o fillna nunca sobrescreve o resultado do dayfirst.
    s2 = pd.to_datetime(series, errors='coerce', utc=True, format='ISO8601')
    if getattr(s2.dtype, 'tz', None) is not None:
        s2 = s2.dt.tz_localize(None)

    return s.fillna(s2)


def _fmt_nf(series):
    """Normaliza a coluna de nota fiscal pra servir de chave de merge.

    `.astype(str)` transforma NULL em 'None' e vazio em '' — chaves VÁLIDAS, que
    sobrevivem ao dedup por nota e depois casam entre si no merge, colando uma
    nota nula do monitoramento numa nota nula do fattureweb.

    Devolvendo NaN, o `groupby('NOTA_FISCAL')` do dedup descarta essas linhas
    (chave nula não forma grupo) e elas nunca chegam ao merge. Atenção: o merge
    do pandas casa NaN com NaN — quem resolve é a eliminação no dedup, não a
    normalização sozinha.
    """
    s = series.astype(str).str.strip()
    return s.where(~s.isin(['', 'nan', 'None', 'NaN', '<NA>', 'NaT']))


def _nf_key(series):
    """Chave de JOIN por nota fiscal, tolerante ao lixo de formato: '42937901.0',
    '042937901' e '42937901' são a MESMA nota.

    Usada só como chave — a NFF exibida continua saindo de `_fmt_nf`, intacta (regra
    aditiva: nenhum valor de coluna existente muda).

    Por quê: a NFF passa por float em algum ponto do caminho (ganha '.0' e perde o zero
    à esquerda) e a CPFL usa 9 dígitos com zero à esquerda. As pontas nem sempre sujam
    igual, e aí o merge exato não acha a nota — ou acha a ERRADA. Caso real (GO-MNU-01,
    jun/2026): o monitoramento guarda '194412037' e no Oracle esse número exato é uma
    nota Cancelada de valor 0; a nota boa, paga, está como '194412037.0'.
    """
    s = (
        _fmt_nf(series)
        .str.replace(r'\.0$', '', regex=True)
        .str.replace(r'^0+', '', regex=True)
    )
    # nota que era só zeros virou '' — chave inútil, fora (mesma ideia do _fmt_nf)
    return s.where(s.ne(''))


def _completar_por_chave_normalizada(df, df_fonte, colunas):
    """Preenche `colunas` de `df` nas linhas que o merge EXATO deixou vazias, casando
    por `_nf_key`. Altera `df` no lugar; devolve (linhas_preenchidas, chaves_ambíguas).

    Estritamente ADITIVO: só escreve onde o valor está nulo, então toda linha que já
    casava no merge exato sai idêntica. É um complemento do merge, não um substituto.

    Duas salvaguardas contra casar a nota errada:

    1. Só disputa a chave quem INFORMA algo — linha de origem com todas as `colunas`
       nulas não candidata. É o que resolve o caso GO-MNU-01: a nota Cancelada não tem
       pagamento nem status de parcela, então ela sai da disputa e a chave, que era
       ambígua, passa a ter uma única candidata.
    2. Chave que AINDA aponta pra mais de uma nota de origem é descartada inteira.
       Ficar sem pagamento é bem menos grave que exibir o pagamento de outra fatura.
    """
    fonte = df_fonte.copy()
    fonte['_NF_KEY'] = _nf_key(fonte['NOTA_FISCAL'])
    fonte = fonte.dropna(subset=['_NF_KEY'])
    fonte = fonte[fonte[list(colunas)].notna().any(axis=1)]      # salvaguarda 1

    por_chave = fonte.groupby('_NF_KEY')['NOTA_FISCAL'].nunique()
    ambiguas = int((por_chave > 1).sum())                         # salvaguarda 2
    fonte = (
        fonte[fonte['_NF_KEY'].isin(por_chave[por_chave == 1].index)]
        .drop_duplicates('_NF_KEY')
        .set_index('_NF_KEY')
    )

    chave = _nf_key(df['NOTA_FISCAL'])
    tocadas = pd.Series(False, index=df.index)
    for c in colunas:
        de_fora = chave.map(fonte[c])
        preencher = df[c].isna() & de_fora.notna()
        df.loc[preencher, c] = de_fora[preencher]
        tocadas |= preencher
    return int(tocadas.sum()), ambiguas


def _fmt_uc(v):
    """Normaliza a UC (Unidade Consumidora).

    Vem do fattureweb como NUMERO_DA_INSTALACAO e pode chegar como float
    (ex.: 12345.0); devolve string sem o ".0" (e None quando ausente).
    """
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s[:-2] if s.endswith('.0') else s


# Ordem dos degraus das duas cascatas de data. Explícita e lado a lado porque a diferença
# entre elas é PROPOSITAL — ver _cascata_datas.
DEGRAUS_MES     = ['DATA_DA_APRESENTACAO_DA_FATURA', 'DATA_APRES_FW', 'MES_REF_FW',      'DATA_INVOICE']
DEGRAUS_CHEGADA = ['DATA_DA_APRESENTACAO_DA_FATURA', 'DATA_APRES_FW', 'DATA_EMISSAO_FW', 'DATA_INVOICE']


def _cascata_datas(df, com_monitoramento=True):
    """Preenche DATA_REFERENCIA e DATA_CHEGADA. Altera `df` no lugar e devolve.

    São DUAS perguntas diferentes que antes compartilhavam a mesma resposta (`Data
    Chegada` era literalmente a DATA_REFERENCIA):

      DATA_REFERENCIA -> "de que MÊS é esta fatura?"  (define em que mês ela aparece)
      DATA_CHEGADA    -> "QUANDO ela chegou?"          (o que o painel exibe, e o Status usa)

    Por isso os dois últimos degraus divergem:

    - No MÊS, a competência (MES_REF_FW) vem ANTES do INVOICEDATE do Oracle. O INVOICEDATE
      é data de LANÇAMENTO contábil e, pra distribuidora com lag de emissão, jogava a
      fatura no mês seguinte: a CELPE leva ~40-47 dias entre competência e emissão, então
      competência 05 e 06 caíam as DUAS em julho. O mês de competência ficava vazio (falso
      "Atrasada" sem NFF) e o mês seguinte recebia duas faturas do mesmo acrônimo, onde o
      tail(1) descartava uma — 17 faturas invisíveis em 2026 (CELPE 12, COELBA 4, CEPISA 1).

    - Na CHEGADA entra a EMISSÃO do FattureWeb, e a competência NÃO entra: competência é
      sempre dia 1º, seria uma data de chegada falsa. Emissão é quando a distribuidora
      emitiu de fato (PE-VEN-01, competência 06/2026 -> emitida 10/07/2026).

    Quem preenche apresentação (CPFL, Equatorial...) para no 1º/2º degrau nas DUAS
    cascatas — pra essas distribuidoras nada muda.

    `com_monitoramento=False` no suplemento FW, que por definição não tem a apresentação
    do monitoramento.
    """
    def _primeiro_preenchido(degraus):
        if not com_monitoramento:
            degraus = [c for c in degraus if c != 'DATA_DA_APRESENTACAO_DA_FATURA']
        s = df[degraus[0]]
        for c in degraus[1:]:
            s = s.fillna(df[c])
        return s

    df['DATA_REFERENCIA'] = _primeiro_preenchido(DEGRAUS_MES)
    df['DATA_CHEGADA'] = _primeiro_preenchido(DEGRAUS_CHEGADA)
    return df


def _depara_uc_por_endereco(df_uc_end, uc_to_acronimo):
    """Estende o de/para UC->ACRONIMO para UC que TROCOU DE CÓDIGO na distribuidora.
    Devolve (novos_pares, endereços_ambíguos_descartados) — não altera o dict recebido.

    O problema: a CPFL migrou as UCs pro padrão ANEEL na competência 06/2026. As antigas
    ('4003…', 10 díg.) param em maio, as novas ('55x/56x', 12 díg.) começam em junho, e
    NENHUMA fonte de de/para cobre a virada. Todas foram checadas e estão vazias:
    monitoramento_hist_usina (não tem UC de 12 díg.), FATTUREWEB_INSTALACOES.CODIGO_ANTIGO
    (8.831 instalações CPFL, ZERO preenchidas), CONSUMER_UNIT_ALIAS do SIGMA (só UC de
    cliente, não de geradora), FATTUREWEB_USINAS.CONTRATO (vazio desde 09/2025) e
    DESCRIPTION/UNIDADE_CONSUMIDORA do Oracle (vazios nessas notas). Sem de/para, a fatura
    não pode ser posicionada no projeto e a usina aparece como falso "Atrasada" sem NFF.

    O que resolve: o ENDEREÇO da instalação, que o próprio FattureWeb já traz. Ele é
    IDÊNTICO antes e depois da troca — é a mesma usina no mesmo lugar. Então a UC antiga,
    que tem acrônimo, empresta o acrônimo pro endereço, e a UC nova o herda. Nenhuma fonte
    nova entra no pipeline. Desambigua até casos finos: em Araraquara, 'CRT 166A' é a
    SP-ARQ-03 e 'CRT 166B' a SP-ARQ-04.

    Duas salvaguardas — na dúvida, melhor a usina seguir sem fatura do que exibir a fatura
    de OUTRA usina:
    1. endereço que aponta pra mais de um acrônimo fica de fora (SP-ATN-01 e SP-ATN-02
       dividem literalmente o mesmo endereço em Morro Agudo);
    2. UC cujos endereços levem a acrônimos diferentes também fica de fora.
    """
    d = df_uc_end.copy()
    d['UC'] = d['UC'].apply(_fmt_uc)
    # normalização leve: caixa, bordas e espaços repetidos. De propósito NÃO mexe em
    # pontuação — 'TP - TP -' e 'TP TP' são endereços de usinas DIFERENTES em Morro Agudo,
    # e achatar isso colaria as duas.
    d['_END'] = (
        d['ENDERECO'].astype(str).str.upper().str.strip()
        .str.replace(r'\s+', ' ', regex=True)
    )
    d = d.dropna(subset=['UC'])
    d = d[~d['_END'].isin(['', 'NAN', 'NONE', '<NA>'])].drop_duplicates(['UC', '_END'])

    d['_ACR'] = d['UC'].map(uc_to_acronimo)

    conhecidas = d[d['_ACR'].notna()]
    por_end = conhecidas.groupby('_END')['_ACR'].nunique()
    ambiguos = int((por_end > 1).sum())                                   # salvaguarda 1
    end_to_acr = (
        conhecidas[conhecidas['_END'].isin(por_end[por_end == 1].index)]
        .drop_duplicates('_END').set_index('_END')['_ACR']
    )

    orfas = d[d['_ACR'].isna()].copy()
    orfas['_ACR_NOVO'] = orfas['_END'].map(end_to_acr)
    orfas = orfas.dropna(subset=['_ACR_NOVO'])
    por_uc = orfas.groupby('UC')['_ACR_NOVO'].nunique()                   # salvaguarda 2
    novos = (
        orfas[orfas['UC'].isin(por_uc[por_uc == 1].index)]
        .drop_duplicates('UC').set_index('UC')['_ACR_NOVO'].to_dict()
    )
    return novos, ambiguos


def _status(row, hoje_date):
    """Status da fatura de um projeto no mês corrente.

    Se já chegou: 'Chegou' (no prazo) ou 'Chegou atrasada' (depois da data
    esperada). Se não chegou: 'Pendente' (ainda dentro do prazo) ou 'Atrasada'.
    """
    if pd.notna(row['Data Chegada']):
        return 'Chegou' if row['Data Chegada'].date() <= row['Data Esperada'].date() else 'Chegou atrasada'
    return 'Pendente' if row['Data Esperada'].date() >= hoje_date else 'Atrasada'


def _dias_para_vencer(row, hoje_date):
    """Dias até a data esperada (negativo se já passou). None se a fatura já chegou."""
    if pd.notna(row['Data Chegada']):
        return None
    return int((row['Data Esperada'].date() - hoje_date).days)


# Blocos de coluna que o resto do pipeline espera de cada fonte de pagamento. Explícitos
# porque a query recortada devolve os DOIS blocos na mesma linha e eles precisam sair
# separados: se STATUS_INSTALLMENT viajasse dentro de df_pag, o merge de df_inst mais
# adiante criaria sufixos _x/_y e o 3º degrau de pagamento pararia de ser lido.
COLS_PAG = ['NOTA_FISCAL', 'FATURA_VALOR', 'DATA_DE_PAGAMENTO', 'DATA_INVOICE']
COLS_INST = ['NOTA_FISCAL', 'STATUS_INSTALLMENT', 'DATA_STATUS_INSTALLMENT']


def _prep_pag(df):
    """Tipa e deduplica o bloco de PAGAMENTO (AP_PAYMENTS).

    na_position='first' é obrigatório: o default do pandas joga NaT pro FIM, e o
    tail(1) acabaria elegendo justamente a linha SEM data de pagamento quando a
    mesma nota tem uma linha paga e outra não — a fatura aparecia como não paga.
    """
    df = df[COLS_PAG].copy()
    df['DATA_DE_PAGAMENTO'] = _to_naive(df['DATA_DE_PAGAMENTO'])
    df['DATA_INVOICE'] = _to_naive(df['DATA_INVOICE'])
    df['NOTA_FISCAL'] = _fmt_nf(df['NOTA_FISCAL'])
    return df.sort_values(
        'DATA_DE_PAGAMENTO', na_position='first'
    ).groupby('NOTA_FISCAL', as_index=False).tail(1)


def _prep_inst(df):
    """Tipa e deduplica o bloco de PARCELA (AP_INSTALLMENTS), guardando só a evidência
    POSITIVA de pagamento.

    O filtro por 'Totalmente paga' serve aos dois caminhos: na query recortada ele é o
    que separa as linhas com parcela paga das demais (que vêm com NULL no CASE), e na
    query antiga é no-op — lá o WHERE já filtrou no servidor.
    """
    df = df[COLS_INST].copy()
    df['NOTA_FISCAL'] = _fmt_nf(df['NOTA_FISCAL'])
    df['DATA_STATUS_INSTALLMENT'] = _to_naive(df['DATA_STATUS_INSTALLMENT'])
    df = df[df['STATUS_INSTALLMENT'].eq('Totalmente paga')]
    # 1 linha por INVOICENUMBER na origem; dropna/drop_duplicates é blindagem da chave
    return df.dropna(subset=['NOTA_FISCAL']).drop_duplicates('NOTA_FISCAL')


def _carregar_pagamentos(conn, mp):
    """Lê pagamento + status de parcela do Oracle. Devolve (df_pag, df_inst).

    [perf] UMA leitura da AP_ORACLE_VIEW, recortada nas notas das usinas
    (stg_pagamentos_usinas.sql). Antes eram DUAS leituras da view inteira e o custo era
    quase todo desperdício — medição de 05/08/2026:

        stg_pagamentos.sql              1.004.303 linhas
        stg_pagamentos_installment.sql    975.691 linhas  ('Totalmente paga' é 97% da view)
        de fato usadas                      1.113 linhas

    Ou seja ~2 milhões de linhas trafegadas e desempacotadas em pandas pra usar 1.113
    (0,06%), e a ap_oracle_view é `materialized='view'` sobre três QUALIFY ROW_NUMBER()
    — era recalculada duas vezes por abertura do app. Era esse o gargalo do startup, não
    o tamanho do histórico: 580.959 das 1.004.303 linhas já são >= 2025, então cortar por
    data resolveria pouco (e INVOICEDATE é TEXT de formato misto).

    O fallback repete o caminho ANTIGO (duas queries, AP inteira) e existe por dois
    motivos: a query nova depende de colunas que são recentes na view (se o build dela
    não rodou, ela falha inteira, e aí perder o pagamento junto seria pior), e ela cruza
    com MONITORAMENTO_CUSD_AWS/FATTUREWEB_USINAS — um grant faltando ali não pode derrubar
    o monitor. Dentro do fallback, a parcela segue sendo degrau opcional como antes.
    """
    print("[monitor] carregando pagamentos + parcela (V_AP_ORACLE_NOVO_PIPE, recorte usinas)...", flush=True)
    try:
        df = pd.read_sql(_get_query("pagamentos_usinas", mp), conn)
        df.columns = df.columns.str.upper().str.strip()
        df_pag, df_inst = _prep_pag(df), _prep_inst(df)
        print(
            f"[monitor] {len(df_pag)} pagamentos e {len(df_inst)} parcelas "
            f"'Totalmente paga' em 1 query ({len(df)} linhas lidas da view)",
            flush=True
        )
        return df_pag, df_inst
    except Exception as e:
        print(
            f"[monitor] AVISO: query recortada indisponível ({type(e).__name__}: {e}). "
            "Caindo pro caminho antigo: AP inteira em 2 queries (startup fica lento).",
            flush=True
        )

    df = pd.read_sql(_get_query("pagamentos", mp), conn)
    df.columns = df.columns.str.upper().str.strip()
    df_pag = _prep_pag(df)
    print(f"[monitor] {len(df_pag)} pagamentos carregados", flush=True)

    print("[monitor] carregando status de parcela (AP_INSTALLMENTS)...", flush=True)
    try:
        df_i = pd.read_sql(_get_query("pagamentos_installment", mp), conn)
        df_i.columns = df_i.columns.str.upper().str.strip()
        df_inst = _prep_inst(df_i)
        print(f"[monitor] {len(df_inst)} faturas 'Totalmente paga' na parcela", flush=True)
    except Exception as e:
        print(
            f"[monitor] AVISO: status de parcela indisponível ({type(e).__name__}: {e}). "
            "A ap_oracle_view provavelmente ainda não expõe STATUS_PAGAMENTO_INSTALLMENT — "
            "rode o build da view. Pagamento segue só por AP_PAYMENTS + monitoramento_cusd_aws.",
            flush=True
        )
        df_inst = pd.DataFrame(columns=COLS_INST)

    return df_pag, df_inst


def carregar_base():
    """Parte cara do pipeline: conecta, roda as queries e devolve o
    `df_merged` (já com DATA_REFERENCIA) + o `df_projetos` estático.

    NÃO recorta mês — quem fatia é `montar_mes()`. É feito pra ser cacheado e
    reaproveitado entre trocas de mês, evitando re-consultar o Snowflake (que
    reautentica no browser e roda vários read_sql) só pra olhar outro mês dos
    MESMOS dados. As queries não filtram data no servidor, então a base já traz
    todo o histórico disponível — o recorte que existe é de ESCOPO, não de período
    (só notas de usina; ver _carregar_pagamentos).
    """
    conf = _get_conf()
    mp = conf['model_parameters']
    _, conn = _init_connections()

    query = _get_query("job_monitoramento", mp)
    df_faturas = pd.read_sql(query, conn)
    df_faturas.columns = df_faturas.columns.str.upper().str.strip()

    # parsing flexível: aceita string '%d/%m/%Y', ISO '%Y-%m-%d', e datetime já tipado
    df_faturas['DATA_DA_APRESENTACAO_DA_FATURA'] = _to_naive(
        df_faturas['DATA_DA_APRESENTACAO_DA_FATURA'], dayfirst=True
    )
    # PAGAMENTO (monitoramento_cusd_aws) é uma data %d/%m/%Y ('' quando não pago).
    # Fonte de pagamento mais fresca que a AP_ORACLE_VIEW — usada como fallback abaixo
    # pra fechar a janela em que o pagamento já ocorreu mas ainda não entrou no Oracle.
    df_faturas['PAGAMENTO'] = _to_naive(df_faturas['PAGAMENTO'], dayfirst=True)
    print(f"[monitor] df_faturas: {len(df_faturas)} linhas, NaT em DATA_APRES: {df_faturas['DATA_DA_APRESENTACAO_DA_FATURA'].isna().sum()}", flush=True)

    # Pagamento (AP_PAYMENTS) + status da parcela (AP_INSTALLMENTS), as duas evidências
    # de "essa fatura foi paga?". A AP_PAYMENTS não é a única porta: quando o Oracle quita
    # a parcela e o pagamento não chega naquela tabela, PAYMENT_DATE fica nulo e a fatura
    # aparece como "A pagar" mesmo paga (jun/2026: 2.372 faturas, 4 das 6 usinas do mês).
    # Vêm da mesma leitura da view, já separadas em dois blocos — ver _carregar_pagamentos.
    df_pag, df_inst = _carregar_pagamentos(conn, mp)

    print("[monitor] carregando faturamento (FATTUREWEB_USINAS)...", flush=True)
    query_fw = _get_query("fattureweb_usinas", mp)
    df_fw = pd.read_sql(query_fw, conn)
    df_fw.columns = df_fw.columns.str.upper().str.strip()
    df_fw['NOTA_FISCAL'] = _fmt_nf(df_fw['NOTA_FISCAL'])
    df_fw['DATA_DA_APRESENTACAO_DA_FATURA'] = _to_naive(
        df_fw['DATA_DA_APRESENTACAO_DA_FATURA'], dayfirst=True
    )
    # MES_DE_REFERENCIA (competência, ex.: 01/06/2026) — última âncora de mês pra
    # distribuidoras que não preenchem apresentação (CELPE/COELBA/CEMIG) e cuja nota
    # nem sempre está no Oracle. Sem isso a fatura fica sem DATA_REFERENCIA e some do
    # recorte de mês (vira falso "Atrasada" com NFF/UC em branco).
    df_fw['MES_REF_FW'] = _to_naive(df_fw['MES_DE_REFERENCIA_DA_FATURA'], dayfirst=True)
    # [add] Emissão da fatura pela distribuidora. É a melhor DATA DE CHEGADA disponível
    # quando ninguém preenche apresentação (CELPE/COELBA/CEMIG): a fatura de competência
    # 06/2026 da PE-VEN-01 foi emitida em 10/07/2026 e essa é a data real de chegada.
    # Não confundir com MES_REF_FW (competência, sempre dia 1º) nem com o INVOICEDATE do
    # Oracle (lançamento contábil, que pode ser bem depois — 27/07 pra fatura de 14/07).
    df_fw['DATA_EMISSAO_FW'] = _to_naive(df_fw['DATA_DE_EMISSAO_DA_FATURA'], dayfirst=True)
    # mantém o registro mais recente por NFF.
    # na_position='first' pelo mesmo motivo do df_pag: com o default, uma nota que
    # tem duas linhas no fattureweb (uma com apresentação, outra sem) elegia a SEM
    # apresentação, zerando o DATA_APRES_FW. A cascata de DATA_REFERENCIA então caía
    # pro degrau seguinte e a fatura ganhava Data Chegada/Status errados.
    df_fw = df_fw.sort_values(
        'DATA_DA_APRESENTACAO_DA_FATURA', na_position='first'
    ).groupby('NOTA_FISCAL', as_index=False).tail(1)
    df_fw_keep = df_fw[['NOTA_FISCAL','DATA_DA_APRESENTACAO_DA_FATURA','NUMERO_DA_INSTALACAO',
                        'MES_REF_FW','DATA_EMISSAO_FW','ENDERECO','FATURA_ID','TOTAL_DA_FATURA']].rename(
        columns={'DATA_DA_APRESENTACAO_DA_FATURA': 'DATA_APRES_FW', 'NUMERO_DA_INSTALACAO': 'UC'}
    )
    print(f"[monitor] {len(df_fw_keep)} faturas no fattureweb_usinas", flush=True)

    df_projetos = pd.DataFrame(
        PROJETOS,
        columns=['Projeto','ACRONIMO','Distribuidora','Dia','Forma Recebimento']
    )
    # Escopo do dashboard: usinas FW (Fattureweb) + E-MAIL. N/A fica de fora (fluxo
    # manual, sem NFF rastreável). Nem toda distribuidora de E-MAIL sobe pro
    # monitoramento_cusd_aws ainda (CELPE/COELBA/CEMIG), então esses acrônimos podem
    # aparecer como "sem fatura" até começarem a ser ingeridos.
    df_projetos = df_projetos[df_projetos['Forma Recebimento'].isin(['FW', 'E-MAIL'])].copy()
    df_projetos['ACRONIMO'] = df_projetos['ACRONIMO'].str.strip()
    print(f"[monitor] {len(df_projetos)} projetos FW em monitoramento", flush=True)

    # Estratégia: cruzar monitoramento_cusd_aws com AP_ORACLE_VIEW por NFF ANTES do filtro,
    # pra ter DATA_INVOICE do Oracle como fallback de "qual mês é essa fatura".
    # Várias distribuidoras (COELBA, CEMIG, CELPE) não preenchem DATA_APRESENTACAO,
    # então sem o Oracle a gente não sabe que mês é a fatura.
    df_faturas = df_faturas.copy()
    df_faturas['ACRONIMO'] = df_faturas['ACRONIMO'].astype(str).str.strip()
    df_faturas['NOTA_FISCAL'] = _fmt_nf(df_faturas['NOTA_FISCAL'])

    df_merged = df_faturas.merge(df_fw_keep, on='NOTA_FISCAL', how='left')
    df_merged = df_merged.merge(df_pag, on='NOTA_FISCAL', how='left')

    df_merged = _cascata_datas(df_merged)

    n_apres = df_merged['DATA_DA_APRESENTACAO_DA_FATURA'].notna().sum()
    n_fw = df_merged['DATA_APRES_FW'].notna().sum()
    n_invoice = df_merged['DATA_INVOICE'].notna().sum()
    n_mesref = df_merged['MES_REF_FW'].notna().sum()
    n_emissao = df_merged['DATA_EMISSAO_FW'].notna().sum()
    n_ref = df_merged['DATA_REFERENCIA'].notna().sum()
    n_cheg = df_merged['DATA_CHEGADA'].notna().sum()
    print(f"[monitor] cobertura: APRES_mon={n_apres}, APRES_fw={n_fw}, EMISSAO_fw={n_emissao}, INVOICE_oracle={n_invoice}, MES_REF_fw={n_mesref}, REFERENCIA={n_ref}/{len(df_merged)}, CHEGADA={n_cheg}/{len(df_merged)}", flush=True)

    # ------------------------------------------------------------------
    # [add] Suplemento FW+Oracle — resgata faturas que NÃO entraram no
    # monitoramento_cusd_aws.
    #
    # O merge acima é ancorado no monitoramento (df_faturas à esquerda), então
    # uma nota que chegou por e-mail, foi cadastrada no FattureWeb e paga no
    # Oracle mas nunca subiu pro monitoramento fica invisível — o projeto aparece
    # como "Atrasada" com NFF/UC em branco (falso-negativo típico de
    # CELPE/COELBA/CEMIG, ver comentário do escopo acima). Aqui trazemos essas
    # notas de volta como linhas ADITIVAS.
    #
    # O gargalo é o ACRONIMO: só o monitoramento amarra nota->projeto. Resolvemos
    # aprendendo um de/para UC->ACRONIMO a partir dos próprios dados já cruzados
    # (linhas onde a nota passou pelo monitoramento no passado, casando o ACRONIMO
    # do monitoramento com a UC do FattureWeb). Nenhuma fonte nova é introduzida.
    #
    # Aditividade: cada linha suplementar carrega FONTE='FW_SUPLEMENTO', e
    # montar_mes faz o monitoramento SEMPRE vencer dentro do mesmo ACRONIMO/mês.
    # Logo, todo (ACRONIMO, mês) que já tinha linha de monitoramento sai idêntico;
    # só (ACRONIMO, mês) hoje vazios passam a exibir a nota resgatada.
    df_merged['FONTE'] = 'MONITORAMENTO'

    # de/para UC->ACRONIMO de duas fontes, unidas:
    #  (1) monitoramento_hist_usina (query hist_usina_livia) — o CADASTRO de usinas,
    #      mesma fonte que o monit_hist_usina.py usa; traz NUMERO_DA_INSTALACAO +
    #      ACRONIMO pra TODA usina, inclusive as que nunca passaram pelo
    #      monitoramento_cusd_aws (CELPE/COELBA/CEMIG). É o que faltava pra
    #      posicionar as faturas resgatadas no projeto certo.
    #  (2) aprendido do próprio df_merged (ACRONIMO do mon x UC do FW), como reforço.
    # UC que mapeie pra >1 ACRONIMO (ambígua, ou fontes discordantes) fica de fora.
    df_hist = pd.read_sql(_get_query("hist_usina_livia", mp), conn)
    df_hist.columns = df_hist.columns.str.upper().str.strip()
    link_hist = df_hist[['NUMERO_DA_INSTALACAO', 'ACRONIMO']].rename(
        columns={'NUMERO_DA_INSTALACAO': 'UC'}
    )
    link_learn = df_merged.loc[df_merged['ACRONIMO'].notna(), ['UC', 'ACRONIMO']]

    link = pd.concat([link_hist, link_learn], ignore_index=True)
    link['UC'] = link['UC'].apply(_fmt_uc)
    link['ACRONIMO'] = link['ACRONIMO'].astype(str).str.strip()
    link = link.dropna(subset=['UC'])
    link = link[~link['ACRONIMO'].isin(['', 'nan', 'None', '<NA>'])]
    n_por_uc = link.groupby('UC')['ACRONIMO'].nunique()
    ucs_ok = n_por_uc[n_por_uc == 1].index
    uc_to_acronimo = (
        link[link['UC'].isin(ucs_ok)]
        .drop_duplicates('UC')
        .set_index('UC')['ACRONIMO']
        .to_dict()
    )
    ucs_ambiguas = int((n_por_uc > 1).sum())
    print(f"[monitor] de/para UC->ACRONIMO: {len(uc_to_acronimo)} UCs (hist_usina={len(link_hist)} linhas; {ucs_ambiguas} UCs ambíguas descartadas)", flush=True)

    #  (3) por ENDEREÇO do FattureWeb — resgata UC que TROCOU DE CÓDIGO na distribuidora
    #      (migração da CPFL pro padrão ANEEL em 06/2026). Ver _depara_uc_por_endereco:
    #      o endereço não muda quando o número muda, então a UC antiga empresta o acrônimo
    #      pro endereço e a nova herda. Roda DEPOIS das fontes 1 e 2 e só preenche UC que
    #      elas não cobriram — nenhum par existente é sobrescrito.
    novos_por_end, end_ambiguos = _depara_uc_por_endereco(
        df_fw_keep[['UC', 'ENDERECO']], uc_to_acronimo
    )
    uc_to_acronimo.update(novos_por_end)
    print(f"[monitor] de/para por ENDEREÇO: +{len(novos_por_end)} UCs que trocaram de código ({end_ambiguos} endereços ambíguos descartados)", flush=True)

    # Nota sem número não é rastreável nem casa com o monitoramento — fica de fora
    # do suplemento em vez de virar uma linha órfã sem NFF.
    nffs_no_mon = set(df_merged['NOTA_FISCAL'].dropna())
    df_supl = df_fw_keep[
        df_fw_keep['NOTA_FISCAL'].notna()
        & ~df_fw_keep['NOTA_FISCAL'].isin(nffs_no_mon)
    ].copy()
    df_supl['ACRONIMO'] = df_supl['UC'].apply(_fmt_uc).map(uc_to_acronimo)
    n_fw_fora = len(df_supl)
    df_supl = df_supl[df_supl['ACRONIMO'].notna()].copy()  # sem de/para, não dá pra posicionar no projeto
    df_supl = df_supl.merge(df_pag, on='NOTA_FISCAL', how='left')  # pagamento Oracle por NFF
    df_supl = _cascata_datas(df_supl, com_monitoramento=False)
    df_supl['PAGAMENTO'] = pd.NaT  # PAGAMENTO só existe no monitoramento_cusd_aws
    df_supl['FONTE'] = 'FW_SUPLEMENTO'
    print(f"[monitor] suplemento FW+Oracle: {len(df_supl)}/{n_fw_fora} faturas fora do monitoramento resgatadas (resto sem de/para de UC)", flush=True)

    df_merged = pd.concat([df_merged, df_supl], ignore_index=True)

    # Status de parcela entra DEPOIS do concat de propósito: assim vale igualmente para as
    # linhas de monitoramento e para as suplementares. As suplementares dependem mais dele —
    # ali PAGAMENTO é NaT por construção, então AP_PAYMENTS era a única fonte de pagamento
    # (foi o caso da BA-RAN-01 em junho: paga na parcela, sem PAYMENT_DATE, e por vir do
    # suplemento não tinha nem o PAGAMENTO do monitoramento pra salvar).
    df_merged = df_merged.merge(df_inst, on='NOTA_FISCAL', how='left')

    # ------------------------------------------------------------------
    # [add] 2º passe de chave: recupera pagamento quando as pontas escreveram a MESMA
    # nota de formas diferentes ('.0' no fim, zero à esquerda). O merge exato acima
    # continua mandando; aqui só preenchemos o que ele deixou vazio.
    #
    # Restrito às colunas de PAGAMENTO de propósito. DATA_INVOICE fica de fora porque
    # alimenta a cascata de DATA_REFERENCIA — completá-la MOVERIA faturas de mês no
    # painel, o que não é aditivo e é decisão separada.
    #
    n_pag, amb_pag = _completar_por_chave_normalizada(
        df_merged, df_pag, ['DATA_DE_PAGAMENTO']
    )
    # [fix] FATURA_VALOR pela mesma chave normalizada, em chamada SEPARADA da data.
    #
    # Era o que faltava pro 'Valor Oracle' aparecer em NFF com ZERO À ESQUERDA: o merge
    # exato falha nessas notas (o monitoramento guarda '047744547', o Oracle '47744547'),
    # então quem as recupera é este passe — e recuperando só a data, a fatura saía "paga"
    # com o valor em branco. Foi o padrão que apareceu no painel: das NFF exibidas, só as
    # sem zero à esquerda traziam valor.
    #
    # SEPARADA de propósito, não junto na lista acima. A salvaguarda 1 exige que a linha
    # de origem informe ALGUMA das colunas pedidas, e FATURA_VALOR vem preenchido em toda
    # linha de AP — inclusive na nota Cancelada do GO-MNU-01, que hoje é eliminada
    # justamente por não ter pagamento nem parcela. Na mesma chamada ela voltaria à disputa,
    # a chave viraria ambígua outra vez e o pagamento que hoje é recuperado se perderia.
    # Em chamada própria, o pior caso fica contido no valor: chave ambígua descarta o
    # VALOR (que fica '—', investigável) sem tocar na data de pagamento.
    n_val, amb_val = _completar_por_chave_normalizada(
        df_merged, df_pag, ['FATURA_VALOR']
    )
    n_inst_key, amb_inst = _completar_por_chave_normalizada(
        df_merged, df_inst, ['STATUS_INSTALLMENT', 'DATA_STATUS_INSTALLMENT']
    )
    print(
        f"[monitor] 2º passe de chave: +{n_pag} pagamentos, +{n_val} valores de fatura, "
        f"+{n_inst_key} status de parcela "
        f"({amb_pag + amb_val + amb_inst} chaves ambíguas descartadas)",
        flush=True
    )

    n_inst = int(df_merged['STATUS_INSTALLMENT'].eq('Totalmente paga').sum())
    n_so_inst = int((
        df_merged['STATUS_INSTALLMENT'].eq('Totalmente paga')
        & df_merged['DATA_DE_PAGAMENTO'].isna()
        & df_merged['PAGAMENTO'].isna()
    ).sum())
    print(f"[monitor] parcela paga: {n_inst} faturas ({n_so_inst} só por essa fonte)", flush=True)

    return df_merged, df_projetos


def listar_meses(df_merged, hoje=None):
    """Meses (ano/mês) em que alguma fatura CHEGOU + o corrente, mais recente
    primeiro. Alimenta o seletor de mês da UI; o mês corrente entra sempre,
    mesmo sem fatura ainda, pra poder ser o default.

    Usa a mesma coluna que `montar_mes` recorta (DATA_CHEGADA) — senão o seletor
    ofereceria mês sem nenhuma chegada e esconderia mês que teve. Cai na
    DATA_REFERENCIA quando a base não tem DATA_CHEGADA (fixture antiga).
    """
    hoje = hoje or datetime.today()
    col = 'DATA_CHEGADA' if 'DATA_CHEGADA' in df_merged.columns else 'DATA_REFERENCIA'
    ref = df_merged[col].dropna()
    pares = {(int(t.year), int(t.month)) for t in ref}
    pares.add((hoje.year, hoje.month))
    return [{"ano": a, "mes": m} for (a, m) in sorted(pares, reverse=True)]


def montar_mes(df_merged, df_projetos, ano=None, mes=None, hoje=None):
    """Recorta um mês do `df_merged` (default = corrente) e monta a lista de
    dicts de saída — mesmas colunas de antes, mais 3 aditivas no fim.

    - `Data Esperada` é calculada pro mês ESCOLHIDO (ano/mes), não pra hoje.
    - `Status`/`Dias Restantes` continuam medidos contra hoje: uma fatura de um
      mês passado que nunca chegou aparece como "Atrasada" (leitura correta),
      e uma que chegou aparece "Chegou/Chegou atrasada" pela Data Esperada do
      próprio mês.

    Puro pandas, sem rede — feito pra rodar a cada troca de mês sobre a base
    cacheada por `carregar_base()`.

    [fix] O MÊS DA ABA É O DE CHEGADA (`DATA_CHEGADA`), não o de referência.

    O painel responde uma pergunta operacional — "o que eu tinha pra receber neste
    mês?" — e o `Dia` de PROJETOS sempre foi calibrado pro mês em que a fatura
    CHEGA. Recortar por `DATA_REFERENCIA` (que para CELPE/COELBA/CEMIG é a
    COMPETÊNCIA) cobrava a fatura no mês da competência, e essas distribuidoras
    emitem 31-57 dias depois dela. Consequência medida em 205 faturas de histórico
    dessas 12 usinas:

        âncora na competência -> 0 de 205 no prazo   (0,0%)
        âncora na chegada     -> 134 de 205 no prazo (65,4%)

    Os 0,0% eram artefato da âncora, não régua apertada: a fatura de competência M
    chega em M+1 e é lá que o `Dia` a espera. O sintoma era a aba do mês corrente
    sempre vazia e vermelha — jul/2026 mostrava 12 "Atrasada" com NFF/UC em branco
    enquanto as 12 faturas já tinham chegado (01/07 a 17/07), todas dentro do prazo
    e 8 pagas, arquivadas na aba de JUNHO como "Chegou atrasada".

    Não é aditivo para quem tem lag: essas linhas MUDAM de mês (é o objetivo). Para
    quem preenche apresentação (CPFL, Equatorial, Enel) nada muda — as duas cascatas
    de `_cascata_datas` compartilham os dois primeiros degraus, então ali
    DATA_CHEGADA == DATA_REFERENCIA e o recorte cai no mesmo mês de antes.

    A competência não se perde: sai na coluna nova `Competência`, que é o que
    permite ver uma competência PULADA agora que a aba é por chegada.
    """
    hoje = hoje or datetime.today()
    ano = ano or hoje.year
    mes = mes or hoje.month

    # Data Esperada é relativa ao mês selecionado (Dia máximo em PROJETOS é 25,
    # então datetime(ano, mes, Dia) é sempre válido).
    df_projetos = df_projetos.copy()
    df_projetos['Data Esperada'] = df_projetos['Dia'].apply(
        lambda d: datetime(ano, mes, d)
    )

    # Colunas que podem faltar em fixtures antigas ou quando um degrau está desligado.
    # Precisam existir ANTES do recorte porque agora é a DATA_CHEGADA que define o mês.
    # Sem DATA_CHEGADA cai na DATA_REFERENCIA — exatamente o comportamento anterior.
    df_merged = df_merged.copy()
    if 'DATA_CHEGADA' not in df_merged.columns:
        df_merged['DATA_CHEGADA'] = df_merged['DATA_REFERENCIA']
    if 'MES_REF_FW' not in df_merged.columns:
        df_merged['MES_REF_FW'] = pd.NaT

    mes_inicio = pd.Timestamp(ano, mes, 1)
    mes_fim = mes_inicio + pd.DateOffset(months=1)
    df_mes = df_merged[
        (df_merged['DATA_CHEGADA'] >= mes_inicio) &
        (df_merged['DATA_CHEGADA'] < mes_fim)
    ]
    print(f"[monitor] {len(df_mes)} faturas chegaram em {mes_inicio.strftime('%m/%Y')}", flush=True)

    # Prioridade de fonte: dentro do mesmo ACRONIMO/mês, a linha de
    # monitoramento SEMPRE vence a suplementar (FW+Oracle). Como o tail(1) pega a
    # última após ordenar asc, ordenar por [_PRIO_FONTE, DATA_REFERENCIA] faz o
    # monitoramento (prio 1) sair por último e, entre linhas de monitoramento,
    # vence a de maior DATA_REFERENCIA — exatamente o comportamento de antes.
    # A suplementar só é escolhida quando não há NENHUMA linha de monitoramento
    # no grupo (garante aditividade). Sem coluna FONTE (ex.: fixtures de teste
    # antigos), trata tudo como monitoramento e o critério recai só em DATA_REFERENCIA.
    df_mes = df_mes.copy()
    if 'FONTE' in df_mes.columns:
        df_mes['_PRIO_FONTE'] = (df_mes['FONTE'] == 'MONITORAMENTO').astype(int)
    else:
        df_mes['_PRIO_FONTE'] = 1

    # Colunas do 3º degrau de pagamento (status da parcela no Oracle). Podem faltar quando a
    # ap_oracle_view ainda não expõe o status (degrau desligado em carregar_base) ou em
    # fixtures de teste montadas à mão — garantir a presença mantém o resto do fluxo igual.
    for c in ('STATUS_INSTALLMENT', 'DATA_STATUS_INSTALLMENT', 'FATURA_ID', 'TOTAL_DA_FATURA',
              'FATURA_VALOR'):
        if c not in df_mes.columns:
            df_mes[c] = None

    # [add] Quais faturas chegaram no mês pra cada projeto, na ordem em que o tail(1) as
    # avalia. O painel é UMA linha por projeto/mês, então uma 2ª fatura que chegue no mesmo
    # mês ficava simplesmente invisível — e isso acontece de verdade: a BA-BAR-01 recebeu
    # TRÊS faturas em maio/2026 (competências 02, 03 e 04, duas delas cobrança atrasada
    # emitida 26/05 e ausente do Oracle). Guardar a lista aqui, ANTES do tail(1), é o que
    # permite expor as descartadas em `NFF Adicionais` sem mudar o formato da saída.
    # dict-comp iterando o groupby (e não .apply().to_dict()) porque em mês VAZIO o apply
    # devolve um objeto de forma instável entre versões do pandas; iterar dá {} sempre.
    nffs_por_acronimo = {
        acr: list(dict.fromkeys(notas))
        for acr, notas in df_mes.dropna(subset=['NOTA_FISCAL']).groupby('ACRONIMO')['NOTA_FISCAL']
    }

    # DATA_CHEGADA entra como último critério de desempate: dentro do mês, vence a de
    # competência mais recente (a fatura "da vez") e, empatada a competência, a que chegou
    # depois. Antes o critério era só DATA_REFERENCIA.
    df_recent = (
        df_mes
        .sort_values(['_PRIO_FONTE', 'DATA_REFERENCIA', 'DATA_CHEGADA'], na_position='first')
        .groupby('ACRONIMO')
        .tail(1)
        .copy()
    )
    df_recent['_NFFS_MES'] = df_recent['ACRONIMO'].map(nffs_por_acronimo)

    # Diagnóstico: acrônimos que ficaram sem fatura no mês
    acronimos_projeto = set(df_projetos['ACRONIMO'])
    acronimos_com_fatura = set(df_recent['ACRONIMO'])
    sem_fatura = sorted(acronimos_projeto - acronimos_com_fatura)
    print(f"[monitor] {len(sem_fatura)} projetos sem fatura em {mes_inicio.strftime('%m/%Y')}: {sem_fatura}", flush=True)

    df = df_projetos.merge(
        df_recent[['ACRONIMO','NOTA_FISCAL','DATA_REFERENCIA','DATA_CHEGADA','DATA_DE_PAGAMENTO',
                   'PAGAMENTO','UC','STATUS_INSTALLMENT','DATA_STATUS_INSTALLMENT',
                   'MES_REF_FW','_NFFS_MES','FATURA_ID','TOTAL_DA_FATURA','FATURA_VALOR']],
        on='ACRONIMO',
        how='left'
    )
    # Mês sem NENHUMA fatura (ex.: mês corrente recém-começado): o merge left
    # devolve essas colunas como all-NaN float e o .dt.strftime abaixo quebraria.
    # Coagir pra datetime mantém tudo como NaT e é no-op quando já há dados.
    for c in ('DATA_REFERENCIA', 'DATA_CHEGADA', 'DATA_DE_PAGAMENTO', 'PAGAMENTO',
              'DATA_STATUS_INSTALLMENT', 'MES_REF_FW'):
        df[c] = pd.to_datetime(df[c], errors='coerce')
    # [fix] a data exibida (e usada pelo Status) é a de CHEGADA, não a âncora de mês.
    # Antes as duas eram a mesma coluna, então uma fatura posicionada pela competência
    # aparecia "chegando" no dia 1º, e uma posicionada pelo lançamento contábil aparecia
    # chegando semanas depois do que de fato chegou.
    df['Data Chegada'] = df['DATA_CHEGADA']
    # "Pago" combina TRÊS fontes, em cascata de precedência:
    #   1. AP_ORACLE_VIEW.PAYMENT_DATE  (DATA_DE_PAGAMENTO) — data real do pagamento
    #   2. monitoramento_cusd_aws       (PAGAMENTO)         — mais fresca que o Oracle
    #   3. status da parcela no Oracle  (STATUS_INSTALLMENT) — [add] ver abaixo
    # É OR, nunca AND: as fontes divergem nos dois sentidos (há fatura paga em AP_PAYMENTS cuja
    # parcela ainda diz 'Não paga'). Basta uma indicar pagamento.
    df['Data Pagamento Efetiva'] = df['DATA_DE_PAGAMENTO'].fillna(df['PAGAMENTO'])
    # [add] 3º degrau. O Oracle marcou a parcela como 'Totalmente paga' mas o pagamento não
    # chegou em AP_PAYMENTS — sem este degrau a fatura fica "A pagar" mesmo paga (jun/2026:
    # 2.372 faturas, 4 das 6 usinas do mês). Aqui NÃO existe data de pagamento real; a melhor
    # âncora é UPDATED_AT_INSTALLMENT, o instante em que o Oracle virou o status — daí a data
    # ser marcada como aproximada em "Fonte Pagamento".
    # ADITIVO: só alcança linhas que hoje ficariam sem pagamento nenhum (o fillna não
    # sobrescreve), então quem já tinha data pelos degraus 1/2 sai idêntico.
    pago_parcela = (
        df['Data Pagamento Efetiva'].isna()
        & df['STATUS_INSTALLMENT'].eq('Totalmente paga')
    )
    df['Data Pagamento Efetiva'] = df['Data Pagamento Efetiva'].fillna(
        df['DATA_STATUS_INSTALLMENT'].where(pago_parcela)
    )
    # `| pago_parcela` blinda o caso de parcela paga com UPDATED_AT nulo/ilegível: a fatura
    # está paga mesmo sem data, e sem isso ela voltaria a aparecer como "A pagar".
    df['Pago'] = df['Data Pagamento Efetiva'].notna() | pago_parcela
    df['Data Pagamento'] = df['Data Pagamento Efetiva'].dt.strftime('%d/%m/%Y').where(df['Data Pagamento Efetiva'].notna(), None)
    # [add] Qual degrau respondeu — a UI usa pra sinalizar que a data do 3º é aproximada, e
    # serve de rastro na exportação. A ordem das atribuições espelha a precedência da cascata
    # (a última que se aplica vence); pago_parcela por construção só é True quando 1 e 2 falharam.
    df['Fonte Pagamento'] = None
    df.loc[df['PAGAMENTO'].notna(), 'Fonte Pagamento'] = 'MONITORAMENTO'
    df.loc[df['DATA_DE_PAGAMENTO'].notna(), 'Fonte Pagamento'] = 'ORACLE_PAYMENTS'
    df.loc[pago_parcela, 'Fonte Pagamento'] = 'ORACLE_INSTALLMENT'
    df['NFF'] = df['NOTA_FISCAL']

    # [add] Competência (MES_DE_REFERENCIA do FattureWeb, sempre dia 1º) exibida como MM/AAAA.
    # Virou informação necessária quando a aba passou a ser por mês de CHEGADA: é ela que diz
    # QUAL fatura é a da linha e, comparando mês a mês, denuncia competência pulada — que uma
    # visão por chegada não acusa sozinha.
    df['Competência'] = df['MES_REF_FW'].dt.strftime('%m/%Y').where(df['MES_REF_FW'].notna(), None)

    # [add] Rastro das faturas que chegaram no mês e NÃO são a exibida (ver nffs_por_acronimo).
    # Sem isso a 2ª/3ª fatura do mesmo mês some do painel sem deixar vestígio.
    df['Faturas no Mês'] = df['_NFFS_MES'].apply(lambda v: len(v) if isinstance(v, list) else 0)
    df['NFF Adicionais'] = [
        (', '.join(n for n in lst if n != nff) or None) if isinstance(lst, list) else None
        for lst, nff in zip(df['_NFFS_MES'], df['NFF'])
    ]

    # UC normalizada via _fmt_uc (tira o ".0" de valores que vêm como float).
    df['UC'] = df['UC'].apply(_fmt_uc)
    hoje_date = hoje.date()

    df['Status'] = df.apply(lambda r: _status(r, hoje_date), axis=1)
    df['Dias Restantes'] = df.apply(lambda r: _dias_para_vencer(r, hoje_date), axis=1)

    df['Data Esperada'] = df['Data Esperada'].dt.strftime('%d/%m/%Y')
    df['Data Chegada'] = df['Data Chegada'].dt.strftime('%d/%m/%Y').where(df['Data Chegada'].notna(), None)
    # [add] FATURA_ID e Total Fatura, do FattureWeb (stg_fattureweb_usinas) — ajudam a
    # identificar a fatura além da NFF.
    df['Fatura ID'] = df['FATURA_ID']
    df['Total Fatura'] = df['TOTAL_DA_FATURA']
    # [add] Valor Oracle (AP_ORACLE_VIEW.INVOICEAMOUNT, já vinha na query de pagamento como
    # FATURA_VALOR e morria em _prep_pag) e a diferença contra o Total Fatura do FattureWeb.
    #
    # As duas pontas deveriam bater e NÃO batem: NFF 047744547 vale 19.142,04 no FattureWeb e
    # 7.525,59 no Oracle. Como "Pago" vem do Oracle e "Total Fatura" do FW, o painel dava a
    # entender que os 19.142,04 foram quitados — quando o que entrou na AP foi 7.525,59.
    # A divergência é o sinal: fatura lançada parcialmente, valor digitado errado, ou NFF
    # reutilizada. Só expõe o número das duas fontes; nenhuma coluna existente muda.
    df['Valor Oracle'] = pd.to_numeric(df['FATURA_VALOR'], errors='coerce')
    total_fw = pd.to_numeric(df['Total Fatura'], errors='coerce')
    # Só compara quando AS DUAS pontas têm valor — sem lançamento no Oracle a diferença
    # seria o total inteiro e todo mês novo apareceria como divergente.
    df['Divergência Valor'] = (total_fw - df['Valor Oracle']).round(2)
    # Colunas novas entram no FIM: consumidores existentes leem por nome, então a ordem antiga
    # segue intacta ('Fonte Pagamento' entrou pela mesma razão).
    cols = ['Projeto','ACRONIMO','Distribuidora','Dia','Forma Recebimento',
             'Data Esperada','Data Chegada','Status','Dias Restantes',
             'NFF','UC','Pago','Data Pagamento','Fonte Pagamento',
             'Competência','Faturas no Mês','NFF Adicionais','Fatura ID','Total Fatura',
             'Valor Oracle','Divergência Valor']
    df_out = df[cols]

    # sanitiza NaN/NaT -> None pra JSON válido
    records = df_out.astype(object).where(df_out.notna(), None).to_dict(orient='records')
    return records


def consultar_faturas(ano=None, mes=None):
    """Retorna a lista de dicts (projetos + status + pagamento) pro mês pedido
    (default = corrente). Wrapper de compat: carrega a base e monta o mês numa
    tacada. Pra trocar de mês SEM re-consultar o Snowflake, cacheie o retorno de
    `carregar_base()` e chame `montar_mes()` direto — é o que a Api faz.
    """
    df_merged, df_projetos = carregar_base()
    return montar_mes(df_merged, df_projetos, ano, mes)