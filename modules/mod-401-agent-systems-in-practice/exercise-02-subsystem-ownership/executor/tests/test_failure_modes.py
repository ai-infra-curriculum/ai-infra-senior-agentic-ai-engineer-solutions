"""Every failure mode in FAILURE_POLICY.md has a test proving documented behavior."""

from __future__ import annotations

from executor import (
    STATUS_ERROR,
    STATUS_OK,
    InMemoryStore,
    InstrumentedExecutor,
    ToolCall,
)
from executor import policy
from executor.tests.fakes import ScriptedTransport, ok_payload, raises, returns


def _executor(transport: ScriptedTransport) -> InstrumentedExecutor:
    return InstrumentedExecutor(transport, InMemoryStore(), sleep=lambda _s: None)


def test_transient_transport_retries_then_errors_after_budget() -> None:
    transport = ScriptedTransport([raises(ConnectionError()) for _ in range(3)])
    result = _executor(transport).execute(ToolCall("a", "tool", {}))

    assert result.status == STATUS_ERROR
    assert len(transport.calls) == 3  # 1 + MAX_RETRIES(2)


def test_hard_tool_error_fails_closed_without_retry() -> None:
    transport = ScriptedTransport([raises(ValueError("bad"))])
    result = _executor(transport).execute(ToolCall("b", "tool", {}))

    assert result.status == STATUS_ERROR
    assert result.error == "ValueError"
    assert len(transport.calls) == 1


def test_timeout_fails_closed() -> None:
    transport = ScriptedTransport(
        [raises(policy.TimeoutExceeded()) for _ in range(3)]
    )
    result = _executor(transport).execute(ToolCall("c", "slow", {}))

    assert result.status == STATUS_ERROR
    assert result.error == "TimeoutExceeded"


def test_rate_limit_is_treated_as_transient() -> None:
    transport = ScriptedTransport(
        [raises(policy.RateLimitError()), ok_payload({"v": 1})]
    )
    result = _executor(transport).execute(ToolCall("d", "tool", {}))

    assert result.status == STATUS_OK
    assert len(transport.calls) == 2  # retried once, then succeeded


def test_malformed_output_fails_closed() -> None:
    transport = ScriptedTransport([returns("not-a-dict")])
    result = _executor(transport).execute(ToolCall("e", "tool", {}))

    assert result.status == STATUS_ERROR
    assert result.error == "MalformedOutput"
    assert len(transport.calls) == 1  # not retried


def test_idempotent_replay_skips_transport() -> None:
    transport = ScriptedTransport([ok_payload({"v": 1})])
    executor = _executor(transport)
    call = ToolCall("f", "tool", {})

    executor.execute(call)
    executor.execute(call)

    assert len(transport.calls) == 1
