import os
import re
import subprocess
import time
from turtle import pd
from turtle import pd
import unicodedata
from datetime import date
from pathlib import Path

import openpyxl
import xlwings as xw
from colorama import Fore, Style
from colorama import init as _colorama_init

_colorama_init(autoreset=True)  # ANSI no Windows; reseta cor/estilo ao fim de cada print

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent

ARQ_ORIGEM = BASE / "contratos completos.xlsx"
ABA_ORIGEM = "Controle_Emissão"

PADRAO_DESTINO = "CreateQuickInvoices*.xlsm"   # o mais recente que casar é usado
ABA_DESTINO = "NFFs"

FILTRO_TIPO_NOTA = "Débito"     # trabalhamos apenas com Tipo de Nota = Débito
LINHA_INICIAL = 9               # dados começam na linha 9 (linha 8 = cabeçalho)

# Valores fixos do de_para (ajustados ao arquivo real)
MOEDA = "BRL"
TIPO_NFF = "Standard"             # de_para dizia "Standard"; arquivo real usa "Padrão"
COND_PGTO = "Imediato"
GRUPO_PGTO = "Método Direto"
TIPO_LINHA = "Item"

# Nomes das colunas na aba de ORIGEM (Controle_Emissão)
SRC = {
    "pagador": "PAGADOR",
    "nota": "Nº da Nota",
    "valor": "Valor",
    "fornecedor": "FORNECEDOR",
    "cnpj": "CNPJ",
    "descricao": "Descrição",
    "charge": "Charge Account",
    "tipo_nota": "Tipo de Nota",
}

# Texto do cabeçalho (linha 8) na aba de DESTINO, por campo do de_para.
# A coluna é resolvida em tempo de execução (primeira ocorrência do texto).
DST_HEADERS = {
    "id_cabecalho": "*Identificador do Cabeçalho da NFF",
    "unidade_negocio": "*Unidade de Negócio",
    "numero_nff": "*Número da NFF",
    "moeda_nff": "*Moeda da NFF",
    "valor_nff": "*Valor da NFF",
    "data_nff": "*Data da NFF",
    "fornecedor": "**Fornecedor[..]",
    "numero_fornecedor": "**Número do Fornecedor",   # coluna M (ID Oracle via de/para)
    "local_fornecedor": "*Local do Fornecedor[..]",
    "moeda_pgto": "Moeda de Pagamento",
    "tipo_nff": "Tipo de NFF",
    "descricao": "Descrição",                 # 1ª ocorrência = nível cabeçalho (Q)
    "cond_pgto": "Condições de Pagamento",
    "data_cond": "Data das Condições",
    "grupo_pgto": "Grupo de Pagamento",
    "tipo_linha": "*Tipo",
    "valor_linha": "*Valor",
    "combinacao_dist": "Combinação de Distribuição[..]",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Chars ilegais no Excel: controle ASCII + zero-width (U+200B..U+200D) + BOM (U+FEFF)
_ILEGAIS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F​-‍﻿]")


def _clean(v):
    """Remove caracteres ilegais para o Excel e normaliza espaços."""
    if isinstance(v, str):
        return _ILEGAIS.sub("", v).replace("\xa0", " ").strip()
    return v


def _digitos(v):
    """Mantém apenas dígitos (ex.: CNPJ '30.997.588/0010-51 ' -> '30997588001051')."""
    if v in (None, ""):
        return None
    d = re.sub(r"\D", "", str(v))
    return d or None


def _vazio(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def _norm_un(v):
    """Normaliza um nome de Unidade de Negócio para casar no DE_PARA_UNIDADE:
    tira acento, sobe pra maiúsculo, colapsa espaços e remove pontuação/espaço
    no fim (assim 'CONSÓRCIO...', 'SERENA GERAÇÃO S.A' e 'S.A.' caem na mesma chave).
    O sufixo 'SA' sem pontos vira 'S.A': a Controle_Emissão passou a trazer
    'SERENA GERAÇÃO SA' (PAGADOR) e 'ARCO ENERGIA 1 SA' (FORNECEDOR) — mesmo CNPJ das
    grafias com ponto — e sem isso caíam fora do de/para."""
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s.upper()).strip()
    s = s.rstrip(". ").strip()
    return re.sub(r" SA$", " S.A", s)


