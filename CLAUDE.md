# CLAUDE.md

Project-level guidance for Claude Code sessions in **dev-loop**. See
`SESSION_HANDOFF.md` for architecture and current state, `docs/design-plan.md`
for the original approved design, and `README.md` for usage. Adapted from the
job-applier CLAUDE.md — same Linear discipline, dev-loop-specific scope.

## What you are working on

This repo is the **scaffolding of an autonomous daily dev loop**, not the app
it improves. The target app (job-applier) lives at `c:/Users/siddh/Job Applier`
and has its own CLAUDE.md, conventions, and Linear backlog — changes to the
target belong in the target repo (or, once M2 is enabled, should be left for
the loop itself to make through its lane/PR pipeline). Here you build and tune
the orchestrator, stages, prompts, adapters, and project configs.

## Task tracking — keep Linear in sync

Work on this project is tracked in **Linear**, team **Job Applier Task
Management** (issue prefix `JOB-*`) — shared with the target project. The
Linear MCP server is configured in local dev config (`~/.claude.json`), not
committed to the repo.

**When you complete a task, update Linear before considering the work done:**

1. **Find the matching issue.** If the work maps to an existing `JOB-*` issue,
   use that. If no issue exists, create one first (`mcp__linear__save_issue`)
   so the board stays the source of truth, then proceed.
2. **Only mark work done once it's verified** — a real run (or `--dry-run` /
   `--stages` subset where appropriate) demonstrates the behavior. Do not
   close an issue optimistically.
3. **Move the issue to `Done`** and **add a brief closing comment**
   (`mcp__linear__save_comment`) referencing the commit SHA(s).
4. Partial work stays open — progress comment and/or `In Progress`.

Issues labeled `loop` were filed by the loop itself; issues labeled
`loop-deferred` were planned but deferred on budget and get planned first the
next morning. Don't hand-close those without checking the corresponding
`runs/<date>/` artifacts.

If the Linear MCP tools are unavailable in the current session, note that the
Linear update is pending rather than silently skipping it. (In *headless*
sessions Linear needs explicit `--mcp-config` — see SESSION_HANDOFF gotchas.)

## Conventions for changing the loop

- **Prompts are the product.** Behavior tuning belongs in `prompts/*.md`
  before it belongs in Python. Keep the hard safety language (worktree jail,
  no dependency edits, never-pause-to-ask) intact when editing prompts.
- **Stage contract:** stages communicate ONLY through `runs/<date>/` artifact
  files, validated by the orchestrator. Never make a stage parse structured
  data out of a model's chat text.
- **Generalization boundary:** anything target-specific goes in
  `projects/<name>.yaml` or `adapters/<name>.py` — never hardcode a target
  path, team name, or metric shape in `orchestrator/`.
- **Safety invariants** (do not weaken without the user's explicit say-so):
  the user's checkout is never touched; lane executors get no Linear and no
  dependency-file access; the review stage's file-overlap check stays in
  code; nothing is pushed to the target's `main` — PR only; budget ceilings
  and `--max-turns` stay on every spawn.
- **Verify with the cheap paths first:** `python -m orchestrator --dry-run`
  (fixtures, no spawns), then `--stages collect`, then a single-stage live
  run. A full live run costs real tokens — don't use it as a debugger.
- **After changing stages/prompts, update `SESSION_HANDOFF.md`** (dated entry
  + open-items reconciliation) before committing. Update `README.md` when
  user-facing usage changes. Keep `runs/` history committed — it is the
  loop's memory.
- ASCII-only in orchestrator console output (scheduled console is cp1252).
