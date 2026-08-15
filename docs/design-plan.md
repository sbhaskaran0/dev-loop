# Autonomous Dev Loop — generalized scaffolding + Job Applier instrumentation

> **Archived design plan** (approved 2026-08-14, executed the same day). This
> is the plan as approved before implementation — kept for the *why*. Where it
> disagrees with the code, the code and `SESSION_HANDOFF.md` win. Known
> deltas: Linear needs explicit `--mcp-config` in headless stages (discovered
> during verification); instrumentation landed on PR #7's branch rather than a
> separate branch (permission classifier blocked branch switching); the target
> repo's Part A items are done (JOB-102).

## Context

Build a **daily autonomous development loop** that improves the Job Applier: every
morning it checks open Linear stories, evaluates app success on defined metrics,
identifies pareto-optimal enhancements, files Linear stories, builds a
dependency-aware delegation plan with a token cutoff, passes an adversarial
codebase-health gate, executes with parallel agents (model tier matched to task
complexity), then commits to a dated branch, opens a PR, updates Linear, writes a run
log, and emails a summary. The scaffolding is **generalized, in its own repo** —
job-applier is just its first configured target. Future pluggable stage: a "PM" agent.

**User decisions (confirmed via AskUserQuestion):**
- Loop lives in a new sibling repo `c:\Users\siddh\dev-loop` (own git, pushed to GitHub under sbhaskaran0)
- Branch + PR per run; user merges — nothing lands on main unattended
- ~500k output tokens per run default budget; overflow defers to next session
- Goals entered via `goals.md` in the loop repo (statement + success criteria + weight 1–5)
- Instrumentation: cheap fixes built now; apply-run ledger + pytest/CI seeded as the loop's first stories
- Notification: plain-text run log per run **plus a summary email to siddharth99.ram@gmail.com** (user corrected the address mid-plan — do NOT use bjagadeesan@gmail.com)

**Metrics & what exists (exploration-verified):**
- (a) Yield: `store.yield_stats()` is point-in-time only; `refresh_runs` table (57 rows) lacks a baseline-pass count — computed in `build_digest` (`src/refresh.py:27-71`) then discarded. Multiple refreshes/day happen.
- (b) App success: `applications.json` is success-only; parked/attempted/rejected_spam computed (`src/mcp_server.py:264-292`) but never persisted → **no denominator**. `data/prep/*.json` `snapshot_at` = weak attempted-proxy. Frontend already renders attempted/parked (dead branches).
- (c) Bugs: greenfield.
- (d) Tokens: `scripts/token_report.py` complete but unwired (no Stop hook anywhere, pre-migration output path, stale Opus-4.8 pricing); `server/chat.py:150-156` discards SDK `ResultMessage.usage`/`total_cost_usd`. `claude -p --output-format json` self-reports usage → budget ledger.

**Environment constraints (verified):** Windows 11 ARM64. Register scheduled tasks via PowerShell cmdlets (never `schtasks`: quoting bug + AC-only default); scheduled console is cp1252 → `PYTHONIOENCODING=utf-8` + ASCII console output. Concurrent Claude CLI *spawns* crash (serialize + stagger; running processes may overlap — `server/chat.py` lock pattern). `.mcp.json` is cwd-relative. Linear MCP (HTTP OAuth) lives in `~/.claude.json` keyed to the exact path string `c:/Users/siddh/Job Applier` — it will NOT load for worktree/dev-loop cwds. Target has zero tests/CI; gates available: `npm run build` (tsc), `python -m src.refresh`. `/commit` skill demands README+USER_GUIDE+SESSION_HANDOFF sync per commit. 09:00 refresh mutates `data/` daily.

---

## Part A — Milestone 0: instrumentation in the job-applier repo

