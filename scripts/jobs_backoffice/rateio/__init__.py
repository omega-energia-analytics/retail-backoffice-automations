"""
Registry de leitores de rateio por distribuidora.

Para adicionar uma distribuidora nova:
  1. Crie um módulo aqui (ex.: coelba.py) seguindo o mesmo contrato dos
     existentes: expor `DISTRIBUIDORA` e `ler_todos_rateios(folder, data_hoje, mes_envio)`.
     Pode usar cpfl_paulista.py ou equatorial_go.py como template.
  2. Importe o módulo abaixo e registre-o em LEITORES.

Nenhuma outra alteração é necessária no pipeline (monit_hist_usina.py).
"""

from .base import validar_soma_rateio
from . import cpfl_paulista, equatorial_go

# distribuidora (str) -> função ler_todos_rateios(folder, data_hoje, mes_envio) -> DataFrame canônico
LEITORES = {
    cpfl_paulista.DISTRIBUIDORA: cpfl_paulista.ler_todos_rateios,
    equatorial_go.DISTRIBUIDORA: equatorial_go.ler_todos_rateios,
}
