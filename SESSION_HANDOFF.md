# Session handoff — dev-loop

Paste into a fresh Claude Code session to restore context. Durable state only;
per-run narrative lives in `runs/<date>/log.md` (tracked) + `git log`.
Last updated 2026-08-14.

## What this project is

An **autonomous daily development loop** that improves a target repository —
first target: [job-applier](https://github.com/sbhaskaran0/job-applier) at
`c:/Users/siddh/Job Applier`. Every morning at **09:30** (Task Scheduler task
"DevLoop Daily", after the target's 09:00 watchlist refresh) it: collects the
app's health metrics → evaluates them against `goals.md` + open Linear stories
+ the target's de-scope list (opus) → files pareto-optimal enhancement stories
in Linear → *(M2, currently disabled: plans lanes → adversarial code-health
review → parallel worktree executors → merge/verify → PR)* → finalizes (Linear
relay + summary email to **siddharth99.ram@gmail.com** — never
bjagadeesan@gmail.com). **Nothing lands on the target's main unattended**; the
human merges the PR. Full design rationale: `docs/design-plan.md`.

Built 2026-08-14 in one session (Claude Fable 5). Private GitHub:
`sbhaskaran0/dev-loop`.

## Architecture / key files

- **`orchestrator/runner.py`** — the spine: stage sequencing, `runs/.lock`
  (stale-steal after 6h), `state.json` rewritten on every change, crash-safe
  `log.md` (header at start, section per stage, try/finally epilogue).
  Critical stages (collect/evaluate/plan/review) abort → finalize-lite;
  everything else degrades. `finalize` is excluded from the main loop and
  always runs last, after final status is known. Re-running with `--date`
  resumes: completed stages are skipped via `stages_done`.
- **`orchestrator/claude_proc.py`** — every Claude stage is a fresh
  `claude -p --output-format json --permission-mode bypassPermissions
  --setting-sources user,project` process, prompt via **stdin** (never argv).
  Global spawn lock + stagger (concurrent CLI *spawns* crash on this ARM64
  machine; running processes may overlap), one retry after 5s on spawn/parse
  failure, **no retry on timeout** (work may be half-done), `taskkill /T /F`
  on the process tree. `find_cli()` prefers PATH → Cursor/VS Code extension →
  Claude Desktop managed CLI (currently resolves to Claude Desktop's
  `claude-code\2.1.229\claude.exe`).
- **`orchestrator/stages/*.py`** — one module per stage, `run(ctx)` contract.
  Agents never return structured data in chat text: each prompt names an
  absolute **artifact path** the agent must write; the orchestrator validates
  and retries once with a correction note (`artifacts.py`).
- **`orchestrator/budget.py`** — ledger from each result's `usage` /
  `total_cost_usd`: 500k output tokens primary + $40 USD ceiling backstop,
  10% reserved for integrate/finalize, lane admission against estimates.
- **`orchestrator/gitops.py`** — M2: lanes branch `loop/<date>/<lane>` off
  `origin/main` into `worktrees/<date>/<lane>` (gitignored; the user's
  checkout is NEVER touched). Merge conflict → lane dropped from run branch,
  its branch pushed for manual pickup. `review.py` enforces lane file-set
  disjointness **in code** (can't be waived by the reviewer agent).
- **`adapters/job_applier.py`** — target-specific metric readers, read-only
  (sqlite opened `mode=ro`; the 09:00 refresh may still be writing). Every
  metric degrades to `{"instrumented": false, "note": ...}`. Reads:
  `refresh_runs` yield (schema v3 cols), `applications.json` +
  prep-file attempted-proxy (weak — JOB-103 replaces it),
  `data/bug-reports.jsonl`, profile `token_usage.jsonl` (Stop-hook records
  win; `source: webchat` records only fill uncovered session_ids).
- **`projects/job-applier.yaml`** — the generalization boundary: target paths
  (cwd casing is load-bearing, see gotchas), Linear team/labels, budgets,
  models per stage (+ `lane_tiers`), timeouts, verification gates, `stages:`
  list (**the plugin point** — M1 list active; the M2 full list is in a
  comment; a future PM agent inserts `pm_review` before `review`),
  `mcp_config` (see gotchas).
- **`prompts/*.md`** — `string.Template` ($vars; prompts contain JSON braces
  so no str.format). These are the loop's actual intelligence — tune
  `evaluate.md` first. All prompts hard-forbid: touching the real checkout,
  profiles/, data/ writes, dependency files, docs (lanes), and instruct
  "never pause to ask" (unattended).
- **`goals.md`** — user-owned; the evaluator reads it verbatim. G1 response
  rate (w5) · G2 cheap to run (w3) · G3 trust before autonomy (w4).
- **`runs/<date>/`** — tracked in git; the loop's own memory (the evaluator
  reads the last 7 run logs to avoid re-proposing). Raw stdout transcripts +
  scheduler.log are gitignored.

## Current state (2026-08-14, end of build session)

- **M1 is live and verified end-to-end.** Dry run green; real collect green
  (4/4 metrics instrumented); live opus evaluation over real metrics produced
  a genuinely sharp scorecard (**2.7/5 weighted** — see
  `runs/2026-08-14/evaluation.md`); summary email delivered; scheduled-task
  path proven via `Start-ScheduledTask` (exit 0, cp1252 console OK, lock
  cleaned). Total verification cost ~$2.50 + ~$0.26 refile.
- **First real filing:** JOB-107 (application outcome tracking), JOB-108
  (persist baseline drop-off reasons — motivated by 144 title-matched roles
  at Brex/Databricks/Anthropic/… dropping to 0 qualifying for discarded
  reasons), JOB-109 (bug-report close path); JOB-103 correctly **reused**,
  not duplicated. `stories.attempt1.json` preserves the pre-mcp-config
  failed attempt for comparison.
- The evaluation also caught a real defect outside itself: an uncommitted
  `updated_at` edit in the target's `token_report.py` that its own cost
  metric depended on — committed to PR #7 the same evening.
- **Target-side state:** job-applier PR #7 (profile-system M1 + UI + chat
  resilience + JOB-102 instrumentation) is open, **merge left to the user**;
  the live webapp needs a restart post-merge for `/api/bug-report` (JOB-59
  gotcha). Instrumentation gaps tracked as JOB-103..106.

## Open items / next steps

1. **Let M1 run a few mornings** (next fire: tomorrow 09:30) and tune
   `prompts/evaluate.md` until the stories are consistently ones the user
   would write. Watch for re-proposals — the recent-logs guard is prompt-only.
2. **Enable M2** when trusted: flip `stages:` in `projects/job-applier.yaml`
   to the full list; first run with `--budget 100000` and `max_lanes: 1`.
   Recommend branch protection on the target's `main` first. JOB-105
   (pytest+CI) materially strengthens the verification gates before this.
3. **PM agent** (user roadmap): add `orchestrator/stages/pm_review.py` +
   `prompts/pm_review.md` judging the plan against goals/north-star/roadmap;
   insert `pm_review` before `review` in the stage list. No other wiring.
4. Second `projects/*.yaml` to prove generalization; per-project goals files
   when that happens. Merge-conflict resolution session (M3).
5. Bug-report lifecycle: once target JOB-109 lands, teach the evaluator to
   close triaged reports (today it can only read them).

## Gotchas / environment

- **Windows 11 ARM64.** Registered tasks via PowerShell cmdlets, never
  `schtasks` (quoting bug + AC-only default). Scheduled console is cp1252 —
  `run.cmd` sets `PYTHONIOENCODING=utf-8`; keep orchestrator prints ASCII.
- **`--mcp-config` is required for Linear.** Interactively-connected MCP
  servers in `~/.claude.json` do NOT load in headless `claude -p` sessions —
  the first scheduled run filed nothing because of this. The project yaml's
  `mcp_config` is passed to every orchestrator-level stage; **lane executors
  deliberately never get it.** Stored OAuth is reused; if Linear auth
  expires, stages degrade to `stories.pending.json` and the log says re-auth
  via `/mcp` in the target repo.
- **`target.cwd` casing is load-bearing** (`c:/Users/siddh/Job Applier`,
  lowercase drive): `~/.claude.json` MCP project keys match the exact string;
  never normalize it.
- **Git Bash vs Windows paths:** `claude` is not on Git Bash's PATH (Python's
  `shutil.which` finds it — trust `find_cli()`), and Windows Python cannot
  open `/c/Users/...` paths — `cd` first and use relative paths, or use
  `C:\...`. Both burned time during the build.
- **Fresh clones need git identity** (`git config user.name/email` — repo-
  local here) and `gh auth`.
- The Claude Code **auto-mode permission classifier** blocked `gh pr merge`
  and `git checkout/switch -b` in the build session — plan around it (work
  landed on the already-current branch; merges are the user's anyway).
- **Emails go to siddharth99.ram@gmail.com** — the account email
  (bjagadeesan@gmail.com) is NOT the user's notification address.
- Costs in `token_usage.jsonl` / budget ledgers are **API-list-price
  equivalents**, not billed spend (work runs on a Claude subscription) — an
  honest heaviness proxy, not a bill.
