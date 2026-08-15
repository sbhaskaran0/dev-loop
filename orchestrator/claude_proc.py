"""Spawn `claude -p` headless sessions and parse their JSON result.

Every Claude stage of the loop is a fresh CLI process: fire-and-forget, no
SDK, no shared state. Two hard-won constraints from the target machine
(Windows ARM64) are enforced here:

- Concurrent CLI *spawns* crash with access violations — a global lock
  serializes process starts, with a stagger delay; already-running
  processes may overlap freely.
- A wedged process must be killed by process TREE (taskkill /T /F), or the
  CLI's children (MCP servers, browsers) leak and hold locks.

The prompt goes in via stdin (never argv — Windows 32K cmdline limit). The
result comes out as one JSON object on stdout (`--output-format json`) with
`result`, `is_error`, `usage`, `total_cost_usd`, `num_turns`.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

_spawn_lock = threading.Lock()
_last_spawn = [0.0]


class ClaudeError(Exception):
    pass


def find_cli() -> str | None:
    """Prefer a native CLI over any bundled x64 binary (ARM64 flakiness).
    Mirrors the target repo's server/chat.py resolution order."""
    if cli := shutil.which("claude"):
        return cli
    home = Path.home()
    candidates: list[str] = []
    for pattern in (
        home / ".cursor/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe",
        home / ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe",
        home / "AppData/Local/Packages/Claude_*/LocalCache/Roaming/Claude/claude-code/*/claude.exe",
    ):
        candidates += glob.glob(str(pattern))
    return sorted(candidates)[-1] if candidates else None


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True)


def _spawn(cmd: list[str], prompt: str, cwd: str, timeout_s: int,
           stagger_s: float) -> tuple[int, str, str]:
    """One serialized spawn + full wait. Returns (returncode, stdout, stderr)."""
    with _spawn_lock:
        wait = stagger_s - (time.monotonic() - _last_spawn[0])
        if wait > 0:
            time.sleep(wait)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        _last_spawn[0] = time.monotonic()
    # The lock covers only the spawn; the wait happens concurrently.
    try:
        out, err = proc.communicate(input=prompt, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        raise ClaudeError(f"timed out after {timeout_s}s (process tree killed)")
    return proc.returncode, out or "", err or ""


def _parse_result(stdout: str) -> dict:
    """`--output-format json` emits a single JSON object; be tolerant of any
    stray non-JSON lines around it by scanning from the last line back."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "result" in obj or "is_error" in obj or "usage" in obj:
                return obj
    # whole-output fallback (pretty-printed JSON)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        raise ClaudeError("no JSON result object found in stdout")


def run_claude(prompt: str, *, cwd: str, model: str, timeout_min: int,
               max_turns: int | None = None, label: str = "claude",
               stagger_s: float = 20.0, raw_path: Path | None = None,
               mcp_config: str | None = None) -> dict:
    """Run one headless claude -p session. Returns the parsed result dict,
    augmented with `_label`. Retries once (5s later) on spawn failure,
    nonzero exit, or unparseable output — never on timeout (the work may be
    half-done; the caller decides)."""
    cli = find_cli()
    if not cli:
        raise ClaudeError("no claude CLI found (PATH, Cursor/VS Code "
                          "extension, or Claude Desktop)")
    cmd = [cli, "-p", "--output-format", "json",
           "--permission-mode", "bypassPermissions",
           "--setting-sources", "user,project",
           "--model", model]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]
    if mcp_config:
        # Interactively-connected MCP servers (e.g. Linear via ~/.claude.json)
        # do NOT load in headless -p sessions — pass them explicitly; stored
        # OAuth credentials are reused. Lane executors deliberately omit this.
        cmd += ["--mcp-config", mcp_config]

    last_err = None
    for attempt in (1, 2):
        try:
            rc, out, err = _spawn(cmd, prompt, cwd, timeout_min * 60, stagger_s)
        except ClaudeError:
            raise  # timeout — no retry
        if raw_path:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(
                f"# exit={rc} attempt={attempt}\n--- stdout ---\n{out}\n"
                f"--- stderr ---\n{err}\n", encoding="utf-8")
        try:
            if rc != 0:
                raise ClaudeError(f"exit {rc}: {err.strip()[:400]}")
            result = _parse_result(out)
            result["_label"] = label
            return result
        except ClaudeError as e:
            last_err = e
            if attempt == 1:
                time.sleep(5)  # transient spawn crash — one retry
    raise ClaudeError(f"{label} failed twice: {last_err}")


def usage_entry(result: dict, label: str) -> dict:
    """Normalize a claude -p result into a budget-ledger entry."""
    u = result.get("usage") or {}
    return {
        "label": label,
        "output_tokens": u.get("output_tokens", 0) or 0,
        "input_tokens": u.get("input_tokens", 0) or 0,
        "cost_usd": result.get("total_cost_usd") or 0.0,
        "num_turns": result.get("num_turns"),
        "is_error": bool(result.get("is_error")),
    }
