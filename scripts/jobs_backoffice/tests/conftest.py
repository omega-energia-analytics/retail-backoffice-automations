"""Configuração de testes dos jobs de jobs_backoffice.

Coloca a raiz de `scripts/` no sys.path para que os testes possam importar
pacotes do projeto pelo caminho completo (ex.: `from jobs_backoffice.rateio import
...`). Os helpers de teste (ex.: `load_job`) ficam em `testkit.py` — num módulo
próprio, e não aqui, para não colidir com o conftest.py de outros pacotes de teste
(ver docstring de testkit.py).
"""
import os
import sys

# tests/ -> jobs_backoffice/ -> scripts/
SCRIPTS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)
