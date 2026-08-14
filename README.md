# dev-loop

An autonomous daily development loop that improves a target repository:
every morning it collects the app's health metrics, evaluates them against
your goals, files Linear stories for pareto-optimal enhancements, and — once
you enable execution — plans lanes, passes an adversarial code-health review,
implements them with parallel `claude -p` agents in isolated git worktrees,
and opens a PR. **Nothing lands on main unattended**; you merge.

Generalized by design: the orchestrator knows nothing about any particular
project. A target = one `projects/<name>.yaml` (paths, Linear team, budgets,
verification gates, stage list) + one `adapters/<name>.py` (metric readers).
First target: [job-applier](https://github.com/sbhaskaran0/job-applier).

```
collect ──▶ evaluate ──▶ file_stories ─▶ plan ─▶ review ─▶ execute ─▶ integrate ─▶ finalize
(python)    (opus,        (sonnet,        (opus)  (opus,     (lanes ×    (merge,      (PR/Linear
 metrics     scorecard +    Linear                  adversar-  worktrees,   verify,      relay +
 .json)      candidates)    issues)                 ial gate)  tiered)      doc-sync)    email)
     M1 = [collect, evaluate, file_stories, finalize]   M2 adds the rest
```

## How it works

- **Stages are fresh `claude -p` processes** (stdin prompt, `--output-format
  json`), never a long-lived SDK session. Each stage's prompt tells the agent
  to WRITE its output to an artifact file under `runs/<date>/`; the
  orchestrator validates the file and retries once with a correction note.
  Spawns are serialized + staggered (concurrent CLI spawns crash on ARM64
  Windows); running lanes overlap up to `max_concurrent_lanes`.
- **Budget**: cumulative output tokens (default 500k) with a USD ceiling
  backstop, 10% reserved for integrate/finalize; lanes are admitted against
  estimates and overflow is deferred to Linear (`loop-deferred` label) for
  the next morning.
- **Worktrees**: the user's checkout is never touched. Lanes branch off
  `origin/main` into `worktrees/<date>/<lane>/`; merge conflicts drop the
  lane from the run branch (its branch is pushed for manual pickup).
- **Linear-touching stages** (evaluate, file_stories, plan, finalize) run
  with cwd = the real target repo — the Linear MCP in `~/.claude.json` is
  keyed to that exact path. Executors run in worktrees with no Linear.
- **Crash-safe**: `runs/<date>/log.md` gets a section per stage inside a
  try/finally; `state.json` is rewritten on every change; `runs/.lock`
  prevents overlapping runs (stale after 6h). Linear/email failures degrade
  (pending files, log banners) — they never abort a run.

## Setup

```
pip install -r requirements.txt          # pyyaml only
# needs on PATH: python, git, gh (authed), claude (or Cursor/VS Code/Desktop install)
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1   # daily 09:30
```

Edit `goals.md` — the evaluator weighs every candidate against it.

## Running manually

```
python -m orchestrator --project job-applier              # full configured run
python -m orchestrator --dry-run                          # no spawns; fixtures end-to-end
python -m orchestrator --stages collect                   # just the metrics snapshot
python -m orchestrator --stages collect,evaluate --no-linear
python -m orchestrator --no-execute                       # M2 config: stop after review
python -m orchestrator --budget 100000                    # tighter cap
python -m orchestrator --date 2026-08-15                  # resume/redo a run dir
```

Artifacts land in `runs/<date>/`: `metrics.json`, `evaluation.md`,
`candidates.json`, `stories.json` (or `stories.pending.json` when Linear is
unavailable), `delegation*.json`, `lanes/<id>/`, `integrate.json`, `log.md`.
The `runs/` history is tracked in git — it is the loop's own memory (the
evaluator reads recent logs to avoid re-proposing).

## Enabling execution (M2)

Run M1 (evaluation-only) for a few mornings and tune `prompts/evaluate.md`
until the stories it files are ones you'd write. Then switch the `stages:`
list in `projects/job-applier.yaml` to the full pipeline, and start with
`--budget 100000` + `max_lanes: 1`. Recommended: enable branch protection on
the target's main so PRs are the only path in.

## Safety model

Unattended `bypassPermissions` agents are jailed by construction: fresh
worktrees, prompts that hard-forbid the real checkout / profiles / data /
dependency files / docs, no installs, review-gate file-overlap enforcement in
code, PR-only delivery, and Linear stages that are read-only in the repo by
prompt. Layered runaway breakers: per-spawn `--max-turns` + wall-clock
timeouts + admission control + token budget + USD ceiling.

## Adding a target project

1. `projects/<name>.yaml` — copy job-applier.yaml, adjust target paths,
   Linear team, verification commands, stage list.
2. `adapters/<name>.py` — expose `collect(cfg, run_dir) -> dict` returning
   your metrics (degrade each to `{"instrumented": false, "note": ...}`).
3. `goals.md` is shared per-repo today; per-project goals can move into the
   project yaml when a second target actually exists.

## Roadmap

- **PM agent** — a `pm_review` stage before `review` judging the plan against
  goals/north-star/roadmap (the `stages:` list is the plugin point).
- Merge-conflict resolution session; per-project goals; response-rate metric
  once the target tracks it.