# De/para PAGADOR (Controle_Emissão) -> valor da LOV "*Unidade de Negócio" do Oracle.
# O Oracle exige o valor EXATO da lista ("<código>-<nome>"); os códigos vêm da aba
# _ADFDI_LOV do CreateQuickInvoices e NÃO são sequenciais (GD 9 = 6101, GD 12 = 6091).
# Se o Oracle mudar/adicionar unidades, atualize daqui (aba _ADFDI_LOV, linha 2).
# As chaves são normalizadas por _norm_un, então acento/caixa/sufixo do PAGADOR não importam.
_DE_PARA_UNIDADE_RAW = {
    "SERENA GERAÇÃO S.A":     "1001-SERENA GERACAO",
    "CONSÓRCIO SERENA GD 1":  "6001-CONSORCIO SERENA GD 1",
    "CONSÓRCIO SERENA GD 2":  "6011-CONSORCIO SERENA GD 2",
    "CONSÓRCIO SERENA GD 3":  "6021-CONSORCIO SERENA GD 3",
    "CONSÓRCIO SERENA GD 4":  "6031-CONSORCIO SERENA GD 4",
    "CONSÓRCIO SERENA GD 5":  "6041-CONSORCIO SERENA GD 5",
    "CONSÓRCIO SERENA GD 6":  "6051-CONSORCIO SERENA GD 6",
    "CONSÓRCIO SERENA GD 7":  "6061-CONSORCIO SERENA GD 7",
    "CONSÓRCIO SERENA GD 8":  "6071-CONSORCIO SERENA GD 8",
    "CONSÓRCIO SERENA GD 9":  "6101-CONSORCIO SERENA GD 9",
    "CONSÓRCIO SERENA GD 10": "6111-CONSORCIO SERENA GD 10",
    "CONSÓRCIO SERENA GD 11": "6121-CONSORCIO SERENA GD 11",
    "CONSÓRCIO SERENA GD 12": "6091-CONSORCIO SERENA GD 12",
    "CONSÓRCIO SERENA GD 13": "6141-CONSORCIO SERENA GD 13",
}
DE_PARA_UNIDADE = {_norm_un(k): v for k, v in _DE_PARA_UNIDADE_RAW.items()}


