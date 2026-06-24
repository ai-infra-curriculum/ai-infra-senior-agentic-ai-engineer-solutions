# Runbook — tool-executor subsystem

Written for an operator who has never read the code. If you are paged for this
subsystem at 3 a.m., start here.

## What this subsystem does

The tool-executor takes a single `ToolCall` (an id, a tool name, and arguments)
from the planner, runs the named tool through a transport, and returns a
`ToolResult` to the synthesizer. It **never raises** — every failure comes back
as `status="error"`. It is **idempotent on call id**: replaying the same id
returns the recorded result without re-running the tool. It does not decide
*which* tools to call; it only runs the one it is handed and reports the outcome.

## Dependencies

- **Transport** — how a tool actually runs (HTTP service, MCP server, or
  in-process function). Most incidents originate here.
- **Idempotency store** — holds the result per call id (in-process today; see
  `adr/001`-class decisions in the exercise-01 ADR). If it is unreachable, the
  subsystem reports unhealthy and cannot dedupe replays.

## Top alerts and first diagnostic step

### Alert 1: error rate high (subsystem reports unhealthy)

`health()` reports unhealthy when the rolling error rate crosses the threshold
below. **First step:** check the boundary logs (`event=tool_execute`) and group
by `tool_name`. If one tool dominates the errors, the fault is that tool/its
transport — not the executor. If errors are spread across all tools, suspect the
transport layer or a shared downstream.

### Alert 2: circuit breaker open

The breaker opens after consecutive transport failures and fails fast with
`error="CircuitOpen"`. **First step:** the transport's downstream is almost
certainly down or rate-limiting. Confirm the downstream's own health; do not
restart the executor (the breaker will half-open and recover on its own after
the cooldown). Restarting only resets the breaker into hammering a dead
dependency.

### Alert 3: store unreachable (health reason = "idempotency store unreachable")

**First step:** the dedup store cannot be reached, so the subsystem is unhealthy
and replays are no longer idempotent. Check store connectivity first. While it is
down, the executor still serves calls but may double-run a replayed id — flag
that risk to anyone replaying traffic.

## Operator thresholds

These are generated from `policy.py` (`runbook.alert_thresholds()`), so they
match runtime behavior exactly:

<!-- BEGIN GENERATED: alert-thresholds -->

- Error rate over last 50 calls >= 50% -> subsystem reports unhealthy.
- 5 consecutive transport failures -> circuit breaker opens for 30s.
- Retry budget: 2 retries, 0s base backoff, 5s per-call deadline.

<!-- END GENERATED: alert-thresholds -->

## What you will NOT find in the logs

By design, no tool argument values or result payloads appear in logs or metrics
— only identifiers (`call_id`, `tool_name`), arg *keys*, payload *size*, and the
error *type*. If you need argument contents to debug, reproduce in a non-prod
environment; do not add payload logging to production.
