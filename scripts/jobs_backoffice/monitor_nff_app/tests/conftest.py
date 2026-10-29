"""Configuração de testes do Monitor NFF.

O app é autocontido e usa imports "flat" (`import config`, `from api import Api`),
contando com o próprio diretório no sys.path quando roda como app/.exe. Aqui a
gente replica isso: insere o diretório-pai (o do app) no sys.path pra que os
testes consigam `import config`, `import db`, `import monitor` direto.
"""
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
