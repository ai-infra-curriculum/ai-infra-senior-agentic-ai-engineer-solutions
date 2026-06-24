# mod-405-technical-leadership/exercise-03-scoping-and-sequencing — Solution

## Approach

The deliverable is a one-page delivery plan that turns the vague initiative "automate tier-1 customer support with an agent" into a sequence a stakeholder can read and a team can execute. The plan is a leadership artifact: its job is to make the sequencing *logic* legible, not just to list slices.

The whole solution hangs on one move from Chapter 4: for an agentic initiative the core uncertainty is **task reliability**, not "can we build it." Stakeholders imagine full autonomy; the unproven bet is whether the agent resolves a ticket category end-to-end at an acceptable success and safety rate. So "done enough" must be a *measured* eval bar, the spine slice must be the thinnest end-to-end path that tests that bet (descoped to copilot if autonomy is unproven), and the sequence must put the riskiest unknown first even when it isn't the most visible work.

The hardest part to get right — and the thing the acceptance criteria reward — is defending a "boring" slice one. The plan below makes slice 0 a copilot-mode reliability prototype on a single ticket category, measured against a held-out eval set, and the "why this order" paragraph sells that to a stakeholder who wanted the flashy UI. Decision points tie measured signals to go/pivot/kill so the bet becomes managed instead of open-ended.

## Reference artifact

```markdown
# Delivery plan: Agentic tier-1 customer support

## Outcome
Tier-1 support tickets in covered categories are resolved end-to-end by the
agent at a measured success and safety rate that lets us reduce human tier-1
load, with humans handling exceptions and escalations.

## Core bet (riskiest assumption)
The agent can resolve a tier-1 ticket category end-to-end — read, reason, act,
reply — at an acceptable success rate WITHOUT introducing unsafe actions (wrong
refunds, data leaks, bad promises). Everything else depends on this being true.

## "Done enough" bar
On a held-out eval set of real tickets in the target category:
- Resolution success >= 80% (correct resolution, human-graded or rubric-scored).
- Safety violations = 0 tolerated in the eval set (no unauthorized action, no
  PII leak, no commitment outside policy); any violation blocks autonomy.
- Escalation precision: when unsure, the agent escalates rather than guessing
  (measured false-resolve rate < 5%).
If we can't measure these, we can't ship autonomy — the eval set is slice 0's
first deliverable.

## Spine slice (proves the core bet)
| Slice | What ships | Proves / measures | Est. |
|-------|-----------|-------------------|------|
| 0 | Copilot on ONE ticket category: agent reads the ticket, drafts a resolution + reply, a human approves/edits/sends. Held-out eval set + scoring harness ship with it. | Core bet vs. the bar: measured draft-quality success rate and zero-safety-violation check on the one category. Generates labeled data for autonomy later. | 2-3 wk |

## Sequence (de-risk first, value early, integrate incrementally)
| # | Slice | Ships value to | Risk it retires | Depends on | Parallel? |
|---|-------|----------------|-----------------|------------|-----------|
| 1 | Graduate slice-0 category to bounded autonomy (agent resolves directly; human spot-checks a sample; auto-escalate on low confidence) | End customers (faster resolution) + support team (load drop) | "Can it run unattended at the bar on a proven category" | Slice 0 eval bar met | No — gated on slice 0 result |
| 2 | Add categories 2-3 in copilot mode, reusing the slice-0 harness | Support team (more coverage) | "Does the approach generalize beyond one category" | Slice 0 harness (frozen eval/scoring interface) | Yes — categories parallel behind the frozen harness interface |
| 3 | Observability + safety dashboard: live success rate, escalation rate, safety-flag stream, per-category trend | Ops + leadership (trust, control) | "Can we run this in production without flying blind" | Tracing interface frozen in slice 0 | Yes — runs alongside slices 1-2 |

## Decision points
| After slice | Signal measured | Go | Pivot | Kill |
|-------------|-----------------|----|----|----|
| 0 | Draft success rate + safety violations on held-out set | >= 80% success, 0 safety violations -> slice 1 (autonomy) | 50-80% success -> stay in copilot mode, ship value, keep collecting data | < 50% success or any unfixable safety violation -> stop; the core bet is false |
| 1 | Unattended success + escalation precision on the live category | At/above bar -> expand (slice 2) | Below bar -> revert that category to copilot, re-prototype | Persistent safety failures -> pull autonomy entirely |

## Why this order
Slice 0 is the unglamorous reliability prototype, not the customer-facing UI,
because the whole initiative rests on one unproven question: will the model
actually resolve tickets safely and often enough? We answer that in week one,
in copilot mode, measured against a held-out eval set — so if the answer is no,
we've spent three weeks, not three months, and we still shipped a tool that
drafts replies for human approval (real value, real data) while we learn. We
build autonomy and breadth on top of a *proven* core, not around an unproven
one. Copilot mode is the feature that lets us ship and measure at the same time.
```

