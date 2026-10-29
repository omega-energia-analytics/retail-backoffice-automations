"""SQLite local do Monitor NFF: controle de NFFs enviadas + histórico do painel.

Duas tabelas, propósitos diferentes:

- `controle_nff`: quais NFFs já foram para o Oracle (vem da planilha ADFDI).
- `historico_fatura`: o que o painel mostrou ao longo do tempo. Grava só MUDANÇA,
  não snapshot — ver `registrar_snapshot`.
"""
import os
import sqlite3
from contextlib import contextmanager

import config

# Campos vigiados pelo histórico. Mudou um deles numa fatura → vira linha no log.
# `Divergência Valor` fica DE FORA de propósito: é derivado de Total Fatura e Valor
# Oracle, então registrá-lo duplicaria toda mudança de valor.
CAMPOS_HISTORICO = [
    'Status',
    'Pago',
    'Data Chegada',
    'Total Fatura',
    'Valor Oracle',
    'Fonte Pagamento',
]

# Campos cujo valor é dinheiro. Guardados sempre como '1234.56' (ponto, 2 casas),
# venham eles como float do Oracle ou como texto em formato BR do FattureWeb —
# ver _num em _txt.
CAMPOS_VALOR = {'Total Fatura', 'Valor Oracle'}


def _db_path():
    return config.get("db_path")


def nff_digitos(valor):
    """Só os dígitos da NFF, sem zeros à esquerda — a forma canônica para
    comparar duas grafias do mesmo número.

    O Oracle devolve a MESMA NFF de três jeitos: '016351936' (zero à esquerda),
    '17767235.0' (float que virou texto na exportação) e '014.492.028' (com
    separador de milhar). Todas viram '16351936', '17767235' e '14492028'.

    O sufixo '.0' é CORTADO, não apenas limpo: tirar só o ponto colaria o zero
    no fim e '17767235.0' viraria '177672350' -- outro número. NFF é
    identificador inteiro, então não há parte decimal real a preservar. Já os
    pontos de '014.492.028' são separador de milhar e somem sem deixar resto.
    """
    if valor is None:
        return ''
    txt = str(valor).strip()
    # Só trata como decimal o que tem UM ponto com 1-2 dígitos depois dele;
    # '014.492.028' tem três grupos e é separador de milhar, não decimal.
    inteiro, ponto, resto = txt.rpartition('.')
    if ponto and inteiro and '.' not in inteiro and 1 <= len(resto) <= 2 \
            and resto.isdigit():
        txt = inteiro
    return ''.join(ch for ch in txt if ch.isdigit()).lstrip('0')


