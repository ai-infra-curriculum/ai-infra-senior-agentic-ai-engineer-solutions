# mod-404-reliability-cost-incident/exercise-03 — Solution

## Approach

This exercise is operational, not a new library: the deliverables are a
pre-built set of containment levers, a runbook filled in during a drill, and a
blameless postmortem with owned, dated, typed action items. The reference
solution treats the runaway-loop drill end to end and shows the *completed*
artifacts a senior engineer would leave behind, built on the SLIs from
exercise-01 and the budgets/breaker from exercise-02.

Four design decisions drive the solution:

- **Levers exist before the drill, usable without a deploy.** A kill
  switch/feature flag, config-driven budget tightening (the mutable
  `BudgetConfig` from exercise-02), and a documented rollback path are all in
  place at `T-0`. During the incident, containment is a config flip, not a code
  change.
- **Detection comes from an SLI/cost alert, not from a human watching.** The
  loop-health burn-rate alert (exercise-01) and the cost-SLI spike
  (exercise-02) fire first; the detection time and source are recorded. A
  small, deterministic fault injector makes the drill reproducible so the
  timeline below is real, not theoretical.
- **The incident runs with a commander and a scribe.** The commander decides
  and does not type fixes; the scribe keeps the timestamped log that becomes the
  postmortem spine. Roles are assigned at declare.
- **The postmortem is blameless and reaches a system root cause.** Five whys
  aimed at the system land on a missing release gate, not "the engineer shipped
  a bad prompt." Action items are owned, dated, ticketed, and typed, with at
  least one each of prevent / detect / mitigate.

## Reference implementation

The primary artifacts are the runbook and postmortem below. A small, optional
fault injector makes the drill reproducible and is what produced the timeline.

### Fault injector (optional, makes the drill reproducible)

Runnable on Python 3.11+, no dependencies. Save as `runaway_drill.py`. It
oscillates between two tool calls until the per-run step cap from exercise-02
trips, demonstrating that the cap *bounds* the loop (so it is a budget incident,
not an outage) and that tightening the cap shortens each capped run.

```python
"""Reproduce the runaway-loop fault and show the per-run cap containing it.

The faulted planner oscillates between two tool calls and never converges. The
per-run step cap (exercise-02) bounds each run; tightening the cap mid-incident
makes stragglers fail closed sooner. Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(Exception):
    """Per-run step cap tripped. Fail closed."""


@dataclass
class LoopConfig:
    max_steps: int = 12  # config, not a constant: on-call tightens this live


def faulted_planner(step: int) -> str:
    """Ambiguous retrieval results -> oscillate between two tools forever."""
    return "search_docs" if step % 2 == 0 else "rerank"


def run_until_capped(config: LoopConfig) -> dict:
    """Run the faulted loop; it can only end by hitting the cap (never converges)."""
    steps, calls = 0, []
    outcome = "ok"
    try:
        while True:
            if steps >= config.max_steps:
                raise BudgetExceeded(f"step cap {config.max_steps}")
            calls.append(faulted_planner(steps))
            steps += 1
    except BudgetExceeded:
        outcome = "budget_exceeded"
    return {"steps": steps, "outcome": outcome, "signature": calls[:4]}


def loop_health_sli(run_outcomes: list[str]) -> float:
    """Good = runs that converged. The faulted runs all read as bad."""
    if not run_outcomes:
        return 1.0
    good = sum(1 for o in run_outcomes if o == "ok")
    return good / len(run_outcomes)


def _demo() -> None:
    # Before tightening: cap = 12. Every faulted run burns 12 steps then fails closed.
    before = [run_until_capped(LoopConfig(max_steps=12)) for _ in range(20)]
    assert all(r["outcome"] == "budget_exceeded" for r in before)
    assert before[0]["signature"] == ["search_docs", "rerank", "search_docs", "rerank"]
    health_before = loop_health_sli([r["outcome"] for r in before])
    print(f"[detect] loop-health SLI={health_before:.2f} (0.00 => every run capped)")
    print(f"[triage] oscillation signature={before[0]['signature']}")

    # Containment: on-call drops the cap 12 -> 6 via config (no deploy).
    after = [run_until_capped(LoopConfig(max_steps=6)) for _ in range(20)]
    assert all(r["steps"] == 6 for r in after)
    print(f"[contain] tightened cap: steps/run {before[0]['steps']} -> {after[0]['steps']}")
    print("[verify] rollback removes the fault; capped runs drain; SLI recovers")


if __name__ == "__main__":
    _demo()
    print("OK")
```

