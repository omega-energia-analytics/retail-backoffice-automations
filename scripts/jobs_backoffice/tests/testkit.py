"""Helpers de teste dos jobs de jobs_backoffice.

`load_job` carrega scripts de módulo único por caminho via importlib. Vários jobs
têm nome começando com dígito (ex.: `jobs_adhoc/7_extracao_nff_aegea.py`), o que
impede o `import` normal (identificador inválido); e só funciona porque a execução
de cada job está protegida sob `if __name__ == "__main__":` — importar não dispara
o job.

Fica num módulo PRÓPRIO (e não em conftest.py) de propósito: os testes importam
`from testkit import load_job`. Se este helper morasse no conftest.py, o
`from conftest import ...` colidiria com o conftest.py de outros pacotes de teste
(ex.: monitor_nff_app/tests/), que também se chama `conftest` — e o import pegaria
o errado ao rodar a árvore inteira num único `pytest`.
"""
import importlib.util
import os

JOBS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_job(filename, module_name=None):
    """Importa um script de job por nome de arquivo (relativo a jobs_backoffice/)."""
    path = os.path.join(JOBS_DIR, filename)
    name = module_name or "job_" + os.path.splitext(filename)[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
