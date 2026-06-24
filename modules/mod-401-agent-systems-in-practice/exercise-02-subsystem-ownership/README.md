# mod-401-agent-systems-in-practice/exercise-02 — Solution

## Approach

Exercise-01 made the tool-executor *work*. This exercise makes it *operable* —
the difference between code that passes tests and a subsystem someone can be
paged for. The deliverable is ownership, so the prose artifacts (failure policy,
runbook, ADRs) carry as much weight as the code.

The design principle throughout is **one source of truth, derived everywhere
else**. The failure policy lives as constants in `policy.py`; `FAILURE_POLICY.md`
and the runbook's alert thresholds are *generated* from those constants, and a
test fails if the committed docs drift. That is the senior answer to "docs rot":
make drift impossible rather than promising to keep them in sync.

Five moves, matching the tasks:

1. **Explicit failure policy** — `policy.py` enumerates the five boundary failure
   modes as data; `FAILURE_POLICY.md` renders them. Behavior under stress is
   intentional, not emergent.
2. **Boundary telemetry with scrubbing** — `telemetry.py` emits one structured
   log line and metrics per call, logging *shapes* (arg keys, payload size) and
   *identifiers*, never contents. The payload-leak invariant has a dedicated test.
3. **Health signal** — `health.py` reports a defensible "can I serve?" signal
   over a rolling error window, with the definition of "unhealthy" written down
   and justified for *this* subsystem (tools fail individually all the time, so
   only a majority-error window or a dead dependency is unhealthy).
4. **Runbook** — `RUNBOOK.md`, written for someone who has never seen the code:
   one-paragraph purpose, dependencies, top three alerts, first diagnostic step
   each.
5. **Two build-vs-buy ADRs** — `adr/001-retry-library.md` (build, narrowly) and
   `adr/002-metrics-client.md` (adopt, explicitly *not* hand-rolling), each scored
   against the Chapter 4 grid.

## Reference implementation

```text
exercise-02-subsystem-ownership/
├── conftest.py
├── NOTES.md
└── executor/
    ├── __init__.py
    ├── contract.py        # boundary types (carried from exercise-01)
    ├── policy.py          # SINGLE SOURCE: retries, timeout, breaker, FAILURE_MODES
    ├── telemetry.py       # structured log + metrics, payload-scrubbing
    ├── health.py          # rolling error-rate window + HealthReport
    ├── executor.py        # InstrumentedExecutor: policy + telemetry + breaker + health
    ├── store.py           # InMemoryStore with a reachability flag for health
    ├── runbook.py         # generates the doc tables from policy.py
    ├── FAILURE_POLICY.md  # Task 1 (generated table region)
    ├── RUNBOOK.md         # Task 4 (generated thresholds region)
    ├── adr/
    │   ├── 001-retry-library.md
    │   └── 002-metrics-client.md
    └── tests/
        ├── fakes.py
        ├── test_failure_modes.py    # one test per FAILURE_POLICY.md row
        ├── test_no_payload_leak.py  # secrets never reach logs
        ├── test_health.py           # healthy / high-error / store-down / breaker
        ├── test_telemetry.py        # status, retry count, latency, metrics
        └── test_doc_consistency.py  # docs == policy constants (stretch)
```

The payload-scrubbing seam is the load-bearing safety property:

```python
def _safe_arg_shape(args: dict) -> list[str]:
    return sorted(args.keys())          # keys only — values never emitted

record = {
    "call_id": call.id,
    "tool_name": call.name,
    "status": result.status,
    "retry_count": retry_count,
    "latency_ms": round(latency_ms, 2),
    "arg_keys": _safe_arg_shape(call.args),     # shape, not contents
    "payload_size": len(result.payload) if result.payload else 0,
    "error": result.error,              # already a type name, never a message
}
```

The "unhealthy" definition is a deliberate judgment call, not a copied threshold:

```python
# A single failing tool is normal; only a majority-error window or a dead
# dependency is unhealthy. Threshold lives in policy.py, referenced in RUNBOOK.md.
if size > 0 and rate >= policy.UNHEALTHY_ERROR_RATE:   # 0.5 for THIS subsystem
    return HealthReport(False, ...)
```

## Meeting the acceptance criteria

| Criterion | Where it is met |
| --- | --- |
| Every failure mode in `FAILURE_POLICY.md` has a test proving documented behavior | `test_failure_modes.py` — transient, hard, timeout, rate-limit, malformed, plus idempotent replay |
| Telemetry emits status, retry count, latency; a test proves no payload leak | `telemetry.py`; `test_telemetry.py` + `test_no_payload_leak.py` (arg and error-message secrets) |
| `health()` returns a defensible signal; "unhealthy" is written down | `health.py` + `policy.py` (`UNHEALTHY_ERROR_RATE`) + `RUNBOOK.md`; `test_health.py` covers four states |
| `RUNBOOK.md` lets an unfamiliar reader take a correct first diagnostic step per alert | `RUNBOOK.md` — three alerts, each with a first step written for a code-blind operator |
| Two ADRs record retry and metrics build-vs-buy, at least one justifying adopt-over-hand-roll | `adr/001-retry-library.md` (build, narrow) + `adr/002-metrics-client.md` (adopt, explicitly not hand-rolled) |

Stretch goals delivered: a circuit breaker whose state shows in `health()`
(`breaker_open`); the runbook's thresholds and the failure-policy table generated
from `policy.py` with `test_doc_consistency.py` guarding against drift.

## Common pitfalls

- **Logging payloads "just for debugging."** The single most common way this
  invariant is broken is a well-meaning `logger.info(args)`. The scrub is
  centralized in `telemetry.py` and tested against a secret-looking arg *and* a
  secret echoed in an exception message — both are real leak vectors.
- **A copied health threshold.** Reusing a generic "error rate > 1% = unhealthy"
  would page on every flaky tool. The threshold here is justified for a subsystem
  whose individual calls fail routinely; the number must fit the subsystem, and
  the reasoning belongs in the runbook.
- **Docs that drift from behavior.** A hand-maintained policy table silently
  diverges the first time someone tunes a retry count. Generating the table from
  `policy.py` and asserting equality in a test makes drift a failing build.
- **Restart-as-reflex defeating the breaker.** If the runbook doesn't say "don't
  restart," an operator resets the breaker into a down dependency. The fix is
  documentation, and it only surfaced because the runbook was written for someone
  who knows nothing about the code (see `NOTES.md` Q2).
- **Hand-rolling the metrics aggregator.** Owning percentile buckets and an
  exporter is exactly the liability Chapter 4 warns against; ADR-002 adopts a
  client behind a two-method seam instead.

## Verification

```bash
cd exercise-02-subsystem-ownership
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q

# Regenerate the doc tables from policy.py (then test_doc_consistency guards them):
python3 -m executor.runbook
```

Expected: `17 passed`. Standard library plus `pytest` only;
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` only sidesteps unrelated globally-installed
pytest plugins.
