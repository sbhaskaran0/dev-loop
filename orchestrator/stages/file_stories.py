"""file_stories — turn approved candidates into Linear issues.

Degrades without aborting: with --no-linear (or when the Linear session
fails) the would-be issues land in stories.pending.json and the run
continues; in a run that would execute, plan.py refuses to plan candidates
that never got story ids.
"""
from ..artifacts import ArtifactError, correction_note, read_json, write_json


def run(ctx) -> str:
    cands = read_json(ctx.run_dir / "candidates.json",
                      required_keys=("candidates",))
    candidates = cands.get("candidates", [])
    if not candidates:
        write_json(ctx.run_dir / "stories.json", {"stories": []})
        return "no candidates — nothing to file."
    if ctx.args.no_linear or ctx.args.dry_run:
        write_json(ctx.run_dir / "stories.pending.json",
                   {"pending": candidates,
                    "note": "Linear disabled this run — file these by hand "
                            "or re-run file_stories without --no-linear"})
        return (f"_Linear disabled — {len(candidates)} candidate(s) written "
                "to stories.pending.json._")
    prompt = ctx.template(
        "file_stories",
        run_dir=str(ctx.run_dir),
        linear_team=ctx.cfg.get("linear", {}).get("team", ""),
        loop_label=ctx.cfg.get("linear", {}).get("loop_label", "loop"),
        candidates_json=(ctx.run_dir / "candidates.json").read_text(
            encoding="utf-8"),
    )
    stories_path = ctx.run_dir / "stories.json"
    try:
        for attempt in (1, 2):
            ctx.spawn("file_stories", prompt)
            try:
                stories = read_json(stories_path, required_keys=("stories",))
                break
            except ArtifactError as e:
                if attempt == 2:
                    raise
                prompt += correction_note(e)
    except Exception as e:
        # Linear auth is the usual culprit — degrade, never abort the run.
        write_json(ctx.run_dir / "stories.pending.json",
                   {"pending": candidates, "error": str(e),
                    "note": "Linear write failed — re-auth via /mcp in the "
                            "target repo, then file these by hand"})
        return (f"**LINEAR WRITE FAILED** ({e}) — {len(candidates)} "
                "candidate(s) parked in stories.pending.json.")
    ids = [s.get("issue") for s in stories.get("stories", [])]
    return f"filed {len(ids)} Linear issue(s): {', '.join(filter(None, ids))}"
