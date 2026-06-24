# mod-405-technical-leadership: Technical Leadership for Agentic Teams — Solutions

Reference solutions for the mod-405 leadership exercises. These are model leadership artifacts — a worked agent-PR review, a paved-road RFC plus golden-path template, and a sequenced delivery plan — not runnable code. Each solution gives the approach, the reference artifact, how it meets the acceptance criteria, and common pitfalls.

## Exercises

- [exercise-01-agent-code-review-standards](exercise-01-agent-code-review-standards/README.md) — an adapted agent-PR review rubric (failure mode per row) and a severity-ordered review of the `support-triage` PR that finds the CRITICAL tool-authority-meets-untrusted-input path, plus the unbounded loop and eval gap, closing to a paved-road note.
- [exercise-02-paved-roads-and-standards](exercise-02-paved-roads-and-standards/README.md) — a paved-road RFC for "add a new worker agent" and a golden-path template with the safe defaults wired (bounded loop, scoped+audited tool registry, fenced untrusted input, starter eval), mapped to the exercise-01 rubric rows.
- [exercise-03-scoping-and-sequencing](exercise-03-scoping-and-sequencing/README.md) — a one-page delivery plan that scopes "automate tier-1 support" to a copilot-mode reliability spine slice, sequences de-risk-first, and ties decision points to measured go/pivot/kill signals.
