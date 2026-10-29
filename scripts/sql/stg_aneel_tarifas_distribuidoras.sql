select 
    "SigAgente",
    TO_DATE("DatInicioVigencia") AS "DatInicioVigencia",
    TO_DATE("DatFimVigencia") AS "DatFimVigencia",
    "DscBaseTarifaria",
    "DscSubGrupo",
    "DscModalidadeTarifaria",
    "DscClasse",
    "DscSubClasse",
    TO_DOUBLE(REPLACE("VlrTUSD", ',', '.')) AS "VlrTUSD",
    TO_DOUBLE(REPLACE("VlrTE", ',', '.')) AS "VlrTE"
from CONSUME_PROD.ANEEL.TARIFAS_DISTRIBUIDORAS
where "DscSubClasse" = 'Baixa Renda'
  and "DscDetalhe" = 'Não se aplica'
  and "DscBaseTarifaria" = 'Tarifa de Aplicação'
  and "DscModalidadeTarifaria" = 'Convencional'