## Meeting the acceptance criteria

- **Outcome and single riskiest assumption, one sentence each** — the Outcome and Core bet sections are each one sentence; the core bet is the task-reliability assumption (resolve a category end-to-end safely), exactly the agentic failure mode Chapter 4 flags.
- **"Done enough" is a measurable bar** — success >= 80% on a held-out set, zero tolerated safety violations, escalation/false-resolve thresholds — not "it works in the demo."
- **Spine slice is genuinely thin, end-to-end, and tests the bet against the bar (descoped to copilot)** — slice 0 is one ticket category in copilot mode (agent drafts, human approves), shipping the eval set and scoring harness that *measure* the bet; it is end-to-end (read → reason → draft → reply) but the thinnest such path.
- **Sequence puts riskiest unknown early, ships usable value each slice, integrates incrementally, notes parallelism behind interfaces** — slice 0 retires the core reliability risk first; every slice ships something usable (copilot tool, then autonomy, then more categories, then dashboard); slices 2 and 3 run in parallel behind the frozen harness and tracing interfaces; slice 1 is an explicit hard dependency on the slice-0 result.
- **At least one decision point ties a measured signal to go/pivot/kill** — both decision points do, with concrete numeric thresholds driving go (expand autonomy), pivot (stay/revert to copilot), or kill (core bet false).
- **"Why this order" would make a stakeholder accept a boring slice one** — the paragraph reframes the boring slice as the cheapest way to answer the only question that matters, and shows copilot mode shipping value while the bet is still being proven.

The `NOTES.md` reflection answers: de-risk-first and ship-value-early conflicted because the riskiest work (reliability measurement) is less visible than a UI — resolved by making slice 0 copilot mode, which is *both* the de-risk prototype and a shippable value increment, so the conflict largely dissolves. The cheapest experiment that would kill the initiative fastest **is** slice 0: it directly measures the core bet on real tickets, so a sub-50% result kills it in weeks. To the stakeholder who wants the flashy UI in slice 1, the one sentence is: *"A beautiful UI on top of an agent that resolves tickets wrong is a faster way to lose customer trust — we prove it resolves correctly first, then make it pretty."*

## Common pitfalls

- **A spine slice that's the whole system.** "Slice 0: build the orchestrator, memory, integrations, and UI" defeats the purpose. The spine is the *thinnest* end-to-end path that tests the bet — one category, copilot mode, an eval set. Over-scoped slice 0 is the most common failure.
- **"Done enough" stated as a demo, not a measure.** "It resolves tickets in the demo" is not a bar. Without a success-rate and safety threshold on a held-out set, you can't responsibly ship autonomy or honestly decide go/pivot/kill.
- **Sequencing the visible work first.** Putting the UI or integrations in slice 1 because they demo well builds throwaway scaffolding around an unproven core. De-risk wins early; say so explicitly to the stakeholder rather than quietly reordering.
- **Decision points without measured signals.** "After slice 1 we'll reassess" is not a decision point. Each must name the signal *and* the numeric threshold that triggers go, pivot, or kill, so the bet is managed on evidence, not sunk cost.
- **Refusing to descope to copilot.** Insisting on full autonomy in slice 0 because that's the stated ambition forfeits the ship-and-measure advantage. Copilot mode is a feature that generates the data autonomy needs — treating it as a retreat is the conceptual error the chapter warns against.
