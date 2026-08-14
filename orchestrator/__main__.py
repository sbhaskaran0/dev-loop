"""CLI entrypoint: python -m orchestrator --project job-applier [...]"""
import argparse
import sys

from . import config as config_mod
from . import runner


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="orchestrator",
        description="Daily autonomous dev loop over a target repo.")
    ap.add_argument("--project", default="job-applier",
                    help="projects/<name>.yaml to run (default: job-applier)")
    ap.add_argument("--date", default=None,
                    help="run-dir date (YYYY-MM-DD); reuse to resume a run")
    ap.add_argument("--stages", default=None,
                    help="comma-separated subset of the config's stage list")
    ap.add_argument("--dry-run", action="store_true",
                    help="no claude spawns; stages use fixtures/ samples")
    ap.add_argument("--no-linear", action="store_true",
                    help="never write to Linear (stories -> pending file)")
    ap.add_argument("--no-execute", action="store_true",
                    help="stop after review (skip execute/integrate)")
    ap.add_argument("--budget", type=int, default=None,
                    help="override output-token budget for this run")
    args = ap.parse_args()

    try:
        cfg = config_mod.load(args.project)
    except config_mod.ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    return runner.run(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