@contextmanager
def conn_ctx():
    caminho = _db_path()
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    # Disponível no SQL como nff_digitos(...) — ver busca por NFF em
    # buscar_historico. Registrado aqui porque toda conexão passa por este ponto.
    conn.create_function("nff_digitos", 1, nff_digitos)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with conn_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS controle_nff (
                numero_nff TEXT PRIMARY KEY,
                data_envio TEXT
            )
        """)
        # Histórico do painel. Uma linha por MUDANÇA observada, não por carga:
        # abrir o app cinco vezes no mesmo dia sem nada mudar não grava nada.
        #
        # A identidade de uma fatura é (projeto, mês do painel, competência,
        # NFF). As quatro partes são necessárias:
        #
        # - `nff`, para a 2ª nota do mês ser uma fatura própria. O painel mostra
        #   uma linha por projeto/mês e joga a 2ª nota em 'NFF Adicionais'; sem
        #   a NFF na chave, a troca de qual nota é a "principal" entraria no log
        #   como se o número da nota tivesse mudado.
        # - `mes_painel`, o recorte que produziu a linha, porque fatura que
        #   ainda NÃO chegou não tem competência nem nota: a chave dela seria
        #   (projeto, '', '') e TODOS os meses dela colapsariam numa só. Como o
        #   mesmo projeto aparece 'Pendente' num mês e 'Atrasada' noutro, cada
        #   mês sobrescrevia o anterior e o log registrava um vai-e-volta
        #   infinito, a cada carga (observado em produção: 170 linhas assim).
        # - `competencia` distingue faturas de competências diferentes que
        #   aparecem no mesmo mês do painel (o recorte é por data de chegada).
        #
        # `nff` fica '' (não NULL) quando a fatura ainda não tem nota: NULL não
        # casa com '=' em SQL e a linha nunca reencontraria seu próprio estado
        # anterior, gerando 'apareceu' repetido a cada carga.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historico_fatura (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observado_em TEXT NOT NULL,
                projeto TEXT NOT NULL,
                acronimo TEXT,
                mes_painel TEXT NOT NULL,
                competencia TEXT NOT NULL,
                nff TEXT NOT NULL,
                campo TEXT NOT NULL,
                valor_de TEXT,
                valor_para TEXT
            )
        """)
        # A busca é sempre por usina ou por nota; o índice cobre os dois casos
        # (acronimo isolado, nff isolado) sem varrer a tabela inteira.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_hist_acronimo
            ON historico_fatura (acronimo, observado_em)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_hist_nff
            ON historico_fatura (nff, observado_em)
        """)
        # Ler o estado atual de uma fatura é o passo mais quente da gravação
        # (uma consulta por fatura por carga), e é sempre pela chave completa.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_hist_chave
            ON historico_fatura (projeto, mes_painel, competencia, nff, campo, id)
        """)
        # Cobre o ORDER BY da tela (ver buscar_historico). Sem ele o SQLite
        # monta um B-tree temporário para ordenar a tabela inteira a cada
        # consulta — tolerável nas 13 mil linhas de hoje, mas o log só cresce.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_hist_ordem
            ON historico_fatura (observado_em DESC, mes_painel DESC, id DESC)
        """)
        conn.commit()

def listar_todas():
    with conn_ctx() as conn:
        rows = conn.execute(
            "SELECT numero_nff, data_envio FROM controle_nff ORDER BY datetime(data_envio) DESC"
        ).fetchall()
    return [dict(r) for r in rows]

def buscar(numero):
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT numero_nff, data_envio FROM controle_nff WHERE numero_nff = ?",
            (numero,)
        ).fetchone()
    return dict(row) if row else None

def total_registros():
    with conn_ctx() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM controle_nff").fetchone()['c']

def inserir_nffs(lista_nffs, timestamp):
    inseridas = []
    with conn_ctx() as conn:
        for nff in lista_nffs:
            cur = conn.execute(
                "INSERT OR IGNORE INTO controle_nff (numero_nff, data_envio) VALUES (?, ?)",
                (nff, timestamp)
            )
            if cur.rowcount > 0:
                inseridas.append(nff)
        conn.commit()
    return inseridas

def nffs_existentes():
    with conn_ctx() as conn:
        rows = conn.execute("SELECT numero_nff FROM controle_nff").fetchall()
    return set(r['numero_nff'] for r in rows)


# --- histórico do painel ---
def _num(texto):
    """Converte dinheiro em texto no formato BR para float. None se não for número.

    `Total Fatura` chega do FattureWeb como TEXTO em formato brasileiro
    ('32810,15'), enquanto `Valor Oracle` chega como float — os dois campos são
    dinheiro e precisam virar a mesma coisa antes de serem comparados. Sem isso,
    '7575,1' e '7575,10' contariam como mudança, e uma fonte que alterne entre
    texto e número geraria mudança falsa a cada carga.

    Trata o separador de milhar brasileiro ('1.234,56'): o ponto só é decimal
    quando não há vírgula no texto.
    """
    t = str(texto).strip()
    if not t:
        return None
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


def _txt(campo, valor):
    """Texto estável de um valor de campo — é o que vai para o banco e o que a
    comparação enxerga.

    Precisa ser estável porque a comparação é textual: um valor que muda de
    representação sem mudar de conteúdo viraria mudança falsa a cada carga.
    Por isso bool vira 'sim'/'nao' (e não 'True'/'1', que o JS e o pandas
    escrevem diferente) e dinheiro vira sempre '1234.56' — a divergência de
    centavos entre FattureWeb e Oracle já é real; ruído de representação não
    precisa virar linha no log.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        return 'sim' if valor else 'nao'
    if isinstance(valor, float) and valor != valor:  # NaN (coluna vazia do pandas)
        return None
    if campo in CAMPOS_VALOR:
        n = _num(valor) if not isinstance(valor, (int, float)) else float(valor)
        # valor de dinheiro que não é número não é descartado: vira texto cru,
        # para quem for ler o log ver o que a fonte mandou em vez de um vazio.
        return f"{round(n, 2):.2f}" if n is not None else (str(valor).strip() or None)
    if isinstance(valor, float):
        return f"{round(valor, 2):.2f}"
    texto = str(valor).strip()
    return texto or None