# De/para FORNECEDOR (Controle_Emissão) -> ("Número do Fornecedor" da coluna M,
# "Fornecedor" da coluna L). Números fornecidos pelo time (Isa). Antes o M ficava em
# branco e o Oracle casava pelo nome em L; agora preenchemos o ID p/ casar direto.
# As chaves são normalizadas por _norm_un, então acento/caixa/espaço/sufixo do
# FORNECEDOR não importam (ex.: "LOCAÇÃO" vs "LOCACAO", "S.A." vs "S.A", trailing
# space). Fornecedor novo? adicione aqui.
#
# O 2º item é a grafia EXATA do cadastro do Oracle (lista conferida pela Neiva em
# 20/10/2026): o L passou a sair daqui porque a Controle_Emissão escreve o nome com
# variações de ponto/sufixo ("... S.A" vs "... S.A."), e o Oracle recusa a linha —
# ela vinha corrigindo o L na mão, linha a linha, a cada geração. Sem de/para o L
# continua saindo como veio da origem (comportamento antigo).
# Sem grafia confirmada pela Neiva (SERRA DO RAMALHO, SERENA, ARCO 1/3/5/6): mantida
# a do próprio de/para, que já era a usada até aqui.
# Chaves duplicadas de propósito (mesmo par de valores): a origem e o Oracle divergem
# no sufixo e _norm_un só remove pontuação do FIM, então "LTDA EPP" e o nome curto da
# SUNO não cairiam na mesma chave do nome oficial.
_DE_PARA_FORNECEDOR_RAW = {
    "ATHON GERACAO DISTRIBUIDA S/A":                 ("16511", "ATHON GERACAO DISTRIBUIDA S/A"),
    "ATHON GERACAO DISTRIBUIDA II S.A.":             ("16396", "ATHON GERACAO DISTRIBUIDA II S.A."),
    "TOV 3 COXIPO DO OURO MT SPE LTDA":              ("16435", "TOV 3 COXIPO DO OURO MT SPE LTDA"),
    "TOV 10 SOLONOPOLE CE SPE LTDA":                 ("16419", "TOV 10 SOLONOPOLE CE SPE LTDA"),
    "SOL GO GUAPO LTDA":                             ("15588", "SOL GO GUAPO LTDA"),
    "SOL GO CEZARINA LTDA":                          ("15589", "SOL GO CEZARINA LTDA."),
    "SOL CE BEBERIBE LTDA":                          ("15590", "SOL CE BEBERIBE LTDA"),
    "EMANA PIAUI LOCACAO DE EQUIPAMENTOS LTDA":      ("15244", "EMANA PIAUI LOCACAO DE EQUIPAMENTOS LTDA EPP"),
    "EMANA PIAUI LOCACAO DE EQUIPAMENTOS LTDA EPP":  ("15244", "EMANA PIAUI LOCACAO DE EQUIPAMENTOS LTDA EPP"),
    "STIMA PIAUI LOCACAO DE EQUIPAMENTOS LTDA":      ("15931", "STIMA PIAUI LOCACAO DE EQUIPAMENTOS LTDA."),
    "SERRA DO RAMALHO LOCACAO DE EQUIPAMENTOS LTDA": ("15953", "SERRA DO RAMALHO LOCACAO DE EQUIPAMENTOS LTDA"),
    "SERENA GERACAO S.A":                            ("91495030", "SERENA GERACAO S.A"),
    "SUNO ENERGIAS LIMPAS FUNDO DE INVESTIMENTO IMOBILIARIO IS": (
        "17490", "SUNO ENERGIAS LIMPAS FUNDO DE INVESTIMENTO IMOBILIARIO IS RESPONSABILIDADE LIMITADA"),
    "SUNO ENERGIAS LIMPAS FUNDO DE INVESTIMENTO IMOBILIARIO IS RESPONSABILIDADE LIMITADA": (
        "17490", "SUNO ENERGIAS LIMPAS FUNDO DE INVESTIMENTO IMOBILIARIO IS RESPONSABILIDADE LIMITADA"),
    "ARCO ENERGIA 1 S.A.":                           ("14978", "ARCO ENERGIA 1 S.A."),
    "ARCO ENERGIA 3 S.A.":                           ("14980", "ARCO ENERGIA 3 S.A."),
    "ARCO ENERGIA 5 S.A.":                           ("14983", "ARCO ENERGIA 5 S.A."),
    "ARCO ENERGIA 6 S.A.":                           ("14984", "ARCO ENERGIA 6 S.A."),
}
DE_PARA_FORNECEDOR = {_norm_un(k): v for k, v in _DE_PARA_FORNECEDOR_RAW.items()}


def resolver_unidade(pagador, nao_mapeados):
    """PAGADOR -> valor da LOV do Oracle via DE_PARA_UNIDADE. Se não achar, mantém
    o nome limpo (comportamento antigo) e registra em `nao_mapeados` p/ o aviso."""
    limpo = _clean(pagador)
    valor = DE_PARA_UNIDADE.get(_norm_un(limpo))
    if valor:
        return valor
    if limpo:
        nao_mapeados.add(limpo)
    return limpo


def resolver_fornecedor(fornecedor, nao_mapeados_forn):
    """FORNECEDOR -> "Número do Fornecedor" (ID Oracle) via DE_PARA_FORNECEDOR. Sem de/para,
    deixa em branco (comportamento antigo do M — o Oracle casa pelo nome em L) e registra
    em `nao_mapeados_forn` p/ o aviso."""
    limpo = _clean(fornecedor)
    par = DE_PARA_FORNECEDOR.get(_norm_un(limpo))
    if par:
        return par[0]
    if limpo:
        nao_mapeados_forn.add(limpo)
    return None


def resolver_nome_fornecedor(fornecedor):
    """FORNECEDOR -> grafia do cadastro do Oracle (coluna L) via DE_PARA_FORNECEDOR.
    Sem de/para, devolve o nome limpo da origem (comportamento antigo do L). Não
    registra não-mapeados: quem faz isso é resolver_fornecedor, na mesma linha."""
    limpo = _clean(fornecedor)
    par = DE_PARA_FORNECEDOR.get(_norm_un(limpo))
    return par[1] if par else limpo


