"""Load and validate a project config (projects/<name>.yaml).

The config is the generalization boundary: every target-specific fact lives
here or in the project's adapter module. The orchestrator itself knows
nothing about any particular target repo.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

_REQUIRED = ("project", "target", "adapter", "policy", "stages")


class ConfigError(Exception):
    pass


def load(project: str) -> dict:
    path = ROOT / "projects" / f"{project}.yaml"
    if not path.exists():
        raise ConfigError(f"no such project config: {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in _REQUIRED:
        if key not in cfg:
            raise ConfigError(f"{path.name}: missing required key '{key}'")
    target = cfg["target"]
    if "cwd" not in target:
        raise ConfigError(f"{path.name}: target.cwd is required")
    # Never normalize target.cwd casing — MCP servers in ~/.claude.json are
    # keyed by the exact path string; a case change silently drops them.
    if not Path(target["cwd"]).is_dir():
        raise ConfigError(f"target.cwd does not exist: {target['cwd']}")
    cfg.setdefault("verification", [])
    cfg.setdefault("context_docs", [])
    cfg.setdefault("notify", {})
    pol = cfg["policy"]
    pol.setdefault("budget_output_tokens", 500_000)
    pol.setdefault("budget_usd_ceiling", 40.0)
    pol.setdefault("reserve_fraction", 0.10)
    pol.setdefault("max_lanes", 4)
    pol.setdefault("max_concurrent_lanes", 2)
    pol.setdefault("spawn_stagger_seconds", 20)
    pol.setdefault("lane_max_turns", 80)
    pol.setdefault("refresh_wait_min", 10)
    pol.setdefault("models", {})
    pol.setdefault("timeouts_min", {})
    return cfg


def model_for(cfg: dict, stage: str, default: str = "opus") -> str:
    return cfg["policy"]["models"].get(stage, default)


def timeout_for(cfg: dict, stage: str, default: int = 15) -> int:
    return int(cfg["policy"]["timeouts_min"].get(stage, default))
