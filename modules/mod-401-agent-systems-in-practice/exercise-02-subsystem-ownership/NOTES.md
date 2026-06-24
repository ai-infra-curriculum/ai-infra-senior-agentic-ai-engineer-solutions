# Reflection — exercise-02

## 1. A failure mode I chose to fail closed, and who pays if I'm wrong

I fail **closed** on malformed tool output (a non-dict payload). The tradeoff:
failing closed turns a confusing tool into a clean `status="error"` the planner
can route around, but it also means a tool that returns a *slightly* off shape
(say, a list of one dict) is rejected outright rather than salvaged. If I chose
wrong — if that shape was actually usable — the affected party is the end user,
who gets a "tool failed" path for a call that could have succeeded. I accept that
because the alternative, failing *open* with a best-effort coercion, feeds the
synthesizer data of unknown provenance, and a synthesizer cannot tell a coerced
guess from a real answer. A visibly failed call is safer than a silently wrong
one.

## 2. Where writing the runbook exposed a design choice only obvious in my head

Writing Alert 2 (circuit breaker open) forced me to state the rule "do not
restart the executor — the breaker recovers on its own." That rule lived only in
my understanding of the half-open logic. An operator's instinct is to restart a
sick service; my design *punishes* that instinct by resetting the breaker into
hammering a dead dependency. The runbook is where that implicit "don't touch it"
contract had to become explicit — and it told me the breaker's recovery behavior
needed to be observable in `health()` (it is: `breaker_open`), or the operator
has no way to confirm the runbook's advice is working.

## 3. The observability signal I'd miss most in an incident

`retry_count` per call. Status alone tells me a call failed; latency tells me it
was slow. But `retry_count` is what distinguishes "the downstream is flaky but
recovering" (high retries, eventual success) from "the downstream is hard-down"
(failures with zero useful retries) from "we're amplifying load on a struggling
dependency" (every call burning its full retry budget). During an incident that
single number is the fastest discriminator between *wait it out* and *shed load
now*, and it is cheap — one integer already in the log line.
