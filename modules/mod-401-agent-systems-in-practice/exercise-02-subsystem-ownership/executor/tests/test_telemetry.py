"""Boundary telemetry emits status, retry count, and latency."""

from __future__ import annotations

import json
import logging

from executor import (
    InMemoryStore,
    InstrumentedExecutor,
    ToolCall,
)
from executor.tests.fakes import ScriptedTransport, ok_payload, raises


def test_log_line_has_status_retry_and_latency(caplog) -> None:
    transport = ScriptedTransport([ok_payload({"v": 1})])
    executor = InstrumentedExecutor(transport, InMemoryStore(), sleep=lambda _s: None)

    with caplog.at_level(logging.INFO, logger="executor.boundary"):
        executor.execute(ToolCall("c1", "lookup", {"q": "x"}))

    record = json.loads(caplog.records[-1].getMessage())
    assert record["status"] == "ok"
    assert record["retry_count"] == 0
    assert "latency_ms" in record
    assert record["tool_name"] == "lookup"


def test_metrics_count_success_and_error() -> None:
    transport = ScriptedTransport([ok_payload({"v": 1}), raises(ValueError())])
    executor = InstrumentedExecutor(transport, InMemoryStore(), sleep=lambda _s: None)

    executor.execute(ToolCall("c1", "lookup", {}))
    executor.execute(ToolCall("c2", "lookup", {}))

    assert executor.metrics.counters["executor.success.lookup"] == 1
    assert executor.metrics.counters["executor.error.lookup"] == 1
    assert len(executor.metrics.timings_ms["executor.latency.lookup"]) == 2


def test_retry_count_surfaced_on_transient_recovery(caplog) -> None:
    from executor import policy

    transport = ScriptedTransport(
        [raises(policy.RateLimitError()), ok_payload({"v": 1})]
    )
    executor = InstrumentedExecutor(transport, InMemoryStore(), sleep=lambda _s: None)

    with caplog.at_level(logging.INFO, logger="executor.boundary"):
        executor.execute(ToolCall("c1", "tool", {}))

    record = json.loads(caplog.records[-1].getMessage())
    assert record["status"] == "ok"
    assert record["retry_count"] == 1
