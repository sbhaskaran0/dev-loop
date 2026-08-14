"""plan — build the delegation plan: lanes with embedded story text,
disjoint file sets, dependencies, model tiers, and token estimates. Overflow
past the budget goes to `deferred`.
"""
from ..artifacts import ArtifactError, correction_note, read_json


def run(ctx) -> str:
    if ctx.args.dry_run:
        from ..config import ROOT
        (ctx.run_dir / "delegation.json").write_text(
            (ROOT / "fixtures" / "delegation.sample.json").read_text(
                encoding="utf-8"), encoding="utf-8")
        return "_dry run: fixture delegation plan copied._"
    stories_path = ctx.run_dir / "stories.json"
    if not stories_path.exists():
        raise RuntimeError(
            "no stories.json — file_stories degraded to pending, so there "
            "are no story ids to plan against (run without --no-linear).")
    pol = ctx.cfg["policy"]
    prompt = ctx.template(
        "plan",
        run_dir=str(ctx.run_dir),
        target_cwd=ctx.cfg["target"]["cwd"],
        linear_team=ctx.cfg.get("linear", {}).get("team", ""),
        deferred_label=ctx.cfg.get("linear", {}).get("deferred_label",
                                                     "loop-deferred"),
        stories_json=stories_path.read_text(encoding="utf-8"),
        budget_tokens=str(ctx.budget.effective_limit - ctx.budget.spent_tokens),
        max_lanes=str(pol["max_lanes"]),
        lane_tiers=str(pol["models"].get("lane_tiers",
                                         {"high": "opus", "medium": "sonnet",
                                          "low": "haiku"})),
    )
    plan_path = ctx.run_dir / "delegation.json"
    for attempt in (1, 2):
        ctx.spawn("plan", prompt)
        try:
            plan = read_json(plan_path, required_keys=("lanes",))
            break
        except ArtifactError as e:
            if attempt == 2:
                raise
            prompt += correction_note(e)
    lanes = plan.get("lanes", [])
    deferred = plan.get("deferred", [])
    return (f"{len(lanes)} lane(s) planned, {len(deferred)} deferred "
            "(pre-review)")
