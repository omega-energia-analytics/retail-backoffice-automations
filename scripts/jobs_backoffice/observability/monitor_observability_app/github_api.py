"""Ponte Python <-> JS: o pywebview expõe os métodos públicos de Api em window.pywebview.api.

Só leitura: consulta a API REST do GitHub Actions, nunca dispara nem re-roda workflow.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

REPO = "serena-analytics/retail-backoffice"
API = "https://api.github.com"
MAX_PAGES = 5  # 100 runs por página, por workflow

# arquivo do workflow -> (tipo, ambiente, nota)
WORKFLOWS = {
    "dbt-stg.yml": ("Views dbt", "stg", "Run verde = views já no ar em stg."),
    "dbt-prod.yml": ("Views dbt", "prod", "Run verde = views já no ar em prod."),
    "prefect-dbt-stg.yml": ("Tabelas dbt", "stg", "Run verde só registra o deployment no Prefect. A tabela popula quando o Prefect roda."),
    "prefect-dbt-prod.yml": ("Tabelas dbt", "prod", "Run verde só registra o deployment no Prefect. A tabela popula quando o Prefect roda."),
    "prefect-stg.yml": ("Flows Python", "stg", "Run verde = flows registrados no Prefect (stg)."),
    "prefect-prod.yml": ("Flows Python", "prod", "Run verde = flows registrados no Prefect (prod)."),
}
BRT = timezone(timedelta(hours=-3))
FAIL = {"failure", "timed_out", "startup_failure"}
ACTIVE = {"in_progress", "queued", "waiting", "pending", "requested"}
GH_PATHS = (r"C:\Program Files\GitHub CLI\gh.exe", r"C:\Program Files (x86)\GitHub CLI\gh.exe")
NO_TOKEN_MSG = (
    "Sem acesso ao GitHub. Instale o GitHub CLI (winget install GitHub.cli) e rode `gh auth login` "
    "(ou defina GITHUB_TOKEN com permissão de leitura em Actions) e clique em Atualizar."
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _gh_token():
    gh = shutil.which("gh") or next((p for p in GH_PATHS if os.path.exists(p)), None)
    if not gh:
        return None
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=15, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def _parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


class Api:
    def __init__(self):
        self._token = None

    # ---------- infra ----------
    def _auth(self):
        if not self._token:
            self._token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or _gh_token()
        if not self._token:
            raise PermissionError(NO_TOKEN_MSG)
        return self._token

    def _request(self, url, accept="application/vnd.github+json", opener=None):
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self._auth()}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "monitor-deploys-app",
        })
        return (opener.open if opener else urllib.request.urlopen)(req, timeout=30)

    def _get(self, path, **params):
        url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        with self._request(url) as resp:
            return json.load(resp)

    @staticmethod
    def _explain(exc):
        if isinstance(exc, PermissionError):
            return str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            if exc.code == 401:
                return "Token do GitHub inválido ou expirado. Rode `gh auth login` de novo."
            if exc.code in (403, 404):
                return (f"Sem permissão em {REPO} (HTTP {exc.code}). Confira acesso ao repo e, se pedir, "
                        "autorize o token na organização (SSO). Também pode ser limite de requisições da API.")
            return f"GitHub respondeu HTTP {exc.code}."
        return f"Falha de rede ao falar com o GitHub ({exc})."

    # ---------- API para o JS ----------
    def config(self):
        return {
            "repo": REPO,
            "repo_url": f"https://github.com/{REPO}",
            "workflows": [
                {"key": f[:-4], "file": f, "kind": k, "env": e, "note": n}
                for f, (k, e, n) in WORKFLOWS.items()
            ],
        }

    def get_runs(self, month):
        """Runs do mês `month` (AAAA-MM, horário de Brasília), de todos os workflows de deploy."""
        try:
            first = datetime.strptime(month, "%Y-%m").replace(tzinfo=BRT)
        except (TypeError, ValueError):
            return {"error": f"Mês inválido: {month!r} (use AAAA-MM)."}
        after = (first + timedelta(days=32)).replace(day=1)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        window = f"{first.astimezone(timezone.utc).strftime(fmt)}..{(after - timedelta(seconds=1)).astimezone(timezone.utc).strftime(fmt)}"
        now = datetime.now(timezone.utc)
        try:
            self._auth()
            with ThreadPoolExecutor(max_workers=len(WORKFLOWS)) as pool:
                chunks = list(pool.map(lambda f: self._workflow_runs(f, window, now), WORKFLOWS))
        except (urllib.error.URLError, TimeoutError, OSError, PermissionError) as exc:
            return {"error": self._explain(exc)}
        runs = [r for c in chunks for r in c[0]]
        runs.sort(key=lambda r: r["when"], reverse=True)
        return {
            "fetched_at": now.isoformat(),
            "truncated": [f[:-4] for f, c in zip(WORKFLOWS, chunks) if c[1]],
            "runs": runs,
        }

    def get_failure(self, run_id):
        """Por que o run falhou: jobs/steps com falha e o final do log do primeiro job que quebrou."""
        try:
            data = self._get(f"/repos/{REPO}/actions/runs/{int(run_id)}/jobs", per_page=100, filter="latest")
        except (urllib.error.URLError, TimeoutError, OSError, PermissionError) as exc:
            return {"error": self._explain(exc)}
        failed = [j for j in data.get("jobs", []) if j.get("conclusion") in FAIL | {"cancelled"}]
        jobs = [{
            "name": j["name"],
            "url": j["html_url"],
            "steps": [s["name"] for s in j.get("steps", []) if s.get("conclusion") in FAIL],
        } for j in failed]
        log = self._job_log_tail(failed[0]["id"]) if failed else None
        return {"jobs": jobs, "log": log}

    # ---------- internos ----------
    def _workflow_runs(self, file, window, now):
        kind, env, _ = WORKFLOWS[file]
        out, truncated = [], False
        for page in range(1, MAX_PAGES + 1):
            data = self._get(f"/repos/{REPO}/actions/workflows/{file}/runs",
                             per_page=100, page=page, created=window)
            batch = data.get("workflow_runs", [])
            for r in batch:
                start = _parse_dt(r.get("run_started_at") or r["created_at"])
                state = (r.get("conclusion") or "unknown") if r["status"] == "completed" else r["status"]
                if r["status"] == "completed":
                    duration = (_parse_dt(r["updated_at"]) - start).total_seconds()
                elif r["status"] == "in_progress":
                    duration = (now - start).total_seconds()
                else:
                    duration = None
                out.append({
                    "id": r["id"],
                    "wf": file[:-4],
                    "number": r["run_number"],
                    "attempt": r.get("run_attempt", 1),
                    "title": r.get("display_title") or "",
                    "branch": r.get("head_branch") or "",
                    "sha": (r.get("head_sha") or "")[:7],
                    "event": r["event"],
                    "actor": (r.get("triggering_actor") or r.get("actor") or {}).get("login", ""),
                    "state": state,
                    "when": start.isoformat(),
                    "duration": duration,
                    "url": r["html_url"],
                })
            if len(batch) < 100:
                break
            if page == MAX_PAGES:
                truncated = True
        return out, truncated

    def _job_log_tail(self, job_id, lines=40):
        """Final do log de um job. O GitHub responde 302 para uma URL assinada, que não pode receber o token."""
        try:
            opener = urllib.request.build_opener(_NoRedirect)
            try:
                resp = self._request(f"{API}/repos/{REPO}/actions/jobs/{job_id}/logs", opener=opener)
                text = resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308) or not exc.headers.get("Location"):
                    return None
                signed = urllib.request.Request(exc.headers["Location"], headers={"User-Agent": "monitor-deploys-app"})
                with urllib.request.urlopen(signed, timeout=30) as resp:
                    text = resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        ts = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ")
        rows = [ts.sub("", ansi.sub("", ln)) for ln in text.splitlines()]
        return "\n".join(rows[-lines:])[-6000:]
