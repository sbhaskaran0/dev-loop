"""Metric collection for the job-applier target.

Pure Python, read-only. Every metric degrades to
{"instrumented": false, "note": ...} instead of crashing — the evaluator is
told what it can and cannot see. The postings DB is opened read-only (the
target's 09:00 refresh may still be writing).
"""
import json
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _yield_metrics(db_path: Path, wait_min: int) -> dict:
    if not db_path.exists():
        return {"instrumented": False, "note": f"no postings db at {db_path}"}
    deadline = time.time() + wait_min * 60
    today = date.today().isoformat()
    while True:
        conn = _ro_connect(db_path)
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT rowid, * FROM refresh_runs "
                "WHERE date(run_at) >= date('now','-14 days') ORDER BY rowid")]
        finally:
            conn.close()
        if any((r.get("run_at") or "").startswith(today) for r in rows) \
                or time.time() >= deadline:
            break
        time.sleep(60)
    by_day: dict[str, dict] = {}
    for r in rows:
        d = (r.get("run_at") or "")[:10]
        day = by_day.setdefault(d, {"date": d, "runs": 0, "new": 0,
                                    "new_qualifying": None,
                                    "new_title_matched": None,
                                    "boards_failed": 0})
        day["runs"] += 1
        day["new"] += r.get("new_count") or 0
        for k in ("new_qualifying", "new_title_matched"):
            if r.get(k) is not None:
                day[k] = (day[k] or 0) + r[k]
        day["boards_failed"] = len(json.loads(r.get("companies_failed") or "[]"))
    days = sorted(by_day.values(), key=lambda d: d["date"], reverse=True)
    note = None
    if not any((r.get("run_at") or "").startswith(today) for r in rows):
        note = "no refresh run recorded today (waited, then proceeded)"
    return {"instrumented": True, "note": note, "per_day": days}


def _application_metrics(apps_path: Path, prep_dir: Path) -> dict:
    if not apps_path.exists():
        return {"instrumented": False, "note": f"no {apps_path}"}
    apps = json.loads(apps_path.read_text(encoding="utf-8"))
    if isinstance(apps, dict):
        apps = apps.get("applications", [])
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    recent: dict[str, dict] = {}
    for a in apps:
        d = a.get("date", "")
        if d >= cutoff:
            day = recent.setdefault(d, {"date": d, "submitted": 0,
                                        "manual_submission": 0, "other": 0})
            status = a.get("status", "other")
            day[status if status in day else "other"] += 1
    # Weak attempted-proxy until the JOB-103 run ledger exists: prep files'
    # snapshot_at dates say an application was at least prepped that day.
    attempted: dict[str, int] = {}
    proxy_note = ("denominator NOT instrumented (JOB-103 open): 'attempted' "
                  "is a weak proxy from data/prep snapshot files")
    if prep_dir.is_dir():
        for f in prep_dir.glob("*.json"):
            if f.name.endswith(".sheet.json"):
                continue
            try:
                snap = json.loads(f.read_text(encoding="utf-8"))
                d = (snap.get("snapshot_at") or "")[:10]
                if d >= cutoff:
                    attempted[d] = attempted.get(d, 0) + 1
            except (json.JSONDecodeError, OSError):
                continue
    return {"instrumented": True, "note": proxy_note,
            "total_tracked": len(apps),
            "last_7_days": sorted(recent.values(), key=lambda d: d["date"],
                                  reverse=True),
            "attempted_proxy_by_day": attempted}


def _bug_metrics(bug_path: Path) -> dict:
    if not bug_path.exists():
        return {"instrumented": True, "open": [], "note": "no reports yet"}
    reports = []
    for line in bug_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                reports.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    open_reports = [r for r in reports if r.get("status") == "open"]
    return {"instrumented": True, "total": len(reports),
            "open": open_reports}


def _token_metrics(usage_path: Path) -> dict:
    if not usage_path.exists():
        return {"instrumented": False, "note": f"no {usage_path}"}
    hook_sessions: dict[str, dict] = {}
    webchat: list[dict] = []
    for line in usage_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("source") == "webchat":
            webchat.append(rec)
        elif "tokens" in rec:  # Stop-hook per-session totals (authoritative)
            hook_sessions[rec.get("session_id")] = rec
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    by_day: dict[str, float] = {}
    for rec in hook_sessions.values():
        d = (rec.get("updated_at") or "")[:10]
        if d and d >= cutoff:
            by_day[d] = round(by_day.get(d, 0) + (rec.get("cost_usd") or 0), 2)
    # webchat records only count when their session has no hook record
    for rec in webchat:
        if rec.get("session_id") in hook_sessions:
            continue
        d = (rec.get("ts") or "")[:10]
        if d and d >= cutoff:
            by_day[d] = round(by_day.get(d, 0) + (rec.get("cost_usd") or 0), 2)
    return {"instrumented": True, "cost_usd_by_day": by_day,
            "sessions_tracked": len(hook_sessions),
            "note": "hook records win; webchat records fill uncovered "
                    "sessions only"}


def collect(cfg: dict, run_dir: Path) -> dict:
    target = Path(cfg["target"]["cwd"])
    p = cfg.get("adapter_paths", {})
    wait_min = int(cfg["policy"].get("refresh_wait_min", 10))

    def safely(fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # a broken metric must not kill collect
            return {"instrumented": False, "note": f"{type(e).__name__}: {e}"}

    metrics = {
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": str(target),
        "yield": safely(_yield_metrics, target / p.get("db", "data/postings.db"),
                        wait_min),
        "applications": safely(_application_metrics,
                               target / p.get("applications", ""),
                               target / p.get("prep_dir", "data/prep")),
        "bugs": safely(_bug_metrics,
                       target / p.get("bug_reports", "data/bug-reports.jsonl")),
        "tokens": safely(_token_metrics, target / p.get("token_usage", "")),
    }
    digest = target / "data" / "digest-latest.md"
    if digest.exists():
        metrics["digest_excerpt"] = digest.read_text(encoding="utf-8")[:4000]
    return metrics