**Sequencing prerequisites (flag to user, do first):**
1. Push `feat/profile-system-m1` + PR + merge (existing open item #1) — the bug-button
   work touches the same frontend files (App.tsx, Sidebar.tsx) that branch changed.
2. `server/chat.py` and `frontend/src/chat.ts` are dirty in the working tree — resolve
   (commit or stash) before P3 touches chat.py.
Then do P1–P3 on a fresh branch off main, committed via the `/commit` skill conventions.

**P1 — persist yield (metric a), ~40 lines:**
- `src/store.py`: `PRAGMA user_version` 2→3 migration — `ALTER TABLE refresh_runs ADD COLUMN new_qualifying INTEGER` (+ `title_matched INTEGER`); extend the insert at `store.py:274-279`; add `yield_history(days)` reader (group by date; multiple runs/day → sum new-counts).
- `src/refresh.py`: `build_digest` already computes the baseline-pass list — return the count and thread it into the `refresh_runs` write.

**P2 — bug-report button (metric c):**
- `frontend/src/components/BugReportModal.tsx` (new ~60 lines): clone `NewProfileModal` (`ProfileModals.tsx:63-116`), textarea (style ref `Onboarding.tsx:597-627`), Ctrl+Enter submit.
- `frontend/src/App.tsx`: modal state + render beside modal siblings (240-274) + `showToast` (71-75) on success; pass `onReportBug` to Sidebar.
- `frontend/src/components/Sidebar.tsx`: "Report bug" button near the theme toggle (copy style 255-263), new prop.
- `frontend/src/api.ts`: `reportBug()` via `send<T>` (13-25); type in `types.ts`.
- `server/data_api.py`: ~25 lines at file end copying `context_paste` (610-635): `POST /api/bug-report` appends `{ts, profile, page, text, status:"open"}` to `config.DATA_DIR / "bug-reports.jsonl"`; `GET /api/bug-reports` returns them (cheap, lets the loop and future UI read status).
- Add `data/bug-reports.jsonl` to `.gitignore` (runtime telemetry, like applications.json).
- Verify: `npm run build`, **restart the real server** (JOB-59 — check `Get-NetTCPConnection -LocalPort 8765` for squatters), then direct HTTP POST (SPA catch-all returns 200+index.html for unknown /api routes, so a browser check alone can lie).

**P3 — token accounting (metric d):**
- `scripts/token_report.py`: output path → active profile's `data/token_usage.jsonl` (resolve via `src.config`/`src.profiles`, same as the server); refresh pricing constants to current published rates at implementation time.
- New `.claude/settings.json` in the target: `Stop` hook invoking `token_report.py` with `PYTHONIOENCODING=utf-8`.
- `server/chat.py` (~5 lines): in the `ResultMessage` branch (150-156), stop discarding `usage`/`total_cost_usd` — append to the same JSONL.

**Linear:** file a `JOB-*` story for this instrumentation unit, close on verified commit per CLAUDE.md.

---

## Part B — the dev-loop repo (`c:\Users\siddh\dev-loop`)

Python 3 stdlib + PyYAML only; ~1,400 lines. No SDK — every Claude stage is a fresh
`claude -p` process (avoids SDK buffer/reader-death modes and MCP staleness; fresh
process per stage is also the ARM64-safe shape).

### Layout

```
dev-loop\
├── README.md  goals.md  requirements.txt (pyyaml)  .gitignore (worktrees/, raw-stdout, __pycache__)
├── orchestrator\
│   ├── __main__.py      # CLI: --project --date --stages --dry-run --no-linear --no-execute --budget
│   ├── config.py        # load/validate projects/<name>.yaml
│   ├── runner.py        # stage sequencing, runs\.lock, state.json, crash-safe log.md (try/finally)
│   ├── claude_proc.py   # spawn claude -p: stdin prompt, --output-format json, global spawn
│   │                    # lock + 20s stagger + one retry after 5s, timeout → taskkill /T /F
│   ├── gitops.py        # fetch/worktree add-remove-prune/merge/push/gh pr create (git -C, abs paths)
│   ├── budget.py        # usage ledger, lane admission, 10% reserve for integrate+finalize
│   ├── artifacts.py     # JSON schema validation + one "retry with correction note"
│   └── stages\          # collect, evaluate, file_stories, plan, review, execute, integrate, finalize
├── adapters\job_applier.py   # all target-specific metric readers (sqlite read-only URI,
│                             # applications.json, prep/, bug-reports.jsonl, token_usage.jsonl, digest)
├── prompts\*.md         # string.Template ($vars — prompts contain JSON braces); NOT skills,
│                        # so every filled prompt is inspectable in the run dir
├── projects\job-applier.yaml
├── fixtures\*.sample.json    # for --dry-run
├── scripts\run.cmd (self-locating, PYTHONIOENCODING=utf-8, >> runs\scheduler.log) + register_task.ps1
├── runs\<date>\         # TRACKED — the loop's own memory (metrics.json, evaluation.md,
│                        # candidates.json, stories.json, delegation*.json, review.json,
│                        # lanes\lane-N\{prompt.txt,result.json,raw-stdout.txt}, log.md, state.json)
└── worktrees\<date>\<lane>   # gitignored per-run checkouts of the TARGET repo
```

### Stage contract

Invocation: `claude -p --output-format json --permission-mode bypassPermissions --setting-sources user,project --model <tier> --max-turns N`, prompt piped via **stdin** (never argv). Structured outputs are **written by the agent to an absolute artifact path** stated in the prompt ("final reply: DONE"), then validated by the orchestrator — never parsed out of result text. Missing/invalid artifact → one retry with a correction note.

| Stage | Runner | cwd | Model | Output |
|---|---|---|---|---|
| collect | pure Python | — | — | `metrics.json` (each metric degrades to `instrumented:false` + note, never crashes) |
| evaluate | claude -p | **target repo, exact casing** (Linear loads) | opus | `evaluation.md` + `candidates.json` — scorecard weighted per goals.md, open JOB-* list, de-scope list (`docs/backlog-multiuser.md`), last 7 run logs; pareto-only candidates |
| file_stories | claude -p | target repo | sonnet | Linear issues labeled `loop` + `stories.json` (id map) |
| plan | claude -p | target repo | opus | `delegation.json` — lanes w/ full embedded story text, disjoint file sets, deps, per-lane model tier + est_output_tokens; overflow → `deferred` |
| review | claude -p | target repo | opus | adversarial gate for codebase health/scalability/hygiene: `review.json` + `delegation.approved.json` (amend/veto/lane-overlap check; enforces no-dependency-install policy) |
| execute | claude -p per lane | **lane worktree** | per-lane tier | commits on lane branch + `lanes/<id>/result.json`; 45 min/lane cap; failed lanes killed by process tree, worktree kept, never retried |
| integrate | Python + one claude -p | integrate worktree | sonnet | sequential `merge --no-ff` per lane (conflict → drop lane from run branch, push its branch, story → In Progress w/ comment); verification gates; **one doc-sync commit for the whole run** (deliberate deviation from per-commit doc rule — parallel lanes would collide; noted in PR body) |
| finalize | Python + one claude -p | target repo | haiku | push, `gh pr create --body-file pr-body.md`, Linear transitions (Done only if verified; partial → In Progress; closing comments w/ SHA), `log.md` epilogue, **summary email to siddharth99.ram@gmail.com via the Gmail connector** (best-effort: send failure logs a warning, never fails the run) |

Failure policy: spawn/parse failure → one retry after 5s; evaluate/plan/review failure → finalize-lite (log.md FAILED + traceback, no PR); Linear failure → degrade to `stories.pending.json` + "re-auth via /mcp" banner, never abort the run. Crash safety: log.md header written at start, section appended per stage, `try/finally` rewrites status; `state.json` rewritten on every change; `runs\.lock` (PID+time, stale-steal >6h) prevents overlap.

### Git/worktree flow (user's checkout NEVER touched)

`git -C <target> fetch` → `worktree prune` → per lane: `worktree add worktrees\<date>\lane-N -b loop/<date>/lane-N origin/main` (lanes branch off base, independent) → integrate worktree on `-b loop/<date>` → merge lanes sequentially → gates → doc-sync commit → push → `gh pr create`. Cleanup: remove merged-lane + integrate worktrees at finalize; keep failed lanes; prune >7-day-old dirs at next start. Worktrees carry their own `.mcp.json`/`src` so the job-applier MCP resolves per-worktree (no staleness); Linear is absent there by design — **all Linear-touching stages run with cwd = the real target repo** (read-only by prompt; artifacts + Linear mutations only). `target.venv_python` in config runs verification with the shared venv against worktree code; **lanes may not install dependencies or edit dependency files** (review enforces; such changes become stories).

### Budget

Ledger from each `claude -p` JSON result (`usage`, `total_cost_usd`) in `state.json`. Primary limit: cumulative **output tokens (default 500k)**; backstop USD ceiling ($40) for cache/input pathologies. 10% reserved for integrate+finalize. Admission check before each lane: spent + running estimates + next estimate ≤ 0.9×budget. Per-spawn `--max-turns` (lane default 80) + wall-clock timeout as independent breakers. Deferrals → Linear label `loop-deferred`, listed in log.md; next morning's plan slots them first. Max 2 concurrent lanes, spawns staggered 20s.

### Config (`projects/job-applier.yaml` — the generalization boundary)

Keys: `target` (cwd **exact-casing** `c:/Users/siddh/Job Applier`, remote, base_ref `origin/main`, branch_prefix `loop`, venv_python — confirm actual interpreter at setup), `adapter` (module path) + `adapter_paths` (db, applications, prep_dir, bug_reports, token_usage), `linear` (team "Job Applier Task Management", prefix JOB, labels loop/loop-deferred), `context_docs` (backlog-multiuser.md, CLAUDE.md), `notify` (email: siddharth99.ram@gmail.com), `policy` (budgets, reserve, max_lanes 4, max_concurrent 2, stagger 20s, per-stage models incl. lane_tiers {high: opus, medium: sonnet, low: haiku}, timeouts), `verification` (frontend `npm run build`; `{venv_python} -m src.refresh`), `stages` (ordered list — **the plugin point**: M1 ships `[collect, evaluate, file_stories, finalize]`; PM agent later inserts `pm_review` before `review`).

`goals.md`: `## G1: <title>` + Statement / Success criteria / Weight (1–5) bullets. Evaluator scores each metric, weights per goals, proposes only pareto-optimal or strongly-argued single-metric wins, cross-checks the de-scope list.

### Seeded first stories (filed in Linear during M1 setup, labeled `loop`)

1. **Apply-run ledger** — `profiles/<id>/data/runs.jsonl` written by the apply-batch flow persisting attempted/parked/rejected_spam (the metric-b denominator; touches the skill so it deserves its own review). Until it lands, collect uses the prep-file proxy flagged `instrumented:false`.
2. **Wire frontend attempted/parked statuses** (dead branches in ApplicationsPage.tsx) — follows #1.
3. **pytest + GitHub Actions CI** — becomes a real verification gate for execute lanes.
4. **Retroactive yield backfill** from `postings.first_seen` (nice-to-have).

### Scheduling & ops

`register_task.ps1`: `Register-ScheduledTask "DevLoop Daily"` at **09:30** (after the 09:00 refresh) + `Set-ScheduledTask` with `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable`. Collect waits up to 10 min for today's `refresh_runs` row, then proceeds with a note; sqlite opened read-only (`file:...?mode=ro`). Preflight at run start: `claude` resolves (find_cli preference order), `gh auth status`, cheap Linear probe (haiku, 2-min timeout → degrade mode on failure).

---

## Milestones & order of work

- **M0 (first):** prereqs (push feat/profile-system-m1; resolve dirty chat.py) → P1+P2+P3 instrumentation commits in job-applier → one-time setup checks (gh auth, claude on PATH, Linear answers from target cwd).
- **M1 (minimum honest loop):** repo scaffold + collect/evaluate/file_stories/finalize-lite (log.md + email, no code changes) + seeded stories + scheduled task. Run ~3 mornings to tune the evaluate prompt before trusting execution.
- **M2:** plan/review/execute/integrate — worktrees, budget ledger, adversarial gate, PR, Linear transitions. First M2 run: `--budget 100000`, `max_lanes: 1`.
- **M3 (later):** PM agent (`pm_review` stage), second `projects/*.yaml` to prove generalization, merge-conflict resolution session.

## Verification (no waiting for 09:30)

M1: (1) `--dry-run` full pipeline off fixtures (sequencing, lock, crash-safe log, budget math); (2) `--stages collect` vs real target → inspect metrics.json; (3) `--stages evaluate --no-linear` → read evaluation.md quality; (4) full run `--no-linear`, then one real manual run (verify email arrives at siddharth99.ram@gmail.com); (5) `Start-ScheduledTask` to prove the scheduled-console path. M2: (6) `--no-execute` through review; (7) hand-written trivial one-lane `delegation.approved.json` ("add a comment to README") with `--budget 50000` → verifies worktrees/merge/gates/PR/cleanup at minimal blast radius; (8) first unattended morning at `max_lanes: 1`. Crash test: kill mid-evaluate → log.md FAILED + lock clears next start.

## Top risks / mitigations

1. **Unattended bypassPermissions damage** — lanes jailed in fresh worktrees, prompts hard-forbid outside paths (user checkout, profiles/, data/, ~/.claude*), no dep installs, PR-only (recommend enabling GitHub branch protection on main), review gate checks scope.
2. **Runaway spend** — layered: max-turns + timeouts + admission + reserve + token budget + USD ceiling; worst case bounded by concurrent-lanes × per-lane caps.
3. **Worktree/MCP/venv interactions** — Linear stages pinned to target cwd exact casing; no-install policy; worktree prune; preflight round-trip test.
4. **Linear OAuth expiry headless** — probe at start, degrade to stories.pending.json, never abort; log banner tells user to `/mcp` re-auth.
5. **ARM64 spawn crashes / cp1252 console** — global spawn lock + stagger + one retry (proven server/chat.py pattern); PYTHONIOENCODING=utf-8; ASCII console output; UTF-8 artifact files.
