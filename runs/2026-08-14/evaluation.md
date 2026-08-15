# Morning evaluation — 2026-08-14 (job-applier)

Metrics collected 2026-08-14T16:54:23-07:00. **Linear was disabled this run**, so
the open backlog was reconstructed from `docs/backlog-multiuser.md`,
`SESSION_HANDOFF.md` §"Open items / Linear open", and the metrics note that cites
`JOB-103` as open. No duplicate-check against live Linear was possible — the one
existing-issue candidate below (JOB-103) is described from that note, not from the
issue body, and should be reconciled before filing anything new.

**Overall weighted health: 2.7 / 5.** The machine that *finds* work is healthy and
newly instrumented; the machine that tells us whether any of it *worked* is still
dark, and that is exactly the highest-weighted goal.

---

## Scorecard — metrics

| Metric | Current | Trend | Health |
|---|---|---|---|
| Posting yield | 895 new postings over 7 days / 11 runs (~81 per run); corpus 8,736 active, 511 title-matched, **262 qualifying** (3.0%) | Stable; 0 board failures on every day in the window (the 79-board total outage on 08-02 has not recurred) | **3 / 5** |
| Application success | 83 tracked all-time; 13 logged in the last 8 days (11 `submitted`, 2 `manual_submission`); **response/interview outcomes: not recorded at all** | Volume steady; success is unmeasurable | **2 / 5** |
| Reported bugs | 1 total, 1 open — and it is self-labelled `"instrumentation smoke test"` | Channel is 1 day old; no way to ever close a report | **3 / 5** |
| Token cost | `cost_usd_by_day: {}` — empty at collection. 3 session records on disk: $38.54 (opus-4-8), $44.49 (fable-5), $0.05 (haiku-4.5) | No trend computable | **2 / 5** |

### Posting yield — 3/5
The ingest is reliable: eleven runs across seven days, zero failed boards, and the
08-02 total outage (79/79 boards dark, 0 new) never repeated. What is weak is the
*conversion*, and our view of it. Qualifying-yield persistence (schema v3) landed
only this morning, so `new_qualifying` is populated for **08-14 alone** — 254 new
postings → 3 title-matched → **1 qualifying**. Every earlier day is `null` and will
stay that way; the series starts today and needs ~2 weeks before a trend exists.

The more actionable signal is in the digest's per-company table: 511 postings match
the title filters but only 262 survive the full baseline, and eight boards convert
**title-matched → 0 qualifying**, including Brex (33→0), Databricks (31→0),
Anthropic (19→0), Scale AI (19→0), Airbnb (15→0), Decagon (12→0), Figma (8→0),
Robinhood (7→0). That is ~144 title-matched roles at the biggest, best-known
employers dropping out for an unknown reason. `store.passes_baseline` already
computes and *returns* that reason (`title` / `seniority:<x>` / `location` /
`salary_below_floor`) — `list_postings_from_store` throws it away into an
undifferentiated `hidden_by_criteria` count (`src/store.py:395`). We are one
histogram away from knowing whether the filters are correctly strict or quietly
eating the best half of the funnel.

### Application success — 2/5
83 applications submitted, and **zero** of them have a recorded outcome. The
`applications.json` record shape is `company / job_title / url / date / status /
fields` — `status` is a *submit* vocabulary (`submitted` / `manual_submission` /
`attempted`), not an *outcome* vocabulary. There is no field for a reply, a
rejection, a screen, or an interview. G1's success criterion ("response rate
becomes trackable") is therefore not merely un-met; nothing in the system can
currently express it.

The denominator is also soft, as the collector's own note says (JOB-103). Working
the proxy against ground truth for 08-13: seven jobs were prepped (Ambience,
Benchling, ClickUp, Hadrian, Headway, Propel, Ramp) and five were logged as
submitted — **ClickUp and Ramp were prepped and then vanished** with no record of
whether they were parked, failed, or abandoned. Separately, the proxy reports 5
attempts on 08-12, but no prep file in the profile carries an 08-12 date, so the
proxy's day attribution is itself unreliable. Both facts argue the same thing: the
denominator needs to be *emitted by the apply flow*, not reverse-engineered from
file timestamps.

### Reported bugs — 3/5
The report channel works end-to-end (sidebar → modal → `POST /api/bug-report` →
`data/bug-reports.jsonl`). The lifecycle does not: the store is append-only,
`GET /api/bug-reports` filters on `status == "open"`, and **nothing in the codebase
ever writes a non-open status** (`server/data_api.py:658-691`). The one open report
is explicitly an instrumentation smoke test, so it will sit at the top of every
morning scorecard forever and the bug metric will never be able to distinguish
"nothing broke" from "nobody can close anything".

