"""integrate — merge completed lanes into the run branch (in its own
worktree), run the verification gates, do ONE doc-sync commit for the whole
run (deliberate deviation from the target's per-commit doc rule — parallel
lanes doing doc edits would conflict every run), then push + open the PR.
Merge conflicts drop the lane from the run branch; its branch is pushed for
manual pickup and its story goes back to In Progress at finalize.
"""
import subprocess

from .. import gitops
from ..artifacts import read_json, write_json


def _run_verification(ctx, integrate_dir) -> list[dict]:
    results = []
    venv_python = ctx.cfg["target"].get("venv_python", "python")
    for gate in ctx.cfg.get("verification", []):
        cmd = gate["cmd"].replace("{venv_python}", venv_python)
        cwd = integrate_dir / gate.get("cwd", ".")
        proc = subprocess.run(cmd, shell=True, cwd=str(cwd),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=1200)
        results.append({"name": gate["name"], "ok": proc.returncode == 0,
                        "tail": (proc.stdout + proc.stderr)[-800:]})
    return results


def run(ctx) -> str:
    lane_results = read_json(ctx.run_dir / "lane-results.json",
                             required_keys=("lanes",))
    done_lanes = [l for l in lane_results["lanes"] if l["status"] == "done"]
    if not done_lanes:
        write_json(ctx.run_dir / "integrate.json",
                   {"merged": [], "note": "no completed lanes"})
        return "no completed lanes — nothing to integrate."
    if ctx.args.dry_run:
        return f"_dry run: would merge {len(done_lanes)} lane(s)._"

    target = ctx.cfg["target"]
    run_branch = f"{target.get('branch_prefix', 'loop')}/{ctx.date}"
    integrate_dir = gitops.add_worktree(
        target["cwd"], ctx.date, "integrate", run_branch,
        target.get("base_ref", "origin/main"))

    merged, conflicted = [], []
    for lane in done_lanes:
        if gitops.merge_lane(integrate_dir, lane["branch"]):
            merged.append(lane)
        else:
            conflicted.append(lane)
            gitops.push_branch(target["cwd"], target.get("remote", "origin"),
                               lane["branch"])

    verification = _run_verification(ctx, integrate_dir) if merged else []
    gates_ok = all(v["ok"] for v in verification)

    if merged and gates_ok:
        # single doc-sync session for the whole run
        prompt = ctx.template(
            "integrate",
            worktree=str(integrate_dir),
            date=ctx.date,
            merged_lanes="\n".join(f"- {l['id']} ({l['branch']})"
                                   for l in merged),
        )
        try:
            ctx.spawn("integrate", prompt, cwd=str(integrate_dir))
        except Exception as e:
            verification.append({"name": "doc-sync", "ok": False,
                                 "tail": str(e)})

    pr_url = None
    if merged and gates_ok:
        gitops.push_branch(target["cwd"], target.get("remote", "origin"),
                           run_branch)
        body = ctx.run_dir / "pr-body.md"
        body.write_text(
            f"Autonomous dev-loop run **{ctx.date}**.\n\n"
            "## Lanes merged\n"
            + "\n".join(f"- `{l['branch']}`" for l in merged)
            + ("\n\n## Merge conflicts (branches pushed for manual pickup)\n"
               + "\n".join(f"- `{l['branch']}`" for l in conflicted)
               if conflicted else "")
            + "\n\n## Verification\n"
            + "\n".join(f"- {v['name']}: {'PASS' if v['ok'] else 'FAIL'}"
                        for v in verification)
            + "\n\nDoc-sync: one consolidated docs commit for the whole run "
              "(deliberate deviation from per-commit doc sync — see dev-loop "
              "README).\n\nRun log: `dev-loop/runs/" + ctx.date + "/log.md`\n"
            + "\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n",
            encoding="utf-8")
        try:
            pr_url = gitops.create_pr(
                target["cwd"], run_branch,
                target.get("pr_base", "main"),
                f"Daily loop {ctx.date}", body)
        except gitops.GitError as e:
            verification.append({"name": "gh-pr", "ok": False,
                                 "tail": str(e)})

    write_json(ctx.run_dir / "integrate.json", {
        "run_branch": run_branch,
        "merged": [l["id"] for l in merged],
        "conflicted": [l["id"] for l in conflicted],
        "verification": verification,
        "pr_url": pr_url,
    })
    # merged lanes' worktrees are disposable now; keep failed ones
    for lane in merged:
        gitops.remove_worktree(target["cwd"],
                               gitops.worktree_dir(ctx.date, lane["id"]),
                               force=True)
    parts = [f"merged {len(merged)}, conflicted {len(conflicted)}"]
    for v in verification:
        parts.append(f"{v['name']}: {'PASS' if v['ok'] else 'FAIL'}")
    if pr_url:
        parts.append(f"PR: {pr_url}")
    elif merged and not gates_ok:
        parts.append("verification FAILED — branch NOT pushed, no PR")
    return " | ".join(parts)
