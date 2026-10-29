import os
import sys
import re
import pandas as pd
import webview
from datetime import datetime

# sobe 2 níveis: monitor_nff_app -> jobs_backoffice -> retail-apps
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import db
import monitor
import config
import parceiros

class Api:
    def __init__(self):
        self._window = None
        # base cacheada (df_merged, df_projetos) — parte cara (Snowflake). O
        # recorte de mês é feito por cima dela via monitor.montar_mes, barato.
        self._cache_base = None
        self._cache_ts = None
        # planilha de contratos dos parceiros (aba Controle_Emissão)
        self._cache_parceiros = None
        db.init_db()

    def _base(self, force_refresh=False):
        """Devolve (df_merged, df_projetos), carregando/recarregando do Snowflake
        só quando necessário. Centraliza o cache pra carregar_faturas,
        meses_disponiveis e resumo_dashboard compartilharem a mesma base."""
        if self._cache_base is None or force_refresh:
            print(f"[api] carregando base (force_refresh={force_refresh})...", flush=True)
            self._cache_base = monitor.carregar_base()
            self._cache_ts = datetime.now().isoformat()
            print("[api] base carregada", flush=True)
            self._registrar_historico()
        return self._cache_base

    def _registrar_historico(self):
        """Grava no histórico o que mudou desde a última carga.

        Roda aqui, e não no carregar_faturas, porque o histórico tem que cobrir
        todos os meses da base — não só o que o usuário estiver olhando. Se
        dependesse da navegação, mês que ninguém abriu nunca entraria no log.

        Falha aqui não derruba a carga: o histórico é um registro paralelo, e
        ficar sem app por causa dele seria pior que ficar sem uma linha de log.
        """
        try:
            df_merged, df_projetos = self._cache_base
            agora = datetime.now().isoformat(timespec="seconds")
            total = 0
            for m in monitor.listar_meses(df_merged):
                linhas = monitor.montar_mes(df_merged, df_projetos, m['ano'], m['mes'])
                # O mês do recorte faz parte da identidade da fatura no log:
                # fatura que ainda não chegou não tem competência nem nota.
                mes_painel = f"{m['ano']:04d}-{m['mes']:02d}"
                total += db.registrar_snapshot(linhas, agora, mes_painel)
            print(f"[api] historico: {total} mudancas registradas", flush=True)
        except Exception as e:
            print(f"[api] historico nao registrado: {type(e).__name__}: {e}", flush=True)

    def set_window(self, w):
        self._window = w

    # --- NFF ---
    def listar_nffs(self):
        try:
            return {"ok": True, "data": db.listar_todas()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def buscar_nff(self, numero):
        try:
            r = db.buscar((numero or '').strip())
            return {"ok": True, "data": r}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def total_nffs(self):
        try:
            return {"ok": True, "data": db.total_registros()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --- Histórico ---
    def buscar_historico(self, termo=None, limite=500, incluir_carga_inicial=False,
                         mes_painel=None):
        """Mudanças registradas, mais recentes primeiro. `termo` casa com
        acrônimo, projeto ou NFF. A carga inicial fica de fora por padrão."""
        try:
            return {"ok": True, "data": db.buscar_historico(
                termo, limite, incluir_carga_inicial, mes_painel)}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def meses_historico(self):
        """Meses do painel presentes no log, para o filtro da aba."""
        try:
            return {"ok": True, "data": db.meses_historico()}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def resumo_historico(self):
        """Onde o log mora e o que já tem dentro — a aba mostra isso no rodapé
        porque 'onde isso fica salvo?' é a primeira pergunta de quem abre."""
        try:
            return {"ok": True, "data": {
                "caminho": config.get("db_path"),
                "total": db.total_historico(),
                "carga_inicial_em": db.carga_inicial_em(),
            }}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # --- Configuração ---
    def obter_config(self):
        try:
            return {"ok": True, "data": config.como_dict()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def selecionar_arquivo_excel(self):
        """Abre o diálogo de seleção e persiste o caminho escolhido."""
        try:
            atual = config.get("arquivo_excel")
            dir_inicial = os.path.dirname(atual) if atual else ''
            resultado = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=dir_inicial,
                allow_multiple=False,
                file_types=('Planilha Excel (*.xlsm;*.xlsx)', 'Todos os arquivos (*.*)')
            )
            if not resultado:
                return {"ok": True, "data": {"cancelado": True}}
            caminho = resultado if isinstance(resultado, str) else resultado[0]
            config.set_many({"arquivo_excel": caminho})
            return {"ok": True, "data": {"arquivo_excel": caminho}}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def processar_excel(self):
        try:
            arquivo = config.get("arquivo_excel")
            aba = config.get("aba")
            header_linha = int(config.get("header_linha"))
            if not os.path.exists(arquivo):
                return {"ok": False, "error": f"Arquivo não encontrado: {arquivo}"}
            df = pd.read_excel(arquivo, sheet_name=aba, header=header_linha, engine="openpyxl")
            df.columns = df.columns.astype(str).str.strip()

            col = "*Número da NFF"
            if col not in df.columns:
                return {"ok": False, "error": f"Coluna '{col}' não encontrada."}

            serie = df[df[col].notna()][col].astype(str).str.strip()
            serie = serie[~serie.str.contains("Obrigatório|Alterado|▲", case=False, na=False)]
            serie = serie[serie.str.match(r"^[0-9.\-]+$")]
            nffs_planilha = list(serie.unique())

            existentes = db.nffs_existentes()
            novas = [n for n in nffs_planilha if n not in existentes]

            inseridas = db.inserir_nffs(novas, datetime.now().isoformat())

            return {"ok": True, "data": {
                "total_planilha": len(nffs_planilha),
                "ja_registradas": len(existentes),
                "novas": len(novas),
                "inseridas": inseridas
            }}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --- Faturas ---
    def carregar_faturas(self, ano=None, mes=None, force_refresh=False):
        """Faturas de um mês (ano/mes; default = corrente). Fatia a base
        cacheada — só bate no Snowflake quando a base está vazia ou force_refresh."""
        import traceback
        try:
            print(f"[api] carregar_faturas(ano={ano}, mes={mes}, force_refresh={force_refresh})", flush=True)
            df_merged, df_projetos = self._base(force_refresh)
            registros = monitor.montar_mes(df_merged, df_projetos, ano, mes)
            print(f"[api] montar_mes retornou {len(registros)} registros", flush=True)
            return {"ok": True, "data": registros}
        except Exception as e:
            print(f"[api] ERRO em carregar_faturas: {e}", flush=True)
            traceback.print_exc()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def meses_disponiveis(self):
        """Meses disponíveis pro seletor da UI (mais recente primeiro)."""
        import traceback
        try:
            df_merged, _ = self._base()
            return {"ok": True, "data": monitor.listar_meses(df_merged)}
        except Exception as e:
            print(f"[api] ERRO em meses_disponiveis: {e}", flush=True)
            traceback.print_exc()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def ultima_atualizacao(self):
        return {"ok": True, "data": {"ts": self._cache_ts}}

    # --- Exportação ---
    def exportar_excel(self, linhas, nome_sugerido):
        """Recebe a lista de linhas (já filtrada na UI) e grava um .xlsx no
        caminho escolhido pelo usuário via diálogo 'Salvar como'."""
        try:
            if not linhas:
                return {"ok": False, "error": "Nada para exportar."}

            resultado = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=nome_sugerido,
                file_types=('Planilha Excel (*.xlsx)',)
            )
            if not resultado:
                return {"ok": True, "data": {"cancelado": True}}

            caminho = resultado if isinstance(resultado, str) else resultado[0]
            if not caminho.lower().endswith('.xlsx'):
                caminho += '.xlsx'

            df = pd.DataFrame(linhas)
            df.to_excel(caminho, index=False, engine='openpyxl')

            return {"ok": True, "data": {"caminho": caminho, "linhas": len(linhas)}}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --- Faturas Parceiro ---
    def _parceiros(self, force_refresh=False):
        """Lê a planilha de contratos. Cache próprio (arquivo local, barato de
        reler, mas relê a cada clique sem isso)."""
        if self._cache_parceiros is None or force_refresh:
            self._cache_parceiros = parceiros.carregar_planilha()
        return self._cache_parceiros

    def carregar_parceiros(self, ano=None, mes=None, force_refresh=False):
        import traceback
        try:
            regs = self._parceiros(force_refresh)
            return {"ok": True, "data": parceiros.filtrar_mes(regs, ano, mes)}
        except Exception as e:
            print(f"[api] ERRO em carregar_parceiros: {e}", flush=True)
            traceback.print_exc()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def meses_parceiros(self):
        try:
            return {"ok": True, "data": parceiros.listar_meses(self._parceiros())}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def marcar_chegou(self, chave, chegou):
        """Persiste o check de uma linha e atualiza o cache em memória."""
        try:
            parceiros.salvar_marcacao(chave, bool(chegou))
            if self._cache_parceiros:
                for r in self._cache_parceiros:
                    if r["_chave"] == chave:
                        r["Chegou"] = bool(chegou)
                        r["Marcado Em"] = datetime.now().isoformat(timespec="seconds") if chegou else None
                        r["Marcado Por"] = (os.getenv("USERNAME") or "") if chegou else None
            return {"ok": True, "data": {"chave": chave, "chegou": bool(chegou)}}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def selecionar_arquivo_contratos(self):
        try:
            atual = config.get("arquivo_contratos")
            resultado = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=os.path.dirname(atual) if atual else '',
                allow_multiple=False,
                file_types=('Planilha Excel (*.xlsx;*.xlsm)', 'Todos os arquivos (*.*)')
            )
            if not resultado:
                return {"ok": True, "data": {"cancelado": True}}
            caminho = resultado if isinstance(resultado, str) else resultado[0]
            config.set_many({"arquivo_contratos": caminho})
            self._cache_parceiros = None
            return {"ok": True, "data": {"arquivo_contratos": caminho}}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def resumo_dashboard(self, ano=None, mes=None):
        import traceback
        try:
            print(f"[api] resumo_dashboard(ano={ano}, mes={mes}) chamado", flush=True)
            df_merged, df_projetos = self._base()
            f = monitor.montar_mes(df_merged, df_projetos, ano, mes)
            total = len(f)
            chegou = sum(1 for x in f if x['Status'] == 'Chegou')
            chegou_atrasada = sum(1 for x in f if x['Status'] == 'Chegou atrasada')
            atrasadas = sum(1 for x in f if x['Status'] == 'Atrasada')
            pendentes = sum(1 for x in f if x['Status'] == 'Pendente')
            atrasadas_fw = sum(1 for x in f if x['Status'] == 'Atrasada' and x['Forma Recebimento'] == 'FW')
            proximas = sum(1 for x in f if x['Status'] == 'Pendente' and x.get('Dias Restantes') is not None and x['Dias Restantes'] <= 3)
            # Pago: só conta entre as que já chegaram
            ja_chegou = [x for x in f if x['Status'] in ('Chegou','Chegou atrasada')]
            pagas = sum(1 for x in ja_chegou if x.get('Pago'))
            nao_pagas = len(ja_chegou) - pagas
            total_nffs = db.total_registros()
            return {"ok": True, "data": {
                "total_projetos": total,
                "chegou": chegou,
                "chegou_atrasada": chegou_atrasada,
                "atrasadas": atrasadas,
                "atrasadas_fw": atrasadas_fw,
                "pendentes": pendentes,
                "proximas_vencimento": proximas,
                "pagas": pagas,
                "nao_pagas": nao_pagas,
                "total_nffs_db": total_nffs
            }}
        except Exception as e:
            print(f"[api] ERRO em resumo_dashboard: {e}", flush=True)
            traceback.print_exc()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}