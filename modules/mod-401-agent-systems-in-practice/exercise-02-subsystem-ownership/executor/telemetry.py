"""Boundary telemetry: one structured log line + metrics per execute call.

The hard invariant: **no tool payload or argument values leak** into logs or
metrics. We emit identifiers and shapes (the arg *keys*, the payload *size*),
never contents. `test_no_payload_leak.py` proves a secret arg never appears in
emitted output.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field

from .contract import STATUS_OK, ToolCall, ToolResult

logger = logging.getLogger("executor.boundary")


@dataclass
class InMemoryMetrics:
    """A metrics sink standing in for statsd/Prometheus in tests and demos.

    `adopt-a-library` would replace this behind the same tiny surface — see
    adr/002-metrics-client.md.
    """

    counters: Counter = field(default_factory=Counter)
    timings_ms: dict[str, list[float]] = field(default_factory=dict)

    def incr(self, name: str) -> None:
        self.counters[name] += 1

    def timing(self, name: str, value_ms: float) -> None:
        self.timings_ms.setdefault(name, []).append(value_ms)


def _safe_arg_shape(args: dict) -> list[str]:
    """Return the arg *keys* only. Values are never emitted."""

    return sorted(args.keys())


def emit(
    call: ToolCall,
    result: ToolResult,
    *,
    retry_count: int,
    latency_ms: float,
    metrics: InMemoryMetrics,
) -> None:
    """Emit the boundary log line and metrics for one execute call."""

    # Structured log: identifiers and shapes, never contents.
    record = {
        "event": "tool_execute",
        "call_id": call.id,
        "tool_name": call.name,
        "status": result.status,
        "retry_count": retry_count,
        "latency_ms": round(latency_ms, 2),
        "arg_keys": _safe_arg_shape(call.args),
        "payload_size": len(result.payload) if result.payload else 0,
        # error is already a type name from the executor's redaction step.
        "error": result.error,
    }
    logger.info(json.dumps(record, sort_keys=True))

    # Metrics: success/error counter + latency timing, tagged by tool name.
    outcome = "success" if result.status == STATUS_OK else "error"
    metrics.incr(f"executor.{outcome}.{call.name}")
    metrics.timing(f"executor.latency.{call.name}", latency_ms)