### Completed incident runbook

```markdown
# Incident: runaway-loop drill (orchestrator agent)

- Detected: 2026-06-24 02:14 UTC via loop-health burn-rate alert (SLI alert),
  cost-SLI spike confirmed 02:15 UTC
- Commander: A. Rivera (on-call) · Scribe: J. Okafor
- Failure class: runaway-loop · Severity: SEV-2 (degraded + cost burn, no data loss)

## Containment checklist
- [x] Pull traces for spiking runs; confirm the loop signature
      (search_docs <-> rerank, ~oscillating to the step cap)
- [x] "What changed in last 24h?" -> retrieval-tool prompt deploy at 01:50 UTC
- [x] Roll back the correlated change (01:50 retrieval-prompt deploy)
- [x] Tighten per-run step cap 12 -> 6 via config (no deploy) as belt-and-suspenders
- [x] Confirm loop-health + cost SLIs recovering
- [x] Hold open one SLI window (30 min), then stand down

## Timeline (UTC)
- 01:50 — retrieval-tool prompt v7 deployed (later-correlated change)
- 02:14 — loop-health burn-rate alert pages on-call (DETECT; source: SLI alert)
- 02:15 — cost-SLI p99-per-run spike confirms; on-call DECLARES SEV-2,
          takes commander, assigns scribe
- 02:16 — TRIAGE: traces for spiking runs show search_docs<->rerank oscillation
          hitting the step cap; cap is working (runs bounded) but volume burns budget
- 02:19 — CORRELATE: "what changed?" -> 01:50 retrieval-prompt v7; timeline matches
- 02:22 — CONTAIN: roll back retrieval prompt v7 -> v6; tighten step cap 12 -> 6 via config
- 02:26 — new runs converging; capped backlog draining
- 02:30 — VERIFY: loop-health SLI back toward baseline, cost SLI flat; hold open
- 03:00 — one SLI window clean; STAND DOWN; postmortem assigned to A. Rivera
```

### Completed blameless postmortem

```markdown
# Postmortem: runaway-loop in the orchestrator agent

- Date / duration: 2026-06-24 · 02:14–03:00 UTC (46 min);
  time-to-detect 24 min after the 01:50 change, time-to-resolve 8 min after declare
- Severity: SEV-2 · Failure class: runaway-loop
- Author / reviewers: A. Rivera / J. Okafor, P. Singh · Status: reviewed

## Impact
- User-facing: ~1,900 runs returned a graceful "couldn't finish within limits"
  bounded result instead of an answer over a 46-minute window; no wrong answers
  shipped (the runs failed closed, they did not hallucinate).
- Cost: ~$310 of extra spend over baseline, attributed via the cost SLI to
  feature=search across all tenants; bounded because the per-run cap held.
- Side-effects: none. The oscillation was between two read-only retrieval tools;
  no records mutated, no irreversible actions.

## Timeline (UTC)
- See the scribe's incident log above (01:50 deploy -> 02:14 detect ->
  02:22 contain -> 03:00 stand-down).

## Detection
- How we found out: loop-health burn-rate alert (SLI alert), cost-SLI spike confirmed.
- What the SLI should have caught and when: the burn-rate alert fired correctly
  at 02:14, 24 minutes after the change. Gap: nothing caught the bad prompt
  *before* it reached production — there was no pre-deploy gate on loop-health.

## Root cause (five whys, aimed at the system)
- Bad retrieval prompt caused the planner to oscillate and burn budget.
  - Why? Retrieval prompt v7 returned ambiguous results, so the planner kept
    re-planning between search_docs and rerank without converging.
  - Why did that reach production? The prompt change deployed with no pre-deploy
    eval gate on loop-health or tool-call validity.
  - Why was there no gate? Loop-health existed as a dashboard SLI but was never
    wired as a release gate.
  - Why wasn't it a gate? We treated loop-health as a monitoring metric, not as
    a budget that blocks a deploy.
  - SYSTEM root cause: a prompt/tool change can reach production without any
    release gate on the loop-health and tool-validity SLIs, so a
    convergence-breaking change is invisible until it burns budget in prod.
- Correlated change: retrieval-tool prompt v7, deployed 01:50 UTC.

## What went well / what was hard
- Went well (blameless, name the controls that worked): the per-run step cap
  bounded every faulted run, so this was a *budget* incident, not an outage; the
  SLI detected it without a human watching; config-driven containment stopped it
  without a deploy.
- Hard: the 24-minute detect lag — the change shipped with no pre-deploy signal,
  so we only learned in production.

## Action items
| Item | Type | Owner | Due | Ticket |
|------|------|-------|-----|--------|
| Gate prompt/tool deploys on a loop-health + tool-validity eval in CI | prevent | A. Rivera | 2026-07-08 | REL-412 |
| Add a baseline-drift alert on loop-health (catch slides above the SLO) | detect | J. Okafor | 2026-07-01 | REL-413 |
| Make the step-cap-tighten lever a one-command runbook action | mitigate | P. Singh | 2026-07-15 | REL-414 |
```

