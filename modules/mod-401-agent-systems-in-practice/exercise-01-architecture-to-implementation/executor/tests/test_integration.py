"""Trace one request across every boundary promise (Task 5).

Each test follows a real call through transport, retry, and store, and asserts
one guarantee the architecture fixed. The final test covers the contract's
*assumption* — an unregistered tool name — and documents the handling choice.
"""

from __future__ import annotations

from executor import (
    STATUS_ERROR,
    STATUS_OK,
    InMemoryStore,
    RealExecutor,
    ToolCall,
    ToolResult,
)
from executor.tests.fakes import ScriptedTransport, ok_payload, raises


def _executor(transport: ScriptedTransport) -> RealExecutor:
    # sleep is stubbed so retry/backoff tests run instantly.
    return RealExecutor(
        transport=transport,
        store=InMemoryStore(),
        max_retries=2,
        sleep=lambda _s: None,
    )


def test_happy_path_returns_tool_result_type() -> None:
    transport = ScriptedTransport([ok_payload({"answer": 42})])
    result = _executor(transport).execute(ToolCall("c1", "lookup", {"q": "x"}))

    assert isinstance(result, ToolResult)
    assert result.status == STATUS_OK
    assert result.payload == {"answer": 42}
    assert result.call_id == "c1"


def test_timeout_surfaces_as_error_not_exception() -> None:
    # Transient on every attempt: after the retry budget, fail closed.
    transport = ScriptedTransport([raises(TimeoutError()) for _ in range(3)])
    result = _executor(transport).execute(ToolCall("c2", "slow_tool", {}))

    assert result.status == STATUS_ERROR
    assert result.error == "TimeoutError"
    assert result.payload is None
    assert len(transport.calls) == 3  # 1 initial + 2 retries


def test_transient_then_success_recovers() -> None:
    transport = ScriptedTransport([raises(TimeoutError()), ok_payload({"ok": 1})])
    result = _executor(transport).execute(ToolCall("c3", "flaky", {}))

    assert result.status == STATUS_OK
    assert len(transport.calls) == 2


def test_hard_error_is_not_retried() -> None:
    # A non-transient error should fail immediately, not exhaust the budget.
    transport = ScriptedTransport([raises(ValueError("bad arg"))])
    result = _executor(transport).execute(ToolCall("c4", "tool", {}))

    assert result.status == STATUS_ERROR
    assert result.error == "ValueError"
    assert len(transport.calls) == 1


def test_replay_is_idempotent_and_skips_transport() -> None:
    transport = ScriptedTransport([ok_payload({"v": 1})])
    executor = _executor(transport)
    call = ToolCall("c5", "lookup", {"q": "y"})

    first = executor.execute(call)
    second = executor.execute(call)  # same id replayed

    assert first == second
    assert len(transport.calls) == 1  # transport NOT invoked a second time


def test_error_message_does_not_echo_args() -> None:
    # The arg value must never leak through the error string.
    secret = "super-secret-token"
    transport = ScriptedTransport([raises(ValueError(secret))])
    result = _executor(transport).execute(ToolCall("c6", "tool", {"token": secret}))

    assert result.status == STATUS_ERROR
    assert secret not in (result.error or "")


def test_unregistered_tool_assumption() -> None:
    # The contract lets us assume the planner validated call.name. We rely on
    # that assumption rather than defending here: an unknown name reaches the
    # transport, which raises, and we surface it as status="error" like any
    # other tool failure. We do NOT add a registry check in the executor.
    #
    # Rationale: defending here would duplicate the planner's responsibility and
    # silently mask a planner bug. Escalating it (a distinct ToolNotFound on the
    # contract) is the architect's call; see NOTES.md Q3. Until then, an unknown
    # tool is just a failed call, which is already a safe, contract-honoring
    # outcome.
    transport = ScriptedTransport([raises(KeyError("no such tool"))])
    result = _executor(transport).execute(ToolCall("c7", "ghost_tool", {}))

    assert result.status == STATUS_ERROR  # never raises past the boundary
