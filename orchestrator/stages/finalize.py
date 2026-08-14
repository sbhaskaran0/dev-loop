"""finalize — always runs, even after failures. Writes the log epilogue and
(best-effort) sends the summary email via a small Claude session with the
Gmail connector. In M2 runs it additionally pushes the run branch, opens
the PR, and relays lane outcomes to Linear — those pieces are driven by
integrate.json when it exists.
"""
import json


def _email_body(ctx) -> str:
    log = (ctx.run_dir / "log.md").read_text(encoding="utf-8") \
        if (ctx.run_dir / "log.md").exists() else "(no log)"
    return log[:6000]


def run(ctx) -> str:
    notes = []
    integrate = ctx.run_dir / "integrate.json"
    pr_url = None
    if integrate.exists():
        info = json.loads(integrate.read_text(encoding="utf-8"))
        pr_url = info.get("pr_url")
        if pr_url:
            notes.append(f"PR: {pr_url}")
    email_to = ctx.cfg.get("notify", {}).get("email")
    if email_to and not ctx.args.dry_run:
        status = ctx.state.get("status", "unknown")
        prompt = ctx.template(
            "finalize",
            email_to=email_to,
            project=ctx.cfg["project"],
            date=ctx.date,
            status=status,
            pr_line=f"PR opened: {pr_url}" if pr_url else "No PR this run.",
            run_log=_email_body(ctx),
            no_linear=("Linear is DISABLED this run — do not touch Linear."
                       if ctx.args.no_linear else ""),
            run_dir=str(ctx.run_dir),
        )
        try:
            result = ctx.spawn("finalize", prompt)
            ok = not result.get("is_error")
            notes.append(f"summary email to {email_to}: "
                         f"{'sent' if ok else 'FAILED (see raw stdout)'}")
        except Exception as e:  # email must never fail the run
            notes.append(f"summary email FAILED: {e}")
    elif email_to:
        notes.append(f"dry run — email to {email_to} skipped")
    return "\n".join(f"- {n}" for n in notes) or "- nothing to finalize"
