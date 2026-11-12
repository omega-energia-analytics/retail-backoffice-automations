"""Ponte Python <-> JS: o pywebview expõe os métodos públicos de Api em window.pywebview.api.

Um sub-objeto por monitor (window.pywebview.api.github.*, .prefect.*, .kpis.*), porque eles
têm métodos com o mesmo nome (config, get_runs).
"""
import github_api
import kpi_api
import prefect_api


class Api:
    def __init__(self):
        self.github = github_api.Api()
        self.prefect = prefect_api.Api()
        self.kpis = kpi_api.Api()
