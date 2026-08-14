"""review — the adversarial gate. A separate session argues for codebase
health, scalability, and product hygiene against the delegation plan; it can
amend or veto lanes. Its output, delegation.approved.json, is what execute
actually runs.
"""
from ..artifacts import ArtifactError, correction_note, read_json


def run(ctx) -> str:
    plan_path = ctx.run_dir / "delegation.json"
    read_json(plan_path, required_keys=("lanes",))
    if ctx.args.dry_run:
        (ctx.run_dir / "delegation.approved.json").write_text(
            plan_path.read_text(encoding="utf-8"), encoding="utf-8")
        return "_dry run: plan approved verbatim._"
    prompt = ctx.template(
        "review",
        run_dir=str(ctx.run_dir),
        target_cwd=ctx.cfg["target"]["cwd"],
        delegation_json=plan_path.read_text(encoding="utf-8"),
        metrics_json=(ctx.run_dir / "metrics.json").read_text(
            encoding="utf-8")[:6000],
    )
    approved_path = ctx.run_dir / "delegation.approved.json"
    for attempt in (1, 2):
        ctx.spawn("review", prompt)
        try:
            approved = read_json(approved_path, required_keys=("lanes",))
            break
        except ArtifactError as e:
            if attempt == 2:
                raise
            prompt += correction_note(e)
    # Hard safety check the reviewer cannot waive: lanes must not share files.
    seen: dict[str, str] = {}
    for lane in approved.get("lanes", []):
        for f in lane.get("files", []):
            key = f.lower()
            if key in seen and seen[key] != lane["id"]:
                raise RuntimeError(
                    f"approved plan has overlapping file '{f}' in lanes "
                    f"{seen[key]} and {lane['id']} — refusing to execute")
            seen[key] = lane["id"]
    n_ok = len(approved.get("lanes", []))
    n_veto = len(approved.get("vetoed", []))
    return f"adversarial review: {n_ok} lane(s) approved, {n_veto} vetoed"
