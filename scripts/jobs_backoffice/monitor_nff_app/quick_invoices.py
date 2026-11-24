"""Quick Invoices Usinas dentro do monitor de NFF.

Leva para a tela o que o notebook `nb_quick_invoices.ipynb` faz com `CreateQuickInvoices.run()`,
separando em dois passos:

    1. buscar()  — lê o Snowflake e mostra o que iria para a planilha. SEM efeito colateral:
                   não abre o Excel e não grava nada.
    2. enviar()  — escreve as linhas escolhidas na planilha ADFDI (xlwings) e registra o log
                   do KPI, exatamente como o `run()` faz.

O notebook e o `CreateQuickInvoices` continuam existindo e funcionando; aqui só se reaproveita
a mesma classe (query, bloqueio de usinas, rename_maps, escrita), então o resultado na
planilha é o mesmo de lá.

O que a busca acrescenta sobre o notebook
    - Cada NFF vem com um de três status: Nova / Já no Oracle / Processada. "Processada" é a
      que já passou por esta tela (ou pelo notebook) — está no log do KPI, de qualquer
      usuário — e traz a data e a hora do envio. O Oracle manda: se a NFF já está lá, é
      "Já no Oracle". A seleção padrão é só "Nova" — rodar duas buscas sobrepostas não
      duplica nota.
    - O que ficou de fora aparece: usinas barradas por `nff_bloqueados` e linhas descartadas
      por dado incompleto. No notebook isso só saía no print do terminal.
    - Linhas com campo obrigatório vazio (fornecedor, unidade de negócio...) vêm marcadas.

A lógica pura (classificar, montar_linhas, validar_*) não importa Snowflake nem xlwings, para ser
testada sem rede nem Excel. Tudo que é pesado é importado só dentro do serviço.
"""
import getpass
import os
import re
import sys
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pandas as pd

# monitor_nff_app -> jobs_backoffice -> scripts (onde moram app/ e utils/)
_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SCRIPTS not in sys.path:
    sys.path.append(_SCRIPTS)

from app import quick_invoices_log as qlog  # noqa: E402  (precisa do sys.path acima)

import config  # noqa: E402

# A aba NFFs do template ADFDI só desbloqueia 100 linhas (9–108). Escrever além dá
# com_error 0x800A03EC no meio da gravação — e como o fluxo limpa as colunas antes, a
# planilha ficaria pela metade. Ver faturamento_parceiros/README.md ("lotes").
LIMITE_LINHAS_PLANILHA = 100

DIAS_MIN, DIAS_MAX = 1, 365

STATUS_NOVA = "Nova"
STATUS_ORACLE = "Já no Oracle"
# Já passou pela automação (está no log do KPI) mas ainda não consta no Oracle. Mostra quando
# foi enviada. Pode ser reenviada de propósito: o envio substitui a planilha, então repetir
# não duplica nada lá.
STATUS_PROCESSADA = "Processada"

# Campos que a planilha precisa ter preenchidos. Os rename_maps do conf devolvem None para
# valor desconhecido (distribuidora/consórcio novo), e aí a NFF iria com a célula vazia —
# caso real do CEMIGD, ver o conf. Valor: nome amigável no aviso.
CAMPOS_OBRIGATORIOS = {
    "CLIENTE_APELIDO": "unidade de negócio",
    "DISTRIBUIDORA_SIGLA": "fornecedor",
    "NUMERO_DO_FORNECEDOR": "nº do fornecedor",
    "DISTRIBUIDORA_CNPJ": "CNPJ",
}


# ---------------------------------------------------------------------------
# Lógica pura (testável sem rede nem Excel)
# ---------------------------------------------------------------------------

def validar_dias(dias):
    """Dias como inteiro entre DIAS_MIN e DIAS_MAX. Levanta ValueError com mensagem de tela."""
    try:
        n = int(str(dias).strip())
    except (TypeError, ValueError):
        raise ValueError("Informe a quantidade de dias como um número inteiro.") from None
    if not DIAS_MIN <= n <= DIAS_MAX:
        raise ValueError(f"A quantidade de dias deve ficar entre {DIAS_MIN} e {DIAS_MAX}.")
    return n


