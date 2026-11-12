"""Ponte Python <-> JS: o pywebview expõe os métodos públicos de Api em window.pywebview.api.

Um sub-objeto por monitor (window.pywebview.api.github.*, window.pywebview.api.prefect.*),
porque os dois têm métodos com o mesmo nome (config, get_runs).
"""
import github_api
import prefect_api


class Api:
    def __init__(self):
        self.github = github_api.Api()
        self.prefect = prefect_api.Api()
