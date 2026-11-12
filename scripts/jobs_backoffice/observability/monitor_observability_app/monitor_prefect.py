"""Monitor dos flow runs do Prefect (tags retail + backoffice).

Reproduz o filtro da tela Runs do Prefect UI (prefect3.srna.co/v2/runs):
todos os estados exceto Scheduled, tags backoffice+retail, subflows incluídos,
janela por expected_start_time, ordenado por START_TIME_DESC.

Sem autenticação: só precisa da VPN (FortiClient) conectada. Só stdlib, sem pip.

Uso:
    python monitor_prefect.py                  # relatório único
    python monitor_prefect.py --watch 5        # atualiza a cada 5 min, bipa em falha nova
    python monitor_prefect.py --mes 2026-10    # só outubro/2026 (mês inteiro, horário de Brasília)
    python monitor_prefect.py --mes 2026-08 2026-10        # agosto a outubro/2026
    python monitor_prefect.py --end 2026-11-10T02:59:00Z   # janela idêntica à URL original

Exit code (modo único): 0 = ok, 1 = algum deployment com último run em falha,
2 = sem acesso ao servidor.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

UI_URL = "https://prefect3.srna.co/v2"
API_URL = "https://prefect3.srna.co/api"
TAGS = ["backoffice", "retail"]
# Todos os estados exceto Scheduled (igual ao filtro padrão da tela Runs).
STATES = [
    "Late", "Resuming", "AwaitingRetry", "AwaitingConcurrencySlot", "Pending", "Submitting",
    "InfrastructurePending", "Paused", "Suspended", "Running", "Retrying", "Completed", "Cached",
    "Cancelled", "Cancelling", "Crashed", "Failed", "TimedOut",
]
START = "2026-06-01T03:00:00Z"  # início do histórico (00:00 de 01/06/2026 em Brasília)
PAGE = 200

OK_STATES = {"Completed", "Cached"}
FAIL_STATES = {"Failed", "TimedOut", "Crashed"}
ACTIVE_STATES = {
    "InfrastructurePending", "Resuming", "Pending", "Suspended", "Late", "Cancelling", "Running",
    "Retrying", "AwaitingRetry", "AwaitingConcurrencySlot", "Paused", "Submitting",
}

BRT = timezone(timedelta(hours=-3))
VPN_MSG = f"Sem acesso a {API_URL} - confira se a VPN (FortiClient) está conectada."


def post(path, body):
    req = urllib.request.Request(
        API_URL + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_runs(start, end):
    flt = {
        "flow_runs": {
            "tags": {"all_": TAGS},
            "state": {"name": {"any_": STATES}},
            "expected_start_time": {"after_": start, "before_": end},
        }
    }
    runs, offset = [], 0
    while True:
        page = post("/flow_runs/filter", {**flt, **{"sort": "START_TIME_DESC", "limit": PAGE, "offset": offset}})
        runs += page
        if len(page) < PAGE:
            return runs
        offset += PAGE


def resolve_names(runs, cache):
    """Nome de exibição por run: deployment, ou flow quando o run não tem deployment."""
    dep_ids = sorted({r["deployment_id"] for r in runs if r["deployment_id"]} - cache.keys())
    flow_ids = sorted({r["flow_id"] for r in runs if r["flow_id"]} - cache.keys())
    for i in range(0, len(dep_ids), PAGE):
        for d in post("/deployments/filter", {"deployments": {"id": {"any_": dep_ids[i:i + PAGE]}}, "limit": PAGE}):
            cache[d["id"]] = d["name"]
    for i in range(0, len(flow_ids), PAGE):
        for f in post("/flows/filter", {"flows": {"id": {"any_": flow_ids[i:i + PAGE]}}, "limit": PAGE}):
            cache[f["id"]] = f["name"]
    for r in runs:
        r["_name"] = cache.get(r["deployment_id"]) or cache.get(r["flow_id"]) or "(desconhecido)"


def ts(value):
    return datetime.fromisoformat(value) if value else None


def brt(dt, fmt="%d/%m %H:%M"):
    return dt.astimezone(BRT).strftime(fmt) if dt else "-"


def dur(seconds):
    if seconds is None:
        return "-"
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def run_time(r, now):
    if r["state_name"] in ("Running", "Retrying") and r["start_time"]:
        return (now - ts(r["start_time"])).total_seconds()
    return r["total_run_time"]


def when(r):
    return ts(r["start_time"]) or ts(r["expected_start_time"])


def month(value):
    try:
        return datetime.strptime(value, "%Y-%m").replace(tzinfo=BRT)
    except ValueError:
        raise argparse.ArgumentTypeError(f"mês inválido: {value!r} (use AAAA-MM)")


def month_window(months):
    """Meses inteiros no horário de Brasília, do primeiro ao último informado -> (início, fim) ISO."""
    first, last = min(months), max(months)
    after_last = (last + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (after_last - timedelta(microseconds=1)).isoformat()


def report(runs, start, end, now):
    """Imprime o relatório e devolve True se algum deployment tem o último run em falha."""
    by = defaultdict(list)
    for r in runs:
        by[r["_name"]].append(r)

    rows = []
    for name, rs in by.items():
        rs.sort(key=when, reverse=True)
        finished = [r for r in rs if r["state_name"] not in ACTIVE_STATES]
        fails = [r for r in rs if r["state_name"] in FAIL_STATES]
        oks = [r for r in rs if r["state_name"] in OK_STATES]
        completed = [r["total_run_time"] for r in rs if r["state_name"] == "Completed" and r["total_run_time"]]
        last = finished[0] if finished else None
        rows.append({
            "alert": bool(last) and last["state_name"] in FAIL_STATES,
            "name": name,
            "runs": len(rs),
            "fails": len(fails),
            "ok": 100 * len(oks) / (len(oks) + len(fails)) if oks or fails else None,
            "last": last,
            "last_fail": fails[0] if fails else None,
            "avg": sum(completed) / len(completed) if completed else None,
        })
    rows.sort(key=lambda x: (not x["alert"], x["name"]))

    print(f"Prefect {'+'.join(TAGS)} | {brt(ts(start), '%d/%m/%Y %H:%M')} -> "
          f"{brt(ts(end) or now, '%d/%m/%Y %H:%M')} (BRT) | {len(runs)} runs")
    print(", ".join(f"{n} {s}" for s, n in Counter(r["state_name"] for r in runs).most_common()))
    print()
    w = max([len(x["name"]) for x in rows] + [10])
    print(f"   {'DEPLOYMENT':<{w}}  {'RUNS':>5}  {'FALHAS':>6}  {'SUCESSO':>7}  "
          f"{'ULTIMO RUN':<21}  {'ULT. FALHA':<11}  {'DUR. MEDIA':>10}")
    for x in rows:
        last = f"{x['last']['state_name']} {brt(when(x['last']))}" if x["last"] else "-"
        pct = f"{x['ok']:.1f}%" if x["ok"] is not None else "-"
        print(f"{'!!' if x['alert'] else '  '} {x['name']:<{w}}  {x['runs']:>5}  {x['fails']:>6}  {pct:>7}  "
              f"{last:<21}  {brt(when(x['last_fail'])) if x['last_fail'] else '-':<11}  {dur(x['avg']):>10}")

    active = [r for r in runs if r["state_name"] in ACTIVE_STATES]
    if active:
        print(f"\nEM ANDAMENTO / PENDENTES ({len(active)})")
        for r in sorted(active, key=when, reverse=True):
            print(f"  {r['_name']:<{w}}  {r['state_name']:<12}  {brt(when(r))}  ({dur(run_time(r, now))})")
    return any(x["alert"] for x in rows)


def main():
    p = argparse.ArgumentParser(description="Monitor dos flow runs retail/backoffice no Prefect.")
    p.add_argument("--start", default=START, help=f"início da janela, ISO UTC (padrão {START})")
    p.add_argument("--end", help="fim da janela, ISO UTC (padrão: agora)")
    p.add_argument("--mes", nargs="+", type=month, metavar="AAAA-MM",
                   help="mês inteiro (ou intervalo: primeiro e último mês); substitui --start/--end")
    p.add_argument("--watch", type=float, metavar="MIN", help="atualiza a cada MIN minutos")
    a = p.parse_args()
    if a.mes and (a.end or a.start != START):
        p.error("use --mes OU --start/--end, não os dois")

    seen, names, first = set(), {}, True
    while True:
        now = datetime.now(timezone.utc)
        start, end = month_window(a.mes) if a.mes else (a.start, a.end or now.isoformat())
        try:
            runs = fetch_runs(start, end)
            resolve_names(runs, names)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"\n{VPN_MSG} ({exc})", file=sys.stderr)
            if not a.watch:
                return 2
            runs = None
        if runs is not None:
            if a.watch:
                os.system("cls" if os.name == "nt" else "clear")
            alert = report(runs, start, end, now)
            fails = {r["id"] for r in runs if r["state_name"] in FAIL_STATES}
            beep = not first and bool(fails - seen)
            seen, first = fails, False
            if not a.watch:
                return 1 if alert else 0
            print(f"\nAtualizado {datetime.now(BRT):%H:%M:%S} - próxima em {a.watch:g} min (Ctrl+C sai)\n",
                  end="\x07" if beep else "", flush=True)
        time.sleep(a.watch * 60)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
