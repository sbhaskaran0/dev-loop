"""The loop's spine: stage sequencing, lock file, state.json, and a
crash-safe run log. Every stage receives the Run context; artifacts flow
through runs/<date>/ files, never through Python object state, so a re-run
with --date can resume from whatever completed.
"""
import json
import os
import string
import sys
import traceback
from datetime import date as _date
from datetime import datetime
from importlib import import_module
from pathlib import Path

from . import claude_proc, config as config_mod
from .budget import Budget
from .config import ROOT

# A failure in one of these aborts the run (jump straight to finalize-lite);
# other stages degrade or skip and the run continues.
CRITICAL_STAGES = {"collect", "evaluate", "plan", "review"}

LOCK_STALE_S = 6 * 3600


class Run:
    def __init__(self, cfg: dict, args):
        self.cfg = cfg
        self.args = args
        self.date = args.date or _date.today().isoformat()
        self.run_dir = ROOT / "runs" / self.date
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.run_dir / "state.json"
        self.log_path = self.run_dir / "log.md"
        self.state = self._load_state()
        self.budget = Budget(cfg["policy"], override_tokens=args.budget)
        for e in self.state.get("usage", []):
            self.budget.record(e)

    # -- state ------------------------------------------------------------ #
    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"date": self.date, "project": self.cfg["project"],
                "status": "in_progress", "stages_done": [], "usage": [],
                "lanes": {}, "failures": []}

    def save_state(self) -> None:
        self.state["usage"] = self.budget.entries
        self.state_path.write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")

    # -- logging ----------------------------------------------------------- #
    def log(self, text: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n\n")

    def set_status(self, status: str) -> None:
        self.state["status"] = status
        self.save_state()

    # -- prompts + spawns --------------------------------------------------- #
    def template(self, name: str, **vars) -> str:
        tpl = (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
        return string.Template(tpl).safe_substitute(**vars)

    def spawn(self, label: str, prompt: str, *, cwd: str | None = None,
              stage: str | None = None, model: str | None = None,
              timeout_min: int | None = None,
              max_turns: int | None = None) -> dict:
        """Run one claude -p session, recording usage into the budget ledger
        and saving the filled prompt + raw stdout under the run dir."""
        stage = stage or label
        model = model or config_mod.model_for(self.cfg, stage)
        timeout_min = timeout_min or config_mod.timeout_for(self.cfg, stage)
        cwd = cwd or self.cfg["target"]["cwd"]
        safe = label.replace("/", "-").replace(":", "-")
        (self.run_dir / f"{safe}.prompt.txt").write_text(prompt,
                                                         encoding="utf-8")
        if self.args.dry_run:
            return {"result": "DONE", "is_error": False, "usage": {},
                    "_label": label, "_dry_run": True}
        result = claude_proc.run_claude(
            prompt, cwd=cwd, model=model, timeout_min=timeout_min,
            max_turns=max_turns, label=label,
            stagger_s=self.cfg["policy"]["spawn_stagger_seconds"],
            raw_path=self.run_dir / f"{safe}.raw-stdout.txt")
        self.budget.record(claude_proc.usage_entry(result, label))
        self.save_state()
        return result

    def target_path(self, rel: str) -> Path:
        return Path(self.cfg["target"]["cwd"]) / rel


# -------------------------------------------------------------------------- #
def _acquire_lock() -> Path | None:
    lock = ROOT / "runs" / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    payload = f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, payload.encode())
        os.close(fd)
        return lock
    except FileExistsError:
        age = None
        try:
            age = (datetime.now()
                   - datetime.fromtimestamp(lock.stat().st_mtime))
        except OSError:
            pass
        if age is not None and age.total_seconds() > LOCK_STALE_S:
            print(f"stealing stale lock (age {age})")
            lock.unlink(missing_ok=True)
            return _acquire_lock()
        print("another run holds runs/.lock -- refusing to overlap")
        return None


def stage_list(cfg: dict, args) -> list[str]:
    stages = list(cfg["stages"])
    if args.stages:
        wanted = [s.strip() for s in args.stages.split(",")]
        stages = [s for s in stages if s in wanted]
    if args.no_execute:
        stages = [s for s in stages
                  if s not in ("execute", "integrate")]
    return stages


def run(cfg: dict, args) -> int:
    lock = _acquire_lock()
    if lock is None:
        return 2
    ctx = Run(cfg, args)
    stages = stage_list(cfg, args)
    started = datetime.now().isoformat(timespec="seconds")
    if not ctx.log_path.exists():
        ctx.log(f"# Dev-loop run -- {ctx.date} ({cfg['project']})\n\n"
                f"Status: **in progress** | started {started} | "
                f"budget {ctx.budget.limit_tokens:,} output tokens"
                + (" | DRY RUN" if args.dry_run else "")
                + (" | no-linear" if args.no_linear else ""))
    exit_code = 0
    try:
        # finalize is excluded from the main loop: it always runs at the end,
        # after the final status is known — even when a critical stage failed.
        for name in [s for s in stages if s != "finalize"]:
            if name in ctx.state["stages_done"]:
                ctx.log(f"## {name}\n\n_Already done (resumed run) -- "
                        "skipped._")
                continue
            print(f"[{datetime.now():%H:%M:%S}] stage: {name}")
            mod = import_module(f"orchestrator.stages.{name}")
            try:
                summary = mod.run(ctx)
                ctx.state["stages_done"].append(name)
                ctx.save_state()
                ctx.log(f"## {name}\n\n{summary or '_ok_'}")
            except Exception as e:
                tb = traceback.format_exc()
                ctx.state["failures"].append({"stage": name, "error": str(e)})
                ctx.save_state()
                ctx.log(f"## {name} -- FAILED\n\n```\n{tb[-1800:]}\n```")
                print(f"stage {name} failed: {e}", file=sys.stderr)
                if name in CRITICAL_STAGES:
                    ctx.set_status("failed")
                    exit_code = 1
                    break
            if ctx.budget.exhausted() and name not in ("finalize",):
                ctx.log("## budget\n\n**Budget exhausted** -- skipping to "
                        "finalize.")
                break
        if ctx.state["status"] == "in_progress":
            ctx.set_status("failed" if ctx.state["failures"] else "ok")
        if "finalize" in stages and "finalize" not in ctx.state["stages_done"]:
            # finalize always runs, even after a critical failure
            try:
                mod = import_module("orchestrator.stages.finalize")
                summary = mod.run(ctx)
                ctx.state["stages_done"].append("finalize")
                ctx.save_state()
                ctx.log(f"## finalize\n\n{summary or '_ok_'}")
            except Exception:
                ctx.log("## finalize -- FAILED\n\n```\n"
                        f"{traceback.format_exc()[-1800:]}\n```")
                exit_code = 1
    except Exception:
        ctx.set_status("crashed")
        ctx.log("## CRASH\n\n```\n" + traceback.format_exc()[-2000:] + "\n```")
        exit_code = 1
    finally:
        b = ctx.budget
        ctx.log(f"---\n\nFinal status: **{ctx.state['status']}** | "
                f"spent {b.spent_tokens:,} output tokens / "
                f"${b.spent_usd:.2f} | finished "
                f"{datetime.now().isoformat(timespec='seconds')}")
        ctx.save_state()
        lock.unlink(missing_ok=True)
    return exit_code
