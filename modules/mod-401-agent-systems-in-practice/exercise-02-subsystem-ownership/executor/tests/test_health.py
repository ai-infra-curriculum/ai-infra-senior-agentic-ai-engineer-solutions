"""health() returns a defensible signal across the states the runbook describes."""

from __future__ import annotations

from executor import (
    InMemoryStore,
    InstrumentedExecutor,
    ToolCall,
)
from executor import policy
from executor.tests.fakes import ScriptedTransport, ok_payload, raises


def test_fresh_executor_is_healthy() -> None:
    executor = InstrumentedExecutor(
        ScriptedTransport([]), InMemoryStore(), sleep=lambda _s: None
    )
    report = executor.health()

    assert report.healthy is True
    assert report.reason == "serving"


def test_high_error_rate_reports_unhealthy() -> None:
    # Every call fails hard; once the window is majority-error, report unhealthy.
    script = [raises(ValueError()) for _ in range(policy.HEALTH_WINDOW)]
    transport = ScriptedTransport(script)
    executor = InstrumentedExecutor(transport, InMemoryStore(), sleep=lambda _s: None)

    for i in range(policy.HEALTH_WINDOW):
        executor.execute(ToolCall(f"c{i}", "tool", {}))

    report = executor.health()
    assert report.healthy is False
    assert report.error_rate >= policy.UNHEALTHY_ERROR_RATE


def test_store_unreachable_reports_unhealthy() -> None:
    store = InMemoryStore()
    transport = ScriptedTransport([ok_payload({"v": 1})])
    executor = InstrumentedExecutor(transport, store, sleep=lambda _s: None)

    store.reachable = False
    report = executor.health()

    assert report.healthy is False
    assert "store" in report.reason


def test_circuit_breaker_opens_after_consecutive_failures() -> None:
    # Enough hard failures (each a single transport call) to trip the breaker.
    n = policy.BREAKER_THRESHOLD + 1
    transport = ScriptedTransport([raises(ConnectionError()) for _ in range(n * 3)])
    executor = InstrumentedExecutor(transport, InMemoryStore(), sleep=lambda _s: None)

    for i in range(n):
        executor.execute(ToolCall(f"c{i}", "tool", {}))

    report = executor.health()
    assert report.breaker_open is True
    assert report.healthy is False