Triage of that report ("filter resets after refresh", page `postings`): reading
`PostingsPage.tsx`, the in-app **Refresh** button calls `runRefresh` → `reload()`
and never touches filter state, so filters *do* survive an in-app refresh. What
does not survive is a **browser** reload — filter state is component `useState` with
no URL or `localStorage` persistence. That is a genuine (minor) gap, but the
2026-01-01 run already proposed `fix-postings-filter-reset` for it, so it is **not
re-proposed here**; it should be closed as a duplicate/test once a close path exists.

### Token cost — 2/5
Instrumented but unreadable. `cost_usd_by_day` came back empty because the adapter
keys sessions on `updated_at` (`adapters/job_applier.py:130`) and that field is
produced by a **two-line edit to `scripts/token_report.py` that is still
uncommitted in the working tree**. The oldest record predates the fix and has no
date at all; the two dated records were written 14s and 30s *after* the snapshot was
taken, so this morning's collection also lost a race with its own hook.

The numbers that do exist are worth noting honestly: $38.54 and $44.49 for two
sessions. These are **API-list-price equivalents computed by `token_report.py`, not
billed spend** — the work runs on a Claude Code subscription — but as a proxy for
"how heavy is a session", tens of dollars per session is exactly the scale G2 says
to avoid. Two data points is not a trend; the point is that we still cannot draw
one.

**Action item, not a story:** commit the `updated_at` line (it is already written)
so tomorrow's run can compute a real 7-day average. That is a two-line diff riding
the existing PR flow, not something worth a backlog entry — but leaving the loop's
own cost metric dependent on an uncommitted local edit is a small G3 violation.

---

## Scorecard — goals

| Goal | Weight | Health | Reasoning |
|---|---|---|---|
| **G1** — land interviews, not just applications | 5 | **2 / 5** | 83 applications, 0 recorded outcomes. Response rate is not low; it is *unrepresentable*. Targeting quality is also half-blind — 144 title-matched roles at top employers fail the baseline for reasons we discard. |
| **G2** — keep the system cheap to run | 3 | **2 / 5** | Plumbing exists; the number does not. `cost_usd_by_day` is empty, the two observed sessions are $38–44 API-equivalent, and the fix that makes the series computable is uncommitted. |
| **G3** — the loop earns trust before autonomy | 4 | **4 / 5** | This is the healthy one: the last commit was pure instrumentation, PR #7 is open with the merge left to the user, no loop-caused regression has been reported, and every proposal below is small and reversible. Docked one point for the uncommitted working-tree edit that the loop's own metrics depend on. |

Weighted: (2×5 + 2×3 + 4×4) / 12 = **2.7 / 5**.

---

## Candidates

Four proposals, ordered by goal weight. All were cross-checked against the de-scope
list in `docs/backlog-multiuser.md` (nothing here touches server-side execution,
auth, Terraform, GDPR tooling, admin UI, or the other deferred items), against the
known-open backlog (JOB-24/32/34/59/82–98/103), and against the 2026-01-01 run log.

1. **`app-outcome-tracking`** (new, medium) — an `outcome` field on every application
   record plus a way to set it, so response rate becomes a number. Directly serves
   G1 (weight 5), which nothing else in the backlog does. Additive and optional:
   the field is absent on all 83 existing records and the apply flow never reads it,
   so the dedupe key and every skill stay untouched.

2. **`JOB-103`** (existing) — instrument the attempt denominator at apply time
   instead of inferring it from prep-file timestamps. The ClickUp/Ramp disappearance
   above and the phantom 08-12 bucket are concrete evidence the proxy is wrong in
   both directions. Pairs with #1: outcomes without a trustworthy denominator still
   do not give a rate. *(Filed before this run; scope described from the collector's
   note because Linear was unavailable — reconcile before adding acceptance criteria.)*

3. **`baseline-dropoff-reasons`** (new, small) — stop discarding the reason string
   `passes_baseline` already returns; aggregate it per company into the digest and
   the postings banner. Nearly free (the value is computed today and thrown away)
   and it answers the sharpest open question in the yield data: why Brex 33→0.

4. **`bug-report-lifecycle`** (new, small) — an append-only status transition so a
   triaged report can be closed. Without it the bug metric permanently reads "1
   open" and the loop can never act on its own triage. Serves G3 by making a
   verification signal honest.

Deliberately **not** proposed: the postings filter-persistence fix (already proposed
2026-01-01), anything in M2–M4 (large, human-sequenced, and gated on decisions this
loop should not make), and Phase-2 embeddings (JOB-32 — a large change with no
metric currently able to show it helped).
