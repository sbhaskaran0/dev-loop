"""collect — pure-Python metrics snapshot into runs/<date>/metrics.json."""
import shutil
import subprocess
from importlib import import_module

from .. import claude_proc
from ..artifacts import write_json
from ..config import ROOT


def _preflight(ctx) -> list[str]:
    notes = []
    if not claude_proc.find_cli():
        notes.append("WARNING: no claude CLI found — Claude stages will fail")
    if shutil.which("gh"):
        gh = subprocess.run(["gh", "auth", "status"], capture_output=True)
        if gh.returncode != 0:
            notes.append("WARNING: gh auth status failed — PR creation "
                         "will fail")
    else:
        notes.append("WARNING: gh CLI not found")
    return notes


def run(ctx) -> str:
    if ctx.args.dry_run:
        sample = ROOT / "fixtures" / "metrics.sample.json"
        (ctx.run_dir / "metrics.json").write_text(
            sample.read_text(encoding="utf-8"), encoding="utf-8")
        return "_dry run: fixture metrics copied._"
    notes = _preflight(ctx)
    adapter = import_module(ctx.cfg["adapter"])
    metrics = adapter.collect(ctx.cfg, ctx.run_dir)
    metrics["preflight"] = notes
    write_json(ctx.run_dir / "metrics.json", metrics)
    lines = [f"- preflight: {n}" for n in notes] or ["- preflight clean"]
    for key in ("yield", "applications", "bugs", "tokens"):
        m = metrics.get(key, {})
        flag = "ok" if m.get("instrumented") else f"NOT instrumented ({m.get('note')})"
        lines.append(f"- {key}: {flag}")
    return "\n".join(lines)