def validar_data_fim(ate, hoje=None):
    """Data final da janela. Vazio = hoje. Aceita 'AAAA-MM-DD' (input date) ou `date`."""
    hoje = hoje or date.today()
    if ate in (None, ""):
        return hoje
    if isinstance(ate, datetime):
        return ate.date()
    if isinstance(ate, date):
        return ate
    try:
        return datetime.strptime(str(ate).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Data final inválida (use o formato AAAA-MM-DD).") from None


def chaves_validas_para_sql(chaves):
    """Só chaves 100% numéricas entram no SQL do Oracle. NFF é número; o que não for dígito
    não casaria com nada mesmo, e filtrar aqui é o que mantém a lista segura para
    interpolar (nada que vem de fora chega ao SQL como texto livre)."""
    return sorted({c for c in chaves if c and re.fullmatch(r"\d+", c)})


def montar_in_sql(chaves):
    """Lista `'123','456'` para o IN do stg_quick_invoices_oracle.sql."""
    return ",".join(f"'{c}'" for c in chaves_validas_para_sql(chaves))


def classificar(chave, oracle, logs):
    """Estado de uma NFF: Nova / Já no Oracle / Processada. Devolve (status, detalhe).

    `oracle`: dict chave -> True (válida) / False (só versões canceladas), ou None quando a
    consulta ao Oracle não rodou. `logs`: índice de qlog.nffs_lancadas.
    Oracle manda sobre o log: nota que já está no Oracle está lançada, ponto. Só existir
    versão CANCELADA no Oracle não conta como lançada — fica como Nova, com o aviso no detalhe.
    """
    if oracle is not None and chave in oracle:
        if oracle[chave]:
            return STATUS_ORACLE, "Esta NFF já existe no Oracle."
        return STATUS_NOVA, (
            "No Oracle só há versão cancelada desta NFF. Confirme antes de lançar de novo."
        )
    if chave in logs:
        info = logs[chave]
        quem = info.get("usuario") or "alguém"
        return STATUS_PROCESSADA, f"Processada por {quem} em {_quando(info.get('executado_em'))}."
    return STATUS_NOVA, ""


def _quando(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return "data desconhecida"


def alertas_da_linha(linha):
    """Problemas que a linha leva para a planilha (campo vazio, valor zerado)."""
    alertas = []
    for coluna, nome in CAMPOS_OBRIGATORIOS.items():
        if qlog._vazio(linha.get(coluna)) or not str(linha.get(coluna)).strip():
            alertas.append(f"{nome} vazio")
    valor = qlog._numero(linha.get("TOTAL_DA_FATURA"))
    if not isinstance(valor, float):
        alertas.append("valor inválido")
    elif valor <= 0:
        alertas.append("valor zerado")
    return alertas


def montar_linhas(df, acronimos=None, oracle=None, logs=None):
    """df do `CreateQuickInvoices.get_invoices` -> lista de dicts para a tabela.

    `_id` é o índice do df: é com ele que a tela diz quais linhas enviar, porque a mesma NFF
    pode aparecer em mais de uma linha. Datas saem em ISO (ordenam certo; a tela formata).
    Nada aqui devolve NaN — o JSON do pywebview não aceita.

    Só vem marcada a NFF Nova, sem alerta e sem versão cancelada no Oracle (essa o usuário
    marca de propósito, depois de conferir).
    """
    logs = logs or {}
    linhas = []
    for idx, r in df.iterrows():
        nff = qlog._texto_nff(r.get("NOTA_FISCAL"))
        chave = qlog.normaliza_nff(nff)
        status, detalhe = classificar(chave, oracle, logs) if chave else (STATUS_NOVA, "")
        alertas = alertas_da_linha(r)
        so_cancelada_no_oracle = bool(oracle) and chave in oracle and not oracle[chave]
        selecionada = status == STATUS_NOVA and not alertas and not so_cancelada_no_oracle
        info = logs.get(chave) if status == STATUS_PROCESSADA else None
        acro = None
        if acronimos is not None and idx in acronimos.index:
            acro = qlog._texto(acronimos.loc[idx])
        valor = qlog._numero(r.get("TOTAL_DA_FATURA"))
        linhas.append({
            "_id": int(idx),
            "NFF": nff,
            "Acrônimo": acro,
            "Unidade de Negócio": qlog._texto(r.get("CLIENTE_APELIDO")),
            "Fornecedor": qlog._texto(r.get("DISTRIBUIDORA_SIGLA")),
            "Valor": valor if isinstance(valor, float) else None,
            "Emissão": qlog._data(r.get("DATA_DE_EMISSAO_DA_FATURA")),
            "Vencimento": qlog._data(r.get("DATA_DE_VENCIMENTO")),
            "Status": status,
            "Detalhe": detalhe,
            # Quando e por quem foi processada (só no status Processada). ISO: a tela formata.
            "Processada Em": info.get("executado_em") if info else None,
            "Processada Por": info.get("usuario") if info else None,
            "Alertas": alertas,
            # Regra da seleção inicial, guardada para o botão "Selecionar novas" refazê-la.
            "Padrão": selecionada,
            "Selecionada": selecionada,
        })
    return linhas


def montar_barradas(df, motivo):
    """Linhas que ficaram de fora (bloqueadas ou incompletas), para a seção de 'por quê'.

    Os dois df chegam com as colunas da fonte; as que faltam (acrônimo nas incompletas) saem
    vazias em vez de quebrar.
    """
    saida = []
    if df is None or df.empty:
        return saida
    for _, r in df.iterrows():
        valor = qlog._numero(r.get("TOTAL_DA_FATURA"))
        saida.append({
            "NFF": qlog._texto_nff(r.get("NOTA_FISCAL")),
            "Acrônimo": qlog._texto(r.get("ACRONIMO")),
            "Unidade de Negócio": qlog._texto(r.get("CLIENTE_APELIDO")),
            "Valor": valor if isinstance(valor, float) else None,
            "Emissão": qlog._data(r.get("DATA_DE_EMISSAO_DA_FATURA")),
            "Motivo": motivo if motivo != "incompleta" else _campos_faltando(r),
        })
    return saida


def _campos_faltando(linha):
    faltando = [
        nome for coluna, nome in {
            "NOTA_FISCAL": "NFF", "CLIENTE_APELIDO": "unidade de negócio",
            "DISTRIBUIDORA_SIGLA": "fornecedor", "DISTRIBUIDORA_CNPJ": "CNPJ",
            "TOTAL_DA_FATURA": "valor", "DATA_DE_EMISSAO_DA_FATURA": "emissão",
            "DATA_DE_VENCIMENTO_DA_FATURA": "vencimento",
        }.items() if qlog._vazio(linha.get(coluna))
    ]
    return "Dado incompleto: falta " + (", ".join(faltando) if faltando else "algum campo")


def resumir(linhas):
    """Contagens por status para os cards."""
    por_status = {}
    for l in linhas:
        por_status[l["Status"]] = por_status.get(l["Status"], 0) + 1
    return {
        "total": len(linhas),
        "valor_total": round(sum(l["Valor"] or 0 for l in linhas), 2),
        "por_status": por_status,
        "com_alerta": sum(1 for l in linhas if l["Alertas"]),
    }


def validar_envio(ids, linhas_por_id):
    """Confere a seleção antes de tocar na planilha. Devolve a lista de ids na ordem recebida.

    Levanta ValueError com mensagem de tela:
      - nada selecionado;
      - id que não pertence à busca atual (tela desatualizada);
      - mais linhas do que a aba NFFs comporta.

    Reenviar o que acabou de ir NÃO é barrado: o envio substitui a planilha, então repetir
    não duplica nada lá, e quem abortou antes do Upload precisa poder mandar de novo.
    """
    if not ids:
        raise ValueError("Nenhuma NFF selecionada.")
    vistos, ordenados = set(), []
    for i in ids:
        if i in vistos:
            continue
        vistos.add(i)
        if i not in linhas_por_id:
            raise ValueError("A seleção não bate com a última busca. Busque de novo e refaça a seleção.")
        ordenados.append(i)
    if len(ordenados) > LIMITE_LINHAS_PLANILHA:
        raise ValueError(
            f"A planilha comporta {LIMITE_LINHAS_PLANILHA} NFFs por vez e há {len(ordenados)} "
            "selecionadas. Envie em lotes: mande um lote, faça o upload no Oracle e busque de novo."
        )
    return ordenados


# ---------------------------------------------------------------------------
# Serviço (Snowflake, SharePoint, Excel)
# ---------------------------------------------------------------------------

@contextmanager
def _com():
    """O xlwings fala com o Excel por COM, e COM é por thread. Os métodos do pywebview rodam
    em threads do pool, não na principal — sem CoInitialize a gravação falha com 'CoInitialize
    não foi chamado'. Sem pywin32 (outro SO) segue sem."""
    try:
        import pythoncom
    except ImportError:
        yield
        return
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


class QuickInvoicesService:
    def __init__(self):
        self._conn = None
        self._qi_busca = None          # CreateQuickInvoices sem planilha, só para consultar
        self._logs_sharepoint = {}     # cache nome -> registro (log é imutável)
        self._ultima = None            # busca em memória: é ela que o envio escreve
        self._lock = threading.Lock()  # um envio por vez (duplo clique, duas abas)

    # --- infra ---
    def _importar(self):
        try:
            from app.create_quick_invoices import CreateQuickInvoices
        except ImportError as e:
            raise RuntimeError(
                f"Dependência ausente para o Quick Invoices ({e}). "
                "Rode: pip install -r requirements.txt"
            ) from e
        return CreateQuickInvoices

    def _conexao(self):
        if self._conn is None:
            from utils.src_usinas import initialize_snowflake_connection
            self._conn = initialize_snowflake_connection()
        return self._conn

    def _resetar_conexao(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:  # noqa: BLE001 — conexão já morta
            pass
        self._conn = None
        self._qi_busca = None

    def _qi_para_busca(self):
        if self._qi_busca is None:
            self._qi_busca = self._importar()(
                connection=self._conexao(), workbook_path=config.get("arquivo_excel"),
                abrir_planilha=False,
            )
        return self._qi_busca

    def caminho_planilha(self):
        return config.get("arquivo_excel")

    def status(self):
        """Pré-requisitos da tela, sem custo: onde está a planilha e se o xlwings existe."""
        try:
            import xlwings  # noqa: F401
            xlwings_ok = True
        except ImportError:
            xlwings_ok = False
        caminho = self.caminho_planilha()
        return {
            "planilha": caminho,
            "planilha_existe": bool(caminho) and os.path.exists(caminho),
            "xlwings_ok": xlwings_ok,
            "limite_linhas": LIMITE_LINHAS_PLANILHA,
            "dias_min": DIAS_MIN, "dias_max": DIAS_MAX,
        }

    # --- cruzamentos ---
    def _consultar_oracle(self, chaves):
        """dict chave -> válida? para as NFFs que existem no Oracle. Levanta em falha."""
        lista = montar_in_sql(chaves)
        if not lista:
            return {}
        from utils.utils_usinas import get_query

        qi = self._qi_para_busca()
        sql = get_query("quick_invoices_oracle", qi.conf["model_parameters"]).replace("{CHAVES}", lista)
        df = pd.read_sql(sql, con=self._conexao())
        df.columns = df.columns.str.upper().str.strip()
        return {str(c): bool(v) for c, v in zip(df["CHAVE"], df["VALIDA"])}

    def _consultar_logs(self, desde):
        """Índice das NFFs já enviadas por alguém. Disco primeiro; SharePoint é melhor
        esforço — sem rede ainda dá para saber o que ESTA máquina enviou."""
        avisos = []
        registros = qlog.ler_logs_locais(desde=desde)
        try:
            mp = self._qi_para_busca().conf["model_parameters"]
            registros += qlog.baixar_logs_sharepoint(
                qlog.obter_token_graph(),
                mp["input_files"]["shp"]["drive_id"],
                mp["log_quick_invoices"]["pasta_shp"],
                desde=desde, cache=self._logs_sharepoint,
            )
        except Exception as e:  # noqa: BLE001
            avisos.append(
                "Não consegui ler os logs do SharePoint — só os envios desta máquina foram "
                f"considerados para marcar 'Processada' ({type(e).__name__}: {e})."
            )
        return qlog.nffs_lancadas(registros), avisos

    # --- passo 1: buscar ---
    def buscar(self, dias, ate=None):
        dias = validar_dias(dias)
        ate = validar_data_fim(ate)
        desde = ate - timedelta(days=dias)

        try:
            qi = self._qi_para_busca()
            df = qi.get_invoices(days=dias, to_date=ate)
        except RuntimeError:
            # Conexão do Snowflake costuma morrer parada (sessão expira). Uma tentativa
            # com conexão nova resolve o caso comum; erro de verdade volta igual.
            self._resetar_conexao()
            qi = self._qi_para_busca()
            df = qi.get_invoices(days=dias, to_date=ate)

        avisos = list(qi.avisos)

        chaves = {qlog.normaliza_nff(n) for n in df["NOTA_FISCAL"]} - {None}
        try:
            oracle = self._consultar_oracle(chaves)
        except Exception as e:  # noqa: BLE001
            oracle = None
            avisos.append(
                "Não consegui consultar o Oracle — as NFFs não foram conferidas contra ele, então "
                f"'Nova' aqui só significa 'não está nos logs' ({type(e).__name__}: {e})."
            )

        logs, avisos_logs = self._consultar_logs(desde)
        avisos += avisos_logs

        linhas = montar_linhas(df, getattr(qi, "acronimos", None), oracle, logs)
        barradas = montar_barradas(getattr(qi, "bloqueadas_no_periodo", None), "Usina em nff_bloqueados")
        incompletas = montar_barradas(getattr(qi, "incompletas_no_periodo", None), "incompleta")

        self._ultima = {
            "df": df,
            "linhas": {l["_id"]: l for l in linhas},
            "dias": dias,
            "ate": ate,
        }

        return {
            "linhas": linhas,
            "resumo": resumir(linhas),
            "barradas": barradas,
            "incompletas": incompletas,
            "avisos": avisos,
            "janela": {"de": desde.isoformat(), "ate": ate.isoformat(), "dias": dias},
            "buscado_em": datetime.now().isoformat(timespec="seconds"),
            "oracle_conferido": oracle is not None,
        }

    # --- passo 2: enviar ---
    def enviar(self, ids):
        with self._lock:
            if self._ultima is None:
                raise ValueError("Faça uma busca antes de enviar.")
            ids = validar_envio([int(i) for i in ids or []], self._ultima["linhas"])

            caminho = self.caminho_planilha()
            if not caminho or not os.path.exists(caminho):
                raise FileNotFoundError(f"Planilha não encontrada: {caminho}")

            df_sel = self._ultima["df"].loc[ids].copy()
            # A data da NFF é a do envio (como no run()), não a da busca — a tela pode ficar
            # aberta de um dia para o outro.
            df_sel["DATA_DE_CRIACAO"] = date.today()

            CreateQuickInvoices = self._importar()
            with _com():
                qi = CreateQuickInvoices(
                    connection=self._conexao(), workbook_path=caminho, abrir_planilha=True
                )
                qi.send_to_quick_invoices(df_sel)
                # Depois da escrita, como no run(): só loga o que de fato foi escrito.
                status_log = qlog.registrar_run(
                    df_sel, qi.conf,
                    parametros={
                        "days": self._ultima["dias"],
                        "to_date": self._ultima["ate"],
                        "origem": "monitor_nff",
                    },
                )
                del qi

            valores = [self._ultima["linhas"][i]["Valor"] or 0 for i in ids]
            # A mesma identidade e o mesmo formato de data que o log grava, para a linha mostrar
            # agora o que mostraria depois de uma nova busca.
            agora = datetime.now().astimezone().isoformat(timespec="seconds")
            quem = getpass.getuser()
            for i in ids:
                linha = self._ultima["linhas"][i]
                linha["Status"] = STATUS_PROCESSADA
                linha["Processada Em"], linha["Processada Por"] = agora, quem
                linha["Detalhe"] = f"Processada por {quem} em {_quando(agora)}."
                linha["Selecionada"] = False

            return {
                "processada_em": agora,
                "processada_por": quem,
                "enviadas": len(ids),
                "valor_total": round(sum(valores), 2),
                "ids": ids,
                "log": status_log,
                "planilha": caminho,
            }
