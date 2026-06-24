# Failure policy — tool-executor

This table is the contract for behavior under stress. Every row has a test in
`tests/test_failure_modes.py` proving the subsystem behaves exactly as
documented. The table below is generated from `policy.FAILURE_MODES` by
`runbook.failure_policy_table()`; `tests/test_doc_consistency.py` fails if this
file drifts from the constants.

<!-- BEGIN GENERATED: failure-policy -->

| Failure mode | Detection | Action | Surfaced as |
| --- | --- | --- | --- |
| Transient transport error | retryable exception (e.g. ConnectionError) | retry x2, exponential backoff | status="error" after budget |
| Hard tool error | non-retryable exception (e.g. ValueError) | fail closed, no retry | status="error" |
| Timeout | deadline 5.0s exceeded | fail closed | status="error" |
| Rate limit / backpressure | RateLimitError (treated as transient) | retry x2 with backoff, then fail closed | status="error" after budget |
| Malformed tool output | output is not a dict (schema check) | fail closed, no retry | status="error" |

<!-- END GENERATED: failure-policy -->

## Why these choices

- **Fail closed by default.** The executor's contract is "never raise past the
  boundary." Every uncertain outcome becomes `status="error"`, so a caller never
  has to handle an exception from us — only a result.
- **Retry only the transient.** Hard errors (bad args, malformed output) cannot
  be fixed by trying again; retrying them just wastes the budget and delays the
  inevitable error. Only transport-level transients (connection resets, rate
  limits, timeouts) are retried.
- **No fail-open path here.** A degraded/partial result is *not* offered: a tool
  result is consumed by a synthesizer that cannot tell a real answer from a
  fabricated fallback. Failing closed and letting the planner decide is safer
  than inventing data. (The reflection in `NOTES.md` Q1 covers the one place this
  tradeoff is tense.)