def _chave(linha, mes_painel):
    """(projeto, mês do painel, competência, NFF) — ver o comentário em init_db.

    `mes_painel` não é redundante com `competencia`: fatura que ainda não chegou
    não tem competência nenhuma, e sem o mês do painel todos os meses dela
    colapsam na mesma chave.
    """
    return (
        _txt('Projeto', linha.get('Projeto')) or '',
        mes_painel,
        _txt('Competência', linha.get('Competência')) or '',
        _txt('NFF', linha.get('NFF')) or '',
    )


def estado_atual(conn, chave):
    """Último valor gravado de cada campo desta fatura.

    `MAX(id)` em vez de `MAX(observado_em)`: duas cargas no mesmo segundo têm o
    mesmo timestamp, e aí o desempate por id é o único que respeita a ordem real
    de gravação.
    """
    rows = conn.execute("""
        SELECT campo, valor_para
        FROM historico_fatura
        WHERE projeto = ? AND mes_painel = ? AND competencia = ? AND nff = ?
          AND id IN (
              SELECT MAX(id) FROM historico_fatura
              WHERE projeto = ? AND mes_painel = ? AND competencia = ? AND nff = ?
              GROUP BY campo
          )
    """, (*chave, *chave)).fetchall()
    return {r['campo']: r['valor_para'] for r in rows}


def _adotar_sem_nff(conn, projeto, mes_painel, competencia, nff, acronimo,
                    observado_em):
    """Transfere o histórico da fatura-sem-nota para a NFF que acabou de chegar.

    A NFF faz parte da chave (para a 2ª emissão do mês ser uma fatura própria),
    e isso cria um caso a resolver: a fatura existe no painel ANTES de ter nota
    — como 'Atrasada' ou 'Pendente' — e ganha a nota quando chega. Sem adoção,
    virar uma nota nova parte a fatura em duas: a sem-nota congela no último
    status e a com-nota nasce do zero, então 'Atrasada -> Chegou' nunca aparece,
    que é exatamente a transição que a aba existe para mostrar.

    A órfã é procurada dentro do MESMO mês do painel: mês é parte da identidade,
    e a fatura sem nota de um mês não tem relação com a nota que chegou noutro.

    Só adota quando a fatura com NFF ainda não tem histórico próprio — se já
    tem, a sem-nota é outra coisa (uma 2ª fatura ainda sem nota, por exemplo) e
    mexer nela embaralharia duas histórias.
    """
    ja_tem = conn.execute("""
        SELECT 1 FROM historico_fatura
        WHERE projeto = ? AND mes_painel = ? AND competencia = ? AND nff = ?
        LIMIT 1
    """, (projeto, mes_painel, competencia, nff)).fetchone()
    if ja_tem:
        return {}
    orfas = conn.execute("""
        SELECT 1 FROM historico_fatura
        WHERE projeto = ? AND mes_painel = ? AND competencia = ? AND nff = ''
        LIMIT 1
    """, (projeto, mes_painel, competencia)).fetchone()
    if not orfas:
        return {}
    conn.execute("""
        UPDATE historico_fatura SET nff = ?
        WHERE projeto = ? AND mes_painel = ? AND competencia = ? AND nff = ''
    """, (nff, projeto, mes_painel, competencia))
    # A chegada da nota é ela própria um evento: sem esta linha, o número
    # apareceria na tabela sem nunca ter sido registrado como novidade.
    conn.execute("""
        INSERT INTO historico_fatura
            (observado_em, projeto, acronimo, mes_painel, competencia, nff,
             campo, valor_de, valor_para)
        VALUES (?, ?, ?, ?, ?, ?, 'NFF', NULL, ?)
    """, (observado_em, projeto, acronimo, mes_painel, competencia, nff, nff))
    # Só o estado dos campos vigiados interessa como base de comparação; a linha
    # 'NFF' acima é um evento, não um campo que se compara na próxima carga.
    estado = estado_atual(conn, (projeto, mes_painel, competencia, nff))
    return {c: v for c, v in estado.items() if c in CAMPOS_HISTORICO}