def achar_destino():
    """Retorna o CreateQuickInvoices*.xlsm mais recente na pasta (ignora locks ~$)."""
    candidatos = [p for p in BASE.glob(PADRAO_DESTINO) if not p.name.startswith("~$")]
    if not candidatos:
        raise FileNotFoundError(
            f"Nenhum arquivo '{PADRAO_DESTINO}' encontrado em {BASE}."
        )
    return max(candidatos, key=lambda p: p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Leitura da origem
# ---------------------------------------------------------------------------
def ler_debitos():
    """Lê Controle_Emissão e devolve (idx_por_campo, lista_de_linhas_Débito)."""
    wb = openpyxl.load_workbook(ARQ_ORIGEM, read_only=True, data_only=True)
    try:
        ws = wb[ABA_ORIGEM]
        linhas = ws.iter_rows(values_only=True)
        cabecalho = [_clean(h) for h in next(linhas)]

        idx = {}
        for campo, nome_col in SRC.items():
            if nome_col not in cabecalho:
                raise ValueError(
                    f"Coluna '{nome_col}' não encontrada na aba '{ABA_ORIGEM}'. "
                    f"Cabeçalho lido: {cabecalho}"
                )
            idx[campo] = cabecalho.index(nome_col)

        debitos = []
        for row in linhas:
            if not any(v is not None for v in row):
                continue
            if _clean(row[idx["tipo_nota"]]) == FILTRO_TIPO_NOTA:
                debitos.append(row)
    finally:
        wb.close()

    return idx, debitos


# ---------------------------------------------------------------------------
# Montagem dos registros (1 dict por NFF, campo -> valor)
# ---------------------------------------------------------------------------
def montar_registros(idx, debitos, hoje):
    import pandas as pd
    registros = []
    sem_valor = sem_nota = 0
    nao_mapeados = set()
    nao_mapeados_forn = set()

    for i, row in enumerate(debitos):
        g = lambda campo: row[idx[campo]]
        valor = g("valor")
        nota = g("nota")
        if _vazio(valor):
            sem_valor += 1
        if _vazio(nota):
            sem_nota += 1

        registros.append({
            "id_cabecalho": i + 1,                 # 1, 2, 3, ... (1 NFF por linha)
            "unidade_negocio": resolver_unidade(g("pagador"), nao_mapeados),
            "numero_nff": _clean(nota),
            "moeda_nff": MOEDA,
            "valor_nff": valor,
            "data_nff": hoje,
            "fornecedor": resolver_nome_fornecedor(g("fornecedor")),
            "numero_fornecedor": resolver_fornecedor(g("fornecedor"), nao_mapeados_forn),
            "local_fornecedor": _digitos(g("cnpj")),
            "moeda_pgto": MOEDA,
            "tipo_nff": TIPO_NFF,
            "descricao": _clean(g("descricao")),
            "cond_pgto": COND_PGTO,
            "data_cond": pd.Timestamp(hoje) + pd.offsets.MonthEnd(0), # último dia do mês, segundo a Neiva
            "grupo_pgto": GRUPO_PGTO,
            "tipo_linha": TIPO_LINHA,
            "valor_linha": valor,
            "combinacao_dist": _clean(g("charge")),
        })

    return registros, sem_valor, sem_nota, nao_mapeados, nao_mapeados_forn


def fatiar_lote(registros, capacidade, lote):
    """Recorta o `lote` (1-based) de até `capacidade` NFFs e renumera o id_cabecalho
    a partir de 1 dentro do lote. Devolve (fatia, total_de_lotes, offset_do_lote).

    Existe porque o template ADFDI só desbloqueia uma faixa FINITA de linhas na aba
    NFFs (100 no CreateQuickInvoices atual: linhas 9–108). Escrever além dela dá
    com_error 0x800A03EC ('planilha protegida') no meio da gravação."""
    if capacidade < 1:
        raise ValueError("A aba NFFs não tem nenhuma linha desbloqueada a partir da "
                         f"linha {LINHA_INICIAL} — template inválido?")
    total = max(1, -(-len(registros) // capacidade))     # ceil; 0 registros = 1 lote vazio
    if not 1 <= lote <= total:
        raise ValueError(f"Lote {lote} não existe: são {len(registros)} NFF(s) em "
                         f"{total} lote(s) de até {capacidade}.")
    ini = (lote - 1) * capacidade
    fatia = [dict(reg, id_cabecalho=k + 1)
             for k, reg in enumerate(registros[ini:ini + capacidade])]
    return fatia, total, ini


def capacidade_linhas(sht, col):
    """Quantas linhas consecutivas, a partir de LINHA_INICIAL, estão DESBLOQUEADAS na
    coluna `col` — é o máximo de NFFs que cabe no template sem esbarrar na proteção.
    Lido do próprio arquivo: se alguém baixar um template com mais linhas (ou inserir
    linhas pelo menu do ADFDI), a capacidade acompanha sem mexer no código."""
    teto = LINHA_INICIAL + 5000     # aba sem proteção nenhuma: não varrer 1M de linhas
    r = LINHA_INICIAL
    while r < teto and not sht.range((r, col)).api.Locked:
        r += 1
    return r - LINHA_INICIAL


def mapear_colunas(headers):
    """headers: lista dos valores da linha 8 (1-based na planilha).
    Devolve {campo: indice_da_coluna}, usando a 1ª ocorrência de cada texto."""
    col_por_texto = {}
    for c, h in enumerate(headers, start=1):
        if h is None:
            continue
        t = str(h).strip()
        if t and t not in col_por_texto:      # 1ª ocorrência vence (ex.: Descrição -> Q)
            col_por_texto[t] = c

    mapa = {}
    faltando = []
    for campo, texto in DST_HEADERS.items():
        if texto in col_por_texto:
            mapa[campo] = col_por_texto[texto]
        else:
            faltando.append(f"{campo} ('{texto}')")
    if faltando:
        raise ValueError("Cabeçalhos não encontrados na aba NFFs: " + "; ".join(faltando))
    return mapa


# ---------------------------------------------------------------------------
# Gravação no destino (xlwings -> preserva VBA/ADFDI)
# ---------------------------------------------------------------------------
def desbloquear_motw(caminho):
    """Remove o Mark-of-the-Web (stream NTFS 'Zone.Identifier') para o Excel confiar no
    arquivo e carregar o add-in do ADFDI — o banner 'origem não confiável' bloqueia
    macros/add-ins e é por isso que o rastreio de linhas não engancha. Idempotente;
    preserva os demais ADS (ex.: tags de DLP). Retorna True se havia MOTW e foi removido."""
    ads = f"{caminho}:Zone.Identifier"
    try:
        os.remove(ads)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        # fallback: alguns ambientes não deixam os.remove no ADS; usa Unblock-File
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Unblock-File -LiteralPath '{caminho}'"],
            check=False, capture_output=True,
        )
        return True


def _achar_book_aberto(nome):
    """Procura, entre as instâncias abertas do Excel, um workbook com este nome; devolve o
    xw.Book ou None. É assim que anexamos à sessão INTERATIVA (add-in ADFDI vivo) em vez de
    subir uma instância de automação."""
    for app in xw.apps:
        for bk in app.books:
            if bk.name.lower() == nome.lower():
                return bk
    return None


def obter_book(arq_destino):
    """Anexa ao workbook se já estiver aberto; senão, abre no Excel e espera aparecer.
    Abre via os.startfile (= duplo-clique, sessão interativa) porque o add-in ADFDI é
    VSTO e NÃO carrega em instância de automação (xw.App)."""
    wb = _achar_book_aberto(arq_destino.name)
    if wb is not None:
        return wb

    desbloquear_motw(arq_destino)   # senão o Excel abre em modo protegido e o add-in não carrega
    os.startfile(str(arq_destino))  # abre numa janela normal do Excel (add-in ADFDI carrega)

    espera_s = 90
    for _ in range(espera_s * 2):
        time.sleep(0.5)             # Excel subir + Workbook_Open/add-in engancharem leva alguns seg
        wb = _achar_book_aberto(arq_destino.name)
        if wb is not None:
            time.sleep(1.5)         # respiro p/ o ADFDI terminar de rastrear a aba
            return wb
    raise RuntimeError(
        f"Abri '{arq_destino.name}', mas ele não apareceu no Excel em {espera_s}s. "
        f"Abra o arquivo manualmente e rode de novo."
    )


def gravar(registros, arq_destino, lote=1):
    """Grava o `lote` de NFFs que cabe no template. Devolve (fatia, total_lotes, offset)."""
    wb = obter_book(arq_destino)
    app = wb.app
    orig_events = app.api.EnableEvents
    app.api.EnableEvents = True                       # ADFDI rastreia via Worksheet_Change
    try:
        sht = wb.sheets[ABA_DESTINO]

        # NÃO desprotegemos a aba. As colunas de DADOS são desbloqueadas — escrevemos direto
        # nelas mesmo com a aba protegida (é o que o create_quick_invoices faz e funciona).
        # As colunas do ADFDI — "Alterado" (C), "Status da Linha" (D) e "Chave" (última) — são
        # BLOQUEADAS e gerenciadas pelo add-in. Desproteger p/ limpar o bloco inteiro apagava a
        # "Chave" (o id que o ADFDI usa p/ rastrear cada linha) e desregulava o rastreio — era
        # por isso que as linhas não subiam pro Oracle.
        ultima_col = sht.used_range.last_cell.column
        ultima_linha = sht.used_range.last_cell.row

        headers = sht.range((8, 1), (8, ultima_col)).value
        if not isinstance(headers, list):
            headers = [headers]
        mapa = mapear_colunas(headers)

        # 0. só cabe o que está desbloqueado (ver fatiar_lote). Valida ANTES de limpar
        #    qualquer coisa: lote inválido não pode deixar a aba pela metade.
        col_id = mapa["id_cabecalho"]
        capacidade = capacidade_linhas(sht, col_id)
        registros, total_lotes, offset = fatiar_lote(registros, capacidade, lote)

        # 1. limpa SÓ as linhas de dados ANTIGAS das colunas que vamos regravar (nunca o bloco
        #    C..última, p/ não encostar em "Alterado"/"Status da Linha"/"Chave"). Atenção: as
        #    células de dados do ADFDI só são desbloqueadas numa FAIXA finita de linhas — abaixo
        #    dela voltam a ser bloqueadas. O `used_range` estoura essa faixa, então limpar até ele
        #    dá "planilha protegida". Descobrimos quantas linhas antigas existem pela coluna-id
        #    (densa: 1..n; leitura é permitida mesmo em célula bloqueada) e limpamos só até lá.
        if ultima_linha >= LINHA_INICIAL:
            id_vals = sht.range((LINHA_INICIAL, col_id), (ultima_linha, col_id)).value
            if not isinstance(id_vals, list):
                id_vals = [id_vals]
            linhas_antigas = [LINHA_INICIAL + k for k, v in enumerate(id_vals) if v not in (None, "")]
            if linhas_antigas:
                fim_antigo = max(linhas_antigas)
                for col in mapa.values():
                    sht.range((LINHA_INICIAL, col), (fim_antigo, col)).clear_contents()

        # 2. grava, um vetor (coluna) por campo (dispara Worksheet_Change -> ADFDI rastreia,
        #    gerando a "Chave" e marcando "Alterado" ▲ em cada linha nova)
        n = len(registros)
        if n:
            fim = LINHA_INICIAL + n - 1
            for campo, col in mapa.items():
                coluna = [[reg[campo]] for reg in registros]
                sht.range((LINHA_INICIAL, col), (fim, col)).value = coluna
    finally:
        app.api.EnableEvents = orig_events

    # Salva no lugar (preserva .xlsm/VBA) para você repassar o arquivo a quem tem acesso de
    # Upload no Oracle. Não fechamos: você revisa a aba NFFs antes de enviar.
    wb.save()
    return registros, total_lotes, offset


# ---------------------------------------------------------------------------
# Relatório no terminal (colorama)
# ---------------------------------------------------------------------------
_LARGURA = 70


def _regra(cor=Fore.CYAN):
    print(cor + "─" * _LARGURA)


def _kv(rotulo, valor):
    """Linha 'rótulo   valor' com o rótulo esmaecido."""
    print(f"    {Style.DIM}{rotulo:<8}{Style.NORMAL}{valor}")


def erro(msg):
    """Mensagem de falha esperada (arquivo não aberto, origem faltando...)."""
    _regra(Fore.RED)
    print(f"{Fore.RED}{Style.BRIGHT}  ✖  {msg}")
    _regra(Fore.RED)


def relatorio(registros, destino, hoje, sem_valor, sem_nota, nao_mapeados, nao_mapeados_forn,
              lote=1, total_lotes=1, offset=0, total_nffs=None):
    """Resumo final: o que foi preenchido, o que revisar e o próximo passo.
    `registros` é só o lote gravado; as pendências são do conjunto inteiro."""
    n = len(registros)
    fim = LINHA_INICIAL + n - 1
    total_nffs = n if total_nffs is None else total_nffs

    _regra()
    print(f"{Fore.CYAN}{Style.BRIGHT}  NFFs de parceiros  →  {destino.name}")
    _regra()
    print(f"{Fore.GREEN}{Style.BRIGHT}  ✔  {n} NFF(s) preenchida(s) e salva(s)")
    _kv("Aba", f"{ABA_DESTINO}  ·  linhas {LINHA_INICIAL}–{fim}")
    if total_lotes > 1:
        _kv("Lote", f"{lote} de {total_lotes}  ·  Débitos {offset + 1}–{offset + n} "
                    f"de {total_nffs} (o template só comporta este tanto por vez)")
    _kv("NFF", f'data {hoje:%d/%m/%Y}  ·  tipo "{TIPO_NFF}"  ·  cond. "{COND_PGTO}"')

    pendencias = []
    if sem_valor:
        pendencias.append(f"{sem_valor} linha(s) sem Valor  (obrigatório — Oracle recusa)")
    if sem_nota:
        pendencias.append(f"{sem_nota} linha(s) sem Nº da Nota")
    if nao_mapeados:
        pendencias.append(f"{len(nao_mapeados)} PAGADOR(es) sem de/para de Unidade: "
                          f"{', '.join(sorted(nao_mapeados))}")
    if nao_mapeados_forn:
        pendencias.append(f"{len(nao_mapeados_forn)} FORNECEDOR(es) sem de/para de Nº "
                          f"(col M em branco): {', '.join(sorted(nao_mapeados_forn))}")
    if pendencias:
        print()
        rotulo = f" (todos os {total_nffs} Débitos)" if total_lotes > 1 else ""
        print(f"{Fore.YELLOW}{Style.BRIGHT}  ⚠  Revisar antes do Upload{rotulo}")
        for p in pendencias:
            print(f"{Fore.YELLOW}    •  {p}")

    print()
    print(f"{Fore.CYAN}  →  Revise a aba {ABA_DESTINO} antes de fazer o "
          f"Upload no Oracle.")
    print(f"    {Style.DIM}cols L/M 'Fornecedor'/'Número do Fornecedor' vêm do de/para (grafia e ID do Oracle); sem de/para o M fica em branco e o L sai como veio da origem")
    if lote < total_lotes:
        print(f"{Fore.CYAN}{Style.BRIGHT}  →  Depois do Upload, rode de novo com "
              f"--lote {lote + 1} para os próximos Débitos.")
    _regra()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Preenche a aba NFFs do CreateQuickInvoices "
                                             "com os Débitos da contratos completos.")
    ap.add_argument("--lote", type=int, default=1,
                    help="qual lote gravar quando os Débitos não cabem no template "
                         "de uma vez (1, 2, ...). Padrão: 1.")
    lote = ap.parse_args().lote

    hoje = date.today()
    try:
        idx, debitos = ler_debitos()
        if not debitos:
            print(f"{Fore.YELLOW}  •  Nenhuma linha com Tipo de Nota = "
                  f"'{FILTRO_TIPO_NOTA}'. Nada a fazer.")
            return
        registros, sem_valor, sem_nota, nao_mapeados, nao_mapeados_forn = \
            montar_registros(idx, debitos, hoje)
        destino = achar_destino()
        gravados, total_lotes, offset = gravar(registros, destino, lote)
    except (OSError, RuntimeError, ValueError) as e:
        erro(str(e))
        return

    relatorio(gravados, destino, hoje, sem_valor, sem_nota, nao_mapeados, nao_mapeados_forn,
              lote=lote, total_lotes=total_lotes, offset=offset, total_nffs=len(registros))


if __name__ == "__main__":
    main()
