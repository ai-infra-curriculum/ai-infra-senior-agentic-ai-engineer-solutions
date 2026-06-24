# mod-401-agent-systems-in-practice/exercise-01 — Solution

## Approach

The exercise hands us the **tool-executor** box from a reference architecture
and asks us to own it behind a stable interface. The senior move here is not the
retry loop — it is sequencing the work so the *contract* exists before any
internals do, and so every internal decision stays reversible.

The solution is built in the order the chapters prescribe:

1. **Freeze the contract as types first** (`contract.py`). `ToolCall`,
   `ToolResult`, and the `ToolExecutor` / `Transport` / `Store` protocols are the
   only things neighbors import. They contain no transport, no retries, no
   framework — those would leak an internal into the boundary.
2. **Ship the stub as the executable contract** (`stub.py`). `StubExecutor`
   honors every promise and does no work, so the synthesizer team can build
   against it on day one while our internals are still empty.
3. **Implement the real executor with injected seams** (`real.py`). Transport,
   retry/timeout policy, and the idempotency store are all constructor-injected.
   The four-step body — replay-check, retry loop, error-trap, record — maps
   exactly to the boundary promises.
4. **Record the one open decision as an ADR** (`adr/001-idempotency-store.md`).
   The architecture did not say where idempotency state lives; we decided
   in-process behind the `Store` seam and wrote down when to revisit.
5. **Trace one request as an integration test** (`tests/test_integration.py`),
   asserting each boundary promise, plus a test for the contract's *assumption*
   (unregistered tool name).

The decisive design rule from Chapter 2 — *wrap whatever you choose behind your
own interface* — is applied to every seam, which is what makes the unregistered-
tool change (Reflection Q3) a contained edit rather than a rewrite.

## Reference implementation

Layout (all runnable; no live model or network required):

```text
exercise-01-architecture-to-implementation/
├── conftest.py                 # puts the package on sys.path for pytest
├── NOTES.md                    # reflection answers
└── executor/
    ├── __init__.py             # public surface
    ├── contract.py             # FROZEN: types + ToolExecutor/Transport/Store protocols
    ├── stub.py                 # StubExecutor — the executable contract
    ├── real.py                 # RealExecutor — replay → retry → error-trap → record
    ├── store.py                # InMemoryStore behind the Store protocol
    ├── caching.py              # stretch: CachingExecutor decorator
    ├── adr/001-idempotency-store.md
    └── tests/
        ├── fakes.py            # ScriptedTransport + helpers
        ├── test_contract.py    # stub & real both satisfy ToolExecutor
        ├── test_integration.py # one request across every boundary promise
        └── test_caching_decorator.py
```

The contract is the heart of the solution:

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: str               # STATUS_OK | STATUS_ERROR
    payload: dict | None = None
    error: str | None = None


@runtime_checkable
class ToolExecutor(Protocol):
    def execute(self, call: ToolCall) -> ToolResult: ...
```

The real executor's body is deliberately small — every line traces to a
contract promise:

```python
def execute(self, call: ToolCall) -> ToolResult:
    recorded = self._store.get(call.id)        # idempotency: replay short-circuits
    if recorded is not None:
        return recorded
    result = self._run_with_retries(call)      # retry transient; trap all raises
    self._store.put(call.id, result)           # record so future replays are no-ops
    return result
```

Two senior details worth calling out:

- **Error redaction.** `_redact` returns the exception *type name*, never its
  message, because tool exceptions routinely echo argument values back in their
  text. `test_error_message_does_not_echo_args` proves a secret arg never reaches
  the error string — boundary-validation discipline applied to the *outbound*
  edge.
- **Injected `sleep`.** Backoff is real in production but stubbed in tests
  (`sleep=lambda _s: None`), so the retry tests run in milliseconds without
  faking time globally.

## Meeting the acceptance criteria

| Criterion | Where it is met |
| --- | --- |
| `ToolCall`/`ToolResult` typed; stub and real both satisfy `ToolExecutor` | `contract.py`; `test_contract.py` asserts both with `isinstance` |
| Failing/timing-out transport produces `status="error"`, no exception escapes | `_run_with_retries` traps all exceptions; `test_timeout_surfaces_as_error_not_exception` |
| Replaying `call.id` returns the recorded result, transport not re-invoked | replay short-circuit in `execute`; `test_replay_is_idempotent_and_skips_transport` asserts `len(transport.calls) == 1` |
| ADR records the idempotency-store decision in four lines | `adr/001-idempotency-store.md` (status / context / decision / consequence) |
| Integration test traces one request through all three seams; unregistered-tool handling documented | `test_integration.py` — happy path, timeout, transient-recovery, replay, plus `test_unregistered_tool_assumption` with the inline rationale |

Stretch goals delivered: `CachingExecutor` decorator (substitutable, proven in
`test_caching_decorator.py`); the `Store` protocol makes a Redis swap a wiring
change only; structured-logging-friendly redaction is in place at the boundary.

## Common pitfalls

- **Letting the framework leak into the contract.** If `contract.py` imported a
  LangGraph `Runnable` or an HTTP client, the framework becomes load-bearing and
  every neighbor inherits the dependency. Keep the boundary types free of
  internals; the framework lives behind `Transport`.
- **Treating the stub as throwaway.** The stub *is* the contract. If it returns a
  shape the real executor cannot reproduce, substitutability silently breaks.
  `test_contract.py` exists to catch that drift.
- **Catching exceptions too narrowly.** A boundary that only traps `TimeoutError`
  lets a `ValueError` escape and violates "never raises past the boundary." The
  trap is intentionally broad (`except Exception`) — this is the one place a bare
  catch is correct, and it is commented as such.
- **Caching errors.** `CachingExecutor` caches only `STATUS_OK`; caching a
  transient failure would pin it forever. Easy to get wrong by caching every
  result.
- **Defending the planner's invariant "just in case."** Adding a registry check
  in the executor duplicates ownership and masks planner bugs. The contract says
  the planner validated the name; we rely on it and document the escalation path
  instead.

## Verification

```bash
cd exercise-01-architecture-to-implementation
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

Expected: `11 passed`. (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` only sidesteps
unrelated globally-installed pytest plugins; the suite needs no third-party
packages — standard library plus `pytest` only.)
