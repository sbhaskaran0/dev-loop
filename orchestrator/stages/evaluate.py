"""evaluate — Claude scores the metrics against goals.md + open Linear
stories + the target's de-scope list, and proposes pareto-optimal candidate
enhancements. Runs with cwd = the REAL target repo (exact casing) so the
Linear MCP and CLAUDE.md load. Read-only by prompt: its only outputs are
runs/<date>/evaluation.md + candidates.json.
"""
from pathlib import Path

from ..artifacts import ArtifactError, correction_note, read_json, read_text
from ..config import ROOT


def _context_docs(ctx) -> str:
    parts = []
    for rel in ctx.cfg.get("context_docs", []):
        p = ctx.target_path(rel)
        if p.exists():
            parts.append(f"--- {rel} ---\n{p.read_text(encoding='utf-8')[:8000]}")
    return "\n\n".join(parts) or "(none)"


def _recent_logs(ctx, n: int = 7) -> str:
    runs = sorted((ROOT / "runs").iterdir(), reverse=True)
    parts = []
    for d in runs:
        if d.name == ctx.date or not d.is_dir():
            continue
        log = d / "log.md"
        if log.exists():
            parts.append(f"--- run {d.name} ---\n"
                         f"{log.read_text(encoding='utf-8')[:2500]}")
        if len(parts) >= n:
            break
    return "\n\n".join(parts) or "(no prior runs)"


def run(ctx) -> str:
    if ctx.args.dry_run:
        (ctx.run_dir / "evaluation.md").write_text(
            "# Dry-run evaluation\n\n(fixture)\n", encoding="utf-8")
        (ctx.run_dir / "candidates.json").write_text(
            (ROOT / "fixtures" / "candidates.sample.json").read_text(
                encoding="utf-8"), encoding="utf-8")
        return "_dry run: fixture candidates copied._"
    goals = (ROOT / "goals.md").read_text(encoding="utf-8") \
        if (ROOT / "goals.md").exists() else "(no goals.md)"
    metrics = (ctx.run_dir / "metrics.json").read_text(encoding="utf-8")
    prompt = ctx.template(
        "evaluate",
        run_dir=str(ctx.run_dir),
        target_cwd=ctx.cfg["target"]["cwd"],
        linear_team=ctx.cfg.get("linear", {}).get("team", ""),
        loop_label=ctx.cfg.get("linear", {}).get("loop_label", "loop"),
        metrics_json=metrics,
        goals=goals,
        context_docs=_context_docs(ctx),
        recent_logs=_recent_logs(ctx),
        no_linear=("Linear is DISABLED this run — skip reading Linear and "
                   "note that in the scorecard." if ctx.args.no_linear else ""),
    )
    eval_path = ctx.run_dir / "evaluation.md"
    cand_path = ctx.run_dir / "candidates.json"
    for attempt in (1, 2):
        ctx.spawn("evaluate", prompt)
        try:
            read_text(eval_path, min_chars=200)
            cands = read_json(cand_path, required_keys=("candidates",))
            break
        except ArtifactError as e:
            if attempt == 2:
                raise
            prompt += correction_note(e)
    n = len(cands.get("candidates", []))
    return (f"scorecard written; **{n} candidate enhancement(s)** proposed "
            f"(see evaluation.md / candidates.json)")