def registrar_snapshot(linhas, observado_em, mes_painel):
    """Compara as linhas do painel com o último estado conhecido e grava só o
    que mudou. Devolve quantas mudanças foram registradas.

    `mes_painel` é o recorte ('AAAA-MM') que produziu estas linhas — parte da
    identidade da fatura, ver `_chave`. Chamar uma vez por mês da base.

    Uma fatura vista pela primeira vez grava os campos que já têm valor — senão
    ela só apareceria no log na primeira vez que mudasse, e uma usina estável
    ficaria invisível. Campo que continua vazio não gera linha: 'não tinha valor
    e continua sem' não é um evento.
    """
    registros = []
    with conn_ctx() as conn:
        for linha in linhas:
            chave = _chave(linha, mes_painel)
            projeto, _, competencia, nff = chave
            if not projeto:
                continue  # linha sem projeto não é uma fatura rastreável
            acronimo = _txt('ACRONIMO', linha.get('ACRONIMO'))
            anterior = estado_atual(conn, chave)
            # Fatura que ganhou nota: herda o histórico de quando não tinha, em
            # vez de nascer de novo (ver _adotar_sem_nff).
            if not anterior and nff:
                anterior = _adotar_sem_nff(conn, projeto, mes_painel, competencia,
                                           nff, acronimo, observado_em)
            novata = not anterior
            for campo in CAMPOS_HISTORICO:
                novo = _txt(campo, linha.get(campo))
                if novata:
                    if novo is None:
                        continue
                    velho = None
                else:
                    velho = anterior.get(campo)
                    if velho == novo:
                        continue
                registros.append((observado_em, projeto, acronimo, mes_painel,
                                  competencia, nff, campo, velho, novo))
        if registros:
            conn.executemany("""
                INSERT INTO historico_fatura
                    (observado_em, projeto, acronimo, mes_painel, competencia,
                     nff, campo, valor_de, valor_para)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, registros)
        # Commit incondicional: a adoção de fatura que ganhou nota já escreveu
        # pelo `conn`, e ela pode acontecer numa carga que não registre nenhuma
        # mudança nova. Com commit só `if registros`, essa adoção se perderia e
        # a fatura voltaria a ser órfã na carga seguinte.
        conn.commit()
    return len(registros)


def carga_inicial_em(conn=None):
    """Instante da primeira gravação deste banco, ou None se está vazio.

    A primeira carga enche o log com todas as faturas que já existiam no painel
    — centenas de linhas com `valor_de` vazio e o mesmo timestamp. Elas não são
    mudança: são o retrato do que já havia quando o log passou a existir. Saber
    qual é esse instante é o que permite escondê-las da tela por padrão.
    """
    def _ler(c):
        row = c.execute(
            "SELECT observado_em FROM historico_fatura ORDER BY id LIMIT 1"
        ).fetchone()
        return row['observado_em'] if row else None
    if conn is not None:
        return _ler(conn)
    with conn_ctx() as conn:
        return _ler(conn)


def meses_historico():
    """Meses do painel presentes no log, mais recente primeiro.

    Alimenta o filtro de mês da aba. Sem ele, o corte em `limite` mostra só os
    dois meses mais recentes e o resto do log fica inalcançável pela tela.
    """
    with conn_ctx() as conn:
        return [r['mes_painel'] for r in conn.execute(
            "SELECT DISTINCT mes_painel FROM historico_fatura ORDER BY 1 DESC")]


def buscar_historico(termo=None, limite=500, incluir_carga_inicial=False,
                     mes_painel=None):
    """Mudanças mais recentes primeiro. `termo` casa com acrônimo, projeto ou
    NFF — a busca é uma só porque quem procura 'GO-RIQ-01' e quem procura
    '047744547' quer a mesma tela.

    A carga inicial fica de fora por padrão (ver `carga_inicial_em`): ela diria
    'tudo apareceu' sobre o acervo inteiro e afogaria a mudança de verdade.

    ATENÇÃO -- A ORDEM É POR (observado_em, mes_painel), NÃO POR id. `id` é
    ordem de INSERÇÃO, e numa mesma carga todas as linhas compartilham o
    `observado_em`: o que as distingue é o mês, que `_registrar_historico`
    percorre do mais recente para o mais antigo. Ordenar por `id DESC` punha as
    linhas do mês MAIS ANTIGO no topo e, com o corte em `limite`, a tela só
    mostrava 2023 (observado em produção com 12.991 linhas de 2023-07 a
    2026-10). `id` entra só como desempate final, para a ordem ser determinística.
    """
    sql = """
        SELECT observado_em, projeto, acronimo, mes_painel, competencia, nff,
               campo, valor_de, valor_para
        FROM historico_fatura
    """
    where, params = [], []
    termo = (termo or '').strip()
    if termo:
        like = f"%{termo.lower()}%"
        cond = ["""(LOWER(COALESCE(acronimo, '')) LIKE ?
                 OR LOWER(projeto) LIKE ?
                 OR LOWER(nff) LIKE ?)"""]
        params += [like, like, like]
        # A NFF chega do Oracle em três grafias para o MESMO número:
        # '016351936' (zero à esquerda), '17767235.0' (float virado texto) e
        # '014.492.028' (com pontos). Um LIKE cru só acha quem digitou a grafia
        # exata que está gravada -- quem digita o número "limpo" não acha nada.
        # Quando o termo é numérico, compara só os dígitos dos dois lados, sem
        # zeros à esquerda (ver nff_digitos).
        #
        # SÓ para termo numérico puro (dígitos, pontos e espaços). Acrônimo tem
        # dígito dentro -- 'SP-DES-01' reduziria a '1' e o LIKE '%1%' casaria com
        # quase toda NFF do banco, devolvendo 82 acrônimos para quem pediu um.
        so_numero = termo and all(ch.isdigit() or ch in '. ' for ch in termo)
        digitos = nff_digitos(termo) if so_numero else ''
        if digitos:
            cond.append("nff_digitos(nff) LIKE ?")
            params.append(f"%{digitos}%")
        where.append("(" + " OR ".join(cond) + ")")
    if mes_painel:
        where.append("mes_painel = ?")
        params.append(mes_painel)
    if not incluir_carga_inicial:
        with conn_ctx() as c:
            inicial = carga_inicial_em(c)
        if inicial:
            where.append("observado_em > ?")
            params.append(inicial)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY observado_em DESC, mes_painel DESC, id DESC LIMIT ?"
    params.append(int(limite))
    with conn_ctx() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def total_historico():
    with conn_ctx() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM historico_fatura"
        ).fetchone()['c']