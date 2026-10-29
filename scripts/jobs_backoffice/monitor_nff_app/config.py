"""Configuração portável do Monitor NFF.

Resolve caminhos (planilha de NFFs, banco SQLite) de forma que o app rode em
qualquer máquina sem editar código. A prioridade de cada valor é:

    variável de ambiente  >  settings.json (escolha persistida na UI)  >  default

Os defaults são relativos ao home do usuário (`~/Faturas Oracle/...`), então
quem já tinha os arquivos nessa pasta continua funcionando sem mudar nada.
"""
import os
import json

HOME = os.path.expanduser("~")
BASE_DEFAULT = os.path.join(HOME, "Faturas Oracle")

# settings.json fica em pasta gravável do usuário (sobrevive a empacotar como .exe)
SETTINGS_DIR = os.path.join(os.getenv("APPDATA") or HOME, "MonitorNFF")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

REPO_JOBS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DEFAULTS = {
    "arquivo_excel": os.path.join(BASE_DEFAULT, "CreateQuickInvoices.xlsm"),
    "db_path": os.path.join(BASE_DEFAULT, "controle_nff.db"),
    "aba": "NFFs",
    "header_linha": 7,
    # planilha de contratos dos parceiros (aba Controle_Emissão). Default aponta
    # pro arquivo no repo; a UI permite trocar e persiste a escolha.
    "arquivo_contratos": os.path.join(REPO_JOBS, "faturamento_parceiros", "contratos completos.xlsx"),
}

# nome da env var por chave: arquivo_excel -> MONITOR_NFF_ARQUIVO_EXCEL
_ENV_PREFIX = "MONITOR_NFF_"


def _load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get(key):
    """Valor efetivo de uma chave (env > settings.json > default)."""
    env = os.getenv(_ENV_PREFIX + key.upper())
    if env not in (None, ""):
        return env
    val = _load().get(key)
    if val not in (None, ""):
        return val
    return DEFAULTS.get(key)


def set_many(updates):
    """Persiste chaves no settings.json (ignora valores None)."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    data = _load()
    data.update({k: v for k, v in updates.items() if v is not None})
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def como_dict():
    """Snapshot dos valores efetivos — pra exibir na UI."""
    return {k: get(k) for k in DEFAULTS}
