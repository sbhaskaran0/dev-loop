"""execute — run approved lanes as parallel claude -p sessions, each jailed
in its own git worktree of the target repo. Spawns are budget-gated and
staggered (the ARM64 spawn crash); running lanes may overlap up to
max_concurrent_lanes. Failed/timed-out lanes keep their worktrees for
inspection and are never retried (they may hold half-committed work).
"""
import subprocess
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .. import claude_proc, gitops
from ..artifacts import read_json, write_json
from ..config import model_for, timeout_for


def _lane_prompt(ctx, lane: dict, worktree) -> str:
    return ctx.template(
        "execute_lane",
        lane_id=lane["id"],
        worktree=str(worktree),
        branch=lane["branch"],
        story_text=lane.get("story", ""),
        files=", ".join(lane.get("files", [])) or "(planner set no file list)",
        result_path=str(ctx.run_dir / "lanes" / lane["id"] / "result.json"),
        target_cwd=ctx.cfg["target"]["cwd"],
    )


def _run_lane(ctx, lane: dict, worktree) -> dict:
    lane_dir = ctx.run_dir / "lanes" / lane["id"]
    lane_dir.mkdir(parents=True, exist_ok=True)
    tiers = ctx.cfg["policy"]["models"].get(
        "lane_tiers", {"high": "opus", "medium": "sonnet", "low": "haiku"})
    model = tiers.get(lane.get("tier", "medium"), "sonnet")
    prompt = _lane_prompt(ctx, lane, worktree)
    (lane_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    try:
        result = claude_proc.run_claude(
            prompt, cwd=str(worktree), model=model,
            timeout_min=timeout_for(ctx.cfg, "lane", 45),
            max_turns=ctx.cfg["policy"]["lane_max_turns"],
            label=f"lane:{lane['id']}",
            stagger_s=ctx.cfg["policy"]["spawn_stagger_seconds"],
            raw_path=lane_dir / "raw-stdout.txt")
        ctx.budget.record(claude_proc.usage_entry(result,
                                                  f"lane:{lane['id']}"))
        ctx.save_state()
        status = "failed" if result.get("is_error") else "done"
    except claude_proc.ClaudeError as e:
        (lane_dir / "error.txt").write_text(str(e), encoding="utf-8")
        status = "failed"
    # A lane is only 'done' if it actually committed something on its branch.
    if status == "done":
        head = subprocess.run(
            ["git", "-C", str(worktree), "log", "--oneline", "-1",
             f"{ctx.cfg['target']['base_ref']}..HEAD"],
            capture_output=True, text=True)
        if not (head.stdout or "").strip():
            status = "no_commits"
    return {"id": lane["id"], "status": status, "branch": lane["branch"],
            "worktree": str(worktree)}


def run(ctx) -> str:
    approved = read_json(ctx.run_dir / "delegation.approved.json",
                         required_keys=("lanes",))
    lanes = approved.get("lanes", [])
    if not lanes:
        write_json(ctx.run_dir / "lane-results.json", {"lanes": []})
        return "no approved lanes — nothing to execute."
    if ctx.args.dry_run:
        return f"_dry run: would execute {len(lanes)} lane(s)._"
    target = ctx.cfg["target"]
    gitops.fetch_and_prune(target["cwd"], target.get("remote", "origin"))
    gitops.cleanup_old_worktrees(target["cwd"])
    prefix = target.get("branch_prefix", "loop")

    outcomes, skipped = [], []
    max_conc = ctx.cfg["policy"]["max_concurrent_lanes"]
    running: dict = {}
    with ThreadPoolExecutor(max_workers=max_conc) as pool:
        queue = list(lanes)
        while queue or running:
            # admit while there is room, budget, and a runnable lane
            while queue and len(running) < max_conc:
                lane = queue[0]
                est = int(lane.get("est_output_tokens", 50_000))
                running_est = sum(int(l.get("est_output_tokens", 50_000))
                                  for l in running.values())
                if not ctx.budget.can_admit(est, running_est):
                    skipped.append({"id": lane["id"], "reason": "budget"})
                    queue.pop(0)
                    continue
                queue.pop(0)
                lane["branch"] = f"{prefix}/{ctx.date}/{lane['id']}"
                worktree = gitops.add_worktree(
                    target["cwd"], ctx.date, lane["id"], lane["branch"],
                    target.get("base_ref", "origin/main"))
                fut = pool.submit(_run_lane, ctx, lane, worktree)
                running[fut] = lane
            if not running:
                continue
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                lane = running.pop(fut)
                try:
                    outcomes.append(fut.result())
                except Exception as e:
                    outcomes.append({"id": lane["id"], "status": "failed",
                                     "branch": lane.get("branch", ""),
                                     "error": str(e)})
    ctx.state["lanes"] = {o["id"]: o for o in outcomes}
    ctx.save_state()
    write_json(ctx.run_dir / "lane-results.json",
               {"lanes": outcomes, "deferred_at_execute": skipped})
    done_n = sum(1 for o in outcomes if o["status"] == "done")
    return (f"{done_n}/{len(outcomes)} lane(s) completed with commits; "
            f"{len(skipped)} deferred on budget")
