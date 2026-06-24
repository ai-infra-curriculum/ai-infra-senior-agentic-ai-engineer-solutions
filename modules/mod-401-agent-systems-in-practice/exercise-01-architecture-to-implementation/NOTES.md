# Reflection — exercise-01

## 1. Rely on the planner vs. defend at my boundary

I drew the line at *who owns the invariant*. The contract explicitly states the
planner validates `call.name`, so re-checking it in the executor duplicates
ownership and, worse, would silently swallow a planner bug behind a generic
error. I defend only the invariants the contract assigns to *me*: never raising
past the boundary, idempotency on `call.id`, no payload in logs. What would
change my answer: if the planner and executor shipped on independent release
trains, or if an unknown tool name were a security event (e.g. it could trigger
an expensive or destructive default), I would harden at my boundary regardless,
because "trust upstream" stops being free once the blast radius is high.

## 2. Who could build against the stub on day one

The synthesizer team. `StubExecutor` returns a real `ToolResult` with a valid
`status` and `payload` shape, so they could write and test their result-merging
logic against it immediately. Without the stub they would have been blocked on
my retry loop, transport wiring, and store — none of which affect the *shape*
they consume. The stub let their work and mine proceed in parallel and kept my
internal churn out of their blast radius.

## 3. If the contract changes to "executor may raise `ToolNotFound`"

Small. The change is localized to two places: add a registry/validation seam (or
let the transport's existing `KeyError` map to a typed `ToolNotFound`), and lift
that one exception type out of the boundary trap in `_run_with_retries` so it
propagates instead of becoming `status="error"`. No neighbor that consumed
`ToolResult` breaks, because success and ordinary-failure paths are unchanged —
only the new escape hatch is added. The injected-seam design is exactly what
makes this a contained edit rather than a rewrite: the error policy already lives
in one method, not scattered across the executor.
