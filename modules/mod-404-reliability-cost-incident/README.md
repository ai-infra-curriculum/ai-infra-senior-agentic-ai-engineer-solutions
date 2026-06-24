# mod-404-reliability-cost-incident: Reliability, Cost & Incident Response — Solutions

Reference solutions for the SRE-for-agents module: quality SLOs that catch
drift (not just uptime), cost controls that fail closed, and an incident
response loop that ends in a durable, blameless postmortem.

Each exercise directory holds one self-contained solution README with the
approach, a runnable reference (or completed runbook/postmortem artifact for the
operational exercise), how it meets the acceptance criteria, common pitfalls,
and verification steps.

## Exercises

- [exercise-01 — Define agentic SLOs](exercise-01-agentic-slos/README.md):
  four quality SLIs as `good / valid` ratios, a Wilson-interval success SLI over
  the judged subset, error budgets, and paired burn-rate plus baseline-drift
  alerts.
- [exercise-02 — Cost controls in production](exercise-02-cost-controls-in-production/README.md):
  a per-run budget guard (check before, charge after, fail closed) and a
  per-tenant circuit breaker (reject fast from a shared store, fail closed on
  outage), with attributable cost records feeding a p99-cost SLI.
- [exercise-03 — Agent incident response](exercise-03-agent-incident-response/README.md):
  a reproducible runaway-loop drill, pre-built containment levers, a completed
  incident runbook, and a blameless postmortem with owned, dated, typed action
  items.

## Running the code

All reference code is pure-stdlib Python 3.11+. From any exercise directory:

```bash
python <reference-script>.py
```

Each `README.md` names its script and the expected output under `Verification`.