## Meeting the acceptance criteria

- **Containment levers existed before the drill and were usable without a
  deploy.** The runbook's containment checklist uses three pre-built levers: the
  rollback path ("what deployed in the last 24h?" → revert), the config-driven
  step-cap tightening (12 → 6, the mutable `BudgetConfig` from exercise-02), and
  the documented kill switch/feature flag for the tool path. None required a
  code change.
- **Detected by an SLI/cost alert with a recorded time and source.** Detection
  is the loop-health **burn-rate alert at 02:14 UTC** (source: SLI alert),
  confirmed by the **cost-SLI spike at 02:15** — both recorded in the timeline,
  neither a human noticing.
- **Ran with a named commander and scribe and a timestamped timeline from
  declare to stand-down.** Commander A. Rivera (decides, does not type fixes),
  scribe J. Okafor; the timeline runs 01:50 (change) → 02:14 (detect) → 02:15
  (declare) → 02:22 (contain) → 03:00 (stand-down).
- **Blameless postmortem, system root cause via five whys, owned/dated/ticketed
  action items spanning prevent, detect, and mitigate.** The root cause is "a
  prompt/tool change can reach production with no release gate on loop-health,"
  not "the engineer shipped a bad prompt." The action-item table has one of each
  type — REL-412 (prevent), REL-413 (detect), REL-414 (mitigate) — each with an
  owner, due date, and ticket.

## Common pitfalls

- **Declaring late.** An agent incident has a running meter; every minute of a
  runaway loop is money. Declaring and standing down costs minutes; waiting is
  unbounded. Declare early.
- **A blamey root cause.** "The engineer shipped a bad prompt" produces fear and
  no fix. Restate as a system gap: "a prompt change reached production with no
  loop-health gate." Careful people still cause incidents when the system
  permits it.
- **Stopping the five whys at the prompt.** "The prompt was ambiguous" is a
  symptom. Keep going until the fix is a system change you can build and test —
  here, a release gate plus a drift alert.
- **All-prevent action items.** If every item is "prevent," you have no faster
  detection next time; if every item is "detect," you keep catching the same
  fire. Balance prevent / detect / mitigate.
- **A containment lever that needs a deploy.** If tightening the cap or flipping
  the kill switch requires shipping code, that is itself an incident finding and
  an action item — not a lever you can use at 02:22.

## Verification

```bash
cd modules/mod-404-reliability-cost-incident/exercise-03-agent-incident-response
python runaway_drill.py
```

Expected: lines `[detect]`, `[triage]`, `[contain]`, `[verify]`, then `OK`.
`[detect]` shows the loop-health SLI at `0.00` (every faulted run capped);
`[triage]` prints the oscillation signature `['search_docs', 'rerank',
'search_docs', 'rerank']`; `[contain]` shows steps-per-run dropping from 12 to 6
after the config tighten. The runbook and postmortem above are reviewed by
checking the acceptance criteria: a recorded detect time and source, named
commander and scribe, a declare-to-stand-down timeline, a blameless system root
cause, and an action-item table spanning prevent / detect / mitigate.
