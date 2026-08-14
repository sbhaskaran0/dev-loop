"""Git operations against the TARGET repo — always `git -C <target>` with
absolute paths; the loop never touches the user's working tree (worktrees
share .git metadata only). Lane worktrees live under the dev-loop repo's
gitignored worktrees/ dir for easy cleanup.
"""
import shutil
import subprocess
import time
from pathlib import Path

from .config import ROOT


class GitError(Exception):
    pass


def _git(target: str, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", target, *args],
                          capture_output=True, text=True, encoding="utf-8")
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()[:500]}")
    return (proc.stdout or "").strip()


def fetch_and_prune(target: str, remote: str) -> None:
    _git(target, "fetch", remote)
    _git(target, "worktree", "prune")


def worktree_dir(date: str, name: str) -> Path:
    return ROOT / "worktrees" / date / name


def add_worktree(target: str, date: str, name: str, branch: str,
                 base_ref: str) -> Path:
    path = worktree_dir(date, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        # stale leftover from a re-run of the same date — remove and recreate
        remove_worktree(target, path, force=True)
    # -B: re-runs of the same date reuse the branch name
    _git(target, "worktree", "add", str(path), "-B", branch, base_ref)
    return path


def remove_worktree(target: str, path: Path, force: bool = False) -> None:
    args = ["worktree", "remove", str(path)]
    if force:
        args.append("--force")
    try:
        _git(target, *args)
    except GitError:
        shutil.rmtree(path, ignore_errors=True)
        _git(target, "worktree", "prune", check=False)


def merge_lane(integrate_dir: Path, lane_branch: str) -> bool:
    """Merge a lane branch into the run branch (cwd = integrate worktree).
    Returns False (after aborting) on conflict — the caller drops the lane."""
    proc = subprocess.run(
        ["git", "-C", str(integrate_dir), "merge", "--no-ff", lane_branch,
         "-m", f"merge {lane_branch}"],
        capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        subprocess.run(["git", "-C", str(integrate_dir), "merge", "--abort"],
                       capture_output=True)
        return False
    return True


def push_branch(target: str, remote: str, branch: str) -> None:
    _git(target, "push", "-u", remote, branch)


def create_pr(target: str, branch: str, base: str, title: str,
              body_file: Path) -> str:
    proc = subprocess.run(
        ["gh", "pr", "create", "--base", base, "--head", branch,
         "--title", title, "--body-file", str(body_file)],
        cwd=target, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise GitError(f"gh pr create: {proc.stderr.strip()[:500]}")
    return (proc.stdout or "").strip().splitlines()[-1]


def cleanup_old_worktrees(target: str, keep_days: int = 7) -> None:
    base = ROOT / "worktrees"
    if not base.exists():
        return
    cutoff = time.time() - keep_days * 86400
    for d in base.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            for wt in d.iterdir():
                remove_worktree(target, wt, force=True)
            shutil.rmtree(d, ignore_errors=True)
    _git(target, "worktree", "prune", check=False)
