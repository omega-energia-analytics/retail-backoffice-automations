"""Ponte Python <-> JS da aba KPIs (window.pywebview.api.kpis.*). Só leitura.

Duas fontes, com a mesma regra do monitor de NFF — rede só no carregamento, cálculo em memória:
  - monitor_nff_app/monitor.carregar_base(): a MESMA base do painel do monitor de NFF (abre o
    navegador para o SSO do Snowflake). Os KPIs não têm query própria de propósito — assim
    NFF, "Pago", data de pagamento e valores batem com o painel por construção.
  - SharePoint: JSONs do log do quickinvoices, na pasta `log_quick_invoices.pasta_shp` do conf

A aba só chama `get_kpis` quando é aberta (ver app.js), para o SSO não disparar toda vez que o
app abre. O resultado fica em memória; o botão Atualizar é o único caminho para ir à rede de
novo. JSON de log não muda depois de gravado, então na atualização só os novos são baixados.

Falha nos logs não derruba a aba: o KPI 2 não depende deles e segue sendo exibido.

Imports de dados (pandas, kpis, monitor, utils.*) só dentro dos métodos: as abas GitHub e
Prefect rodam só com pywebview + stdlib, e não podem deixar de abrir por falta de uma
dependência desta aba.
"""
import importlib.util
import os
import sys
from datetime import date, datetime, timezone
from urllib.parse import quote

AQUI = os.path.dirname(os.path.abspath(__file__))
# monitor_observability_app -> observability -> jobs_backoffice -> scripts (raiz dos imports
# utils.* e app.*, como no notebook do quickinvoices).
SCRIPTS_ROOT = os.path.abspath(os.path.join(AQUI, "..", "..", ".."))
MONITOR_NFF = os.path.join(SCRIPTS_ROOT, "jobs_backoffice", "monitor_nff_app", "monitor.py")
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

GRAPH = "https://graph.microsoft.com/v1.0"
SNOWFLAKE_MSG = "Não foi possível carregar a base do monitor de NFF. Confira a VPN e o login no navegador"


def carregar_monitor_nff():
    """Importa o monitor.py do monitor_nff_app pelo caminho, com nome próprio.

    Por caminho e não por sys.path: a pasta dele tem api.py e main.py, que colidiriam com os
    deste app.
    """
    if "monitor_nff" in sys.modules:
        return sys.modules["monitor_nff"]
    spec = importlib.util.spec_from_file_location("monitor_nff", MONITOR_NFF)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["monitor_nff"] = mod
    spec.loader.exec_module(mod)
    return mod


class Api:
    def __init__(self):
        self._base = None        # (df_merged com pagamento_efetivo aplicado, df_projetos)
        self._logs = {}          # nome do arquivo -> conteúdo
        self._erro_logs = None
        self._fetched_at = None

    def config(self):
        import kpis

        return {
            "metas": {"kpi1_pct": kpis.META_KPI1_PCT, "kpi2_max": kpis.META_KPI2_MAX},
            "inicio_serie": kpis.INICIO_SERIE,
        }

    # ---------- infra ----------
    @staticmethod
    def _model_parameters():
        from utils.utils_usinas import get_conf_by_project

        return get_conf_by_project("cusd_invoices")["model_parameters"]

    @staticmethod
    def _carregar_base():
        monitor = carregar_monitor_nff()
        df_merged, df_projetos = monitor.carregar_base()
        # As regras do painel, em toda linha: "Pago" e refaturamento (substituída/cancelada).
        monitor.pagamento_efetivo(df_merged)
        monitor.marcar_substituidas(df_merged)
        return df_merged, df_projetos

    def _baixar_logs(self, mp):
        import requests

        from app.quick_invoices_log import obter_token_graph

        drive = mp["input_files"]["shp"]["drive_id"]
        pasta = quote(mp["log_quick_invoices"]["pasta_shp"].strip("/"), safe="/")
        h = {"Authorization": f"Bearer {obter_token_graph()}"}
        url = f"{GRAPH}/drives/{drive}/root:/{pasta}:/children?$top=999"
        while url:
            r = requests.get(url, headers=h, timeout=30)
            if r.status_code == 404:  # pasta ainda não existe: ninguém rodou com o log
                return
            r.raise_for_status()
            corpo = r.json()
            for item in corpo.get("value", []):
                nome = item.get("name", "")
                if nome.endswith(".json") and nome not in self._logs:
                    arq = requests.get(item["@microsoft.graph.downloadUrl"], timeout=30)
                    arq.raise_for_status()
                    self._logs[nome] = arq.json()
            url = corpo.get("@odata.nextLink")

    # ---------- API ----------
    def get_kpis(self, force_refresh=False):
        try:
            import kpis

            mp = self._model_parameters()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Não foi possível preparar a aba (dependências do repo ou "
                             f"conf_cusd_invoices.yml): {exc}"}

        if self._base is None or force_refresh:
            try:
                self._base = self._carregar_base()
            except Exception as exc:  # noqa: BLE001
                return {"error": f"{SNOWFLAKE_MSG} ({exc})"}
            try:
                self._baixar_logs(mp)
                self._erro_logs = None
            except Exception as exc:  # noqa: BLE001
                self._erro_logs = str(exc)
            self._fetched_at = datetime.now(timezone.utc).isoformat()

        try:
            df_merged, df_projetos = self._base
            payload = kpis.montar_payload(
                df_merged, df_projetos,
                None if self._erro_logs else list(self._logs.values()),
                hoje=date.today(),
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Erro ao calcular os KPIs ({exc})"}

        payload["fetched_at"] = self._fetched_at
        payload["avisos"] = []
        if self._erro_logs:
            payload["avisos"].append(
                f"Logs do quickinvoices indisponíveis ({self._erro_logs}). "
                "O KPI 1 não foi calculado; o KPI 2 não depende deles.")
        return payload
