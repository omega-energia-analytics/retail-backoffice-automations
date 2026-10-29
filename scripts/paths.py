"""Resolução central de caminhos do retail-apps.

Todos os caminhos são derivados da localização DESTE arquivo (a raiz do
`retail-apps/`), e não do diretório de trabalho (CWD). Isso remove os paths
relativos hardcoded que estavam espalhados pelo código e que só funcionavam se
o script fosse rodado de um diretório específico:

    "retail-apps\\query\\"   (distribuidoras — exigia CWD = raiz do repo)
    "../query/"              (utils_ingestion — exigia CWD = subpasta do retail-apps)
    "query/"                 (utils_usinas — exigia CWD = retail-apps)

Com o helper, o mesmo fluxo funciona de qualquer CWD. Bônus: quando/se as
pastas forem renomeadas (ex.: query/ -> sql/), basta trocar a constante aqui.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONF_DIR = ROOT / "conf"
QUERY_DIR = ROOT / "sql"  # pasta sql/ (antiga query/); constante mantida p/ não mexer nos imports


def conf_path(filename):
    """Caminho absoluto de um arquivo dentro de conf/."""
    return CONF_DIR / filename


def query_path(filename):
    """Caminho absoluto de um arquivo dentro de sql/."""
    return QUERY_DIR / filename
