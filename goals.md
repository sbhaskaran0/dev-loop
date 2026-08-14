# Overarching Goals

Edit freely — the morning evaluator reads this file verbatim and weighs every
candidate enhancement against it. Format per goal: a heading, then Statement /
Success criteria / Weight (1–5, higher = matters more).

## G1: Land interviews, not just applications
- Statement: The pipeline should optimize for responses and interviews, not raw submission count — quality of targeting and materials over volume.
- Success criteria: Response rate becomes trackable, then trends up over 4 weeks.
- Weight: 5

## G2: Keep the system cheap to run
- Statement: Daily automation (applies + this loop) should stay at dollar-scale, not tens of dollars.
- Success criteria: 7-day average token cost visible in the scorecard and not trending up without a corresponding capability gain.
- Weight: 3

## G3: The loop earns trust before it earns autonomy
- Statement: Prefer instrumentation, verification, and small reversible changes over ambitious refactors; nothing lands on main without a human-reviewed PR.
- Success criteria: Zero loop-caused regressions reported as bugs; every merged PR passed its verification gates.
- Weight: 4
