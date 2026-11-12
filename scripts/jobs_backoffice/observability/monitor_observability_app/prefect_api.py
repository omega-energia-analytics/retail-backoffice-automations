"""Ponte Python <-> JS: o pywebview expõe os métodos públicos de Api em window.pywebview.api."""
import urllib.error
from datetime import datetime, timezone

import monitor_prefect as mp


class Api:
    def __init__(self):
        self._names = {}  # cache id -> nome do deployment/flow, entre atualizações

    def config(self):
        return {
            "ui_url": mp.UI_URL,
            "tags": mp.TAGS,
            "start_month": datetime.fromisoformat(mp.START).astimezone(mp.BRT).strftime("%Y-%m"),
        }

    def get_runs(self, de, ate):
        """Runs dos meses de..ate (AAAA-MM, horário de Brasília). Em erro devolve {"error": ...}."""
        try:
            start, end = mp.month_window([mp.month(de), mp.month(ate)])
        except Exception as exc:
            return {"error": str(exc)}
        now = datetime.now(timezone.utc)
        try:
            runs = mp.fetch_runs(start, end)
            mp.resolve_names(runs, self._names)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"error": f"{mp.VPN_MSG} ({exc})"}
        return {
            "fetched_at": now.isoformat(),
            "runs": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "deployment": r["_name"],
                    "state": r["state_name"],
                    "when": mp.when(r).isoformat(),
                    "duration": mp.run_time(r, now),
                    "message": (r.get("state") or {}).get("message") if r["state_name"] in mp.FAIL_STATES else None,
                }
                for r in runs
            ],
        }
