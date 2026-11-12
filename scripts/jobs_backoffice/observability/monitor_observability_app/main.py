"""Monitor Observability retail/backoffice - app desktop (pywebview) com duas abas:
Deploys (GitHub Actions) e Execuções (Prefect).

    python main.py            # abre a janela
    python main.py --debug    # abre com DevTools

GitHub: variável de ambiente GITHUB_TOKEN/GH_TOKEN, ou token do GitHub CLI (`gh auth login` uma vez).
Prefect: só precisa da VPN (FortiClient) conectada.
O monitor_prefect.py desta pasta também roda sozinho como CLI: python monitor_prefect.py --mes 2026-11
"""
import os
import sys

import webview

from api import Api


def main():
    html = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "index.html")
    webview.create_window(
        "Monitor Observability — retail/backoffice",
        html,
        js_api=Api(),
        width=1400,
        height=900,
        min_size=(1100, 700),
        background_color="#1A1A1A",
    )
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
