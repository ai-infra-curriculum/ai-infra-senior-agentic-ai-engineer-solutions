"""Operable tool-executor: the exercise-01 core wrapped with ownership artifacts.

Over the exercise-01 executor this adds, in one place each:
  - an explicit, enumerated failure policy (policy.py) driving behavior,
  - boundary telemetry (telemetry.py) with payload scrubbing,
  - a timeout deadline and a circuit breaker (stretch),
  - a health signal (health.py).

The core promise is unchanged: `execute` never raises past its boundary.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from . import policy
from .contract import (
    STATUS_ERROR,
    STATUS_OK,
    Store,
    ToolCall,
    ToolResult,
    Transport,
)
from .health import HealthReport, HealthTracker
from .telemetry import InMemoryMetrics, emit


class _MalformedOutput(Exception):
    """Internal sentinel: transport returned a non-dict payload."""


class _Breaker:
    """Minimal circuit breaker: open after N consecutive failures for a cooldown."""

    def __init__(self, threshold: int, cooldown_s: float, clock: Callable[[], float]) -> None:
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at >= self._cooldown_s:
            # Cooldown elapsed: half-open — allow the next call through.
            self._opened_at = None
            self._consecutive_failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._opened_at = self._clock()


class InstrumentedExecutor:
    """Production-owned tool-executor with failure policy, telemetry, and health."""

    def __init__(
        self,
        transport: Transport,
        store: Store,
        metrics: InMemoryMetrics | None = None,
        *,
        max_retries: int = policy.MAX_RETRIES,
        timeout_s: float = policy.CALL_TIMEOUT_S,
        is_transient: policy.TransientClassifier = policy.default_is_transient,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._store = store
        self._metrics = metrics or InMemoryMetrics()
        self._max_retries = max_retries
        self._timeout_s = timeout_s
        self._is_transient = is_transient
        self._clock = clock
        self._sleep = sleep
        self._health = HealthTracker()
        self._breaker = _Breaker(
            policy.BREAKER_THRESHOLD, policy.BREAKER_COOLDOWN_S, clock
        )

    @property
    def metrics(self) -> InMemoryMetrics:
        return self._metrics

    def execute(self, call: ToolCall) -> ToolResult:
        started = self._clock()
        retry_count = 0
        try:
            recorded = self._store.get(call.id)
            if recorded is not None:
                result = recorded
            elif self._breaker.is_open:
                # Fail fast: do not hammer a dependency that is clearly down.
                result = ToolResult(
                    call_id=call.id, status=STATUS_ERROR, error="CircuitOpen"
                )
            else:
                result, retry_count = self._run_with_retries(call)
                self._store.put(call.id, result)
        except Exception as exc:  # store outage or unexpected internal error
            result = ToolResult(
                call_id=call.id, status=STATUS_ERROR, error=type(exc).__name__
            )

        latency_ms = (self._clock() - started) * 1000.0
        self._health.record(is_error=result.status == STATUS_ERROR)
        emit(
            call,
            result,
            retry_count=retry_count,
            latency_ms=latency_ms,
            metrics=self._metrics,
        )
        return result

    def _run_with_retries(self, call: ToolCall) -> tuple[ToolResult, int]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                payload = self._transport.run(call.name, call.args)
                if not isinstance(payload, dict):
                    # Malformed output: fail closed, do not retry.
                    raise _MalformedOutput
            except _MalformedOutput:
                self._breaker.record_failure()
                return (
                    ToolResult(call_id=call.id, status=STATUS_ERROR, error="MalformedOutput"),
                    attempt,
                )
            except Exception as exc:  # noqa: BLE001 - intentional boundary trap
                # A transport that overran its deadline raises TimeoutError /
                # TimeoutExceeded; both are classified transient and retried
                # within budget. Out-of-process timeout enforcement (a watchdog
                # thread or async cancellation) lives in the transport adapter,
                # keeping this loop synchronous and testable.
                last_error = exc
                self._breaker.record_failure()
                if attempt < self._max_retries and self._is_transient(last_error):
                    self._sleep(policy.BACKOFF_BASE_S * (2**attempt))
                    continue
                break
            else:
                self._breaker.record_success()
                return (
                    ToolResult(call_id=call.id, status=STATUS_OK, payload=payload),
                    attempt,
                )
        return (
            ToolResult(call_id=call.id, status=STATUS_ERROR, error=_redact(last_error)),
            self._max_retries,
        )

    def health(self) -> HealthReport:
        try:
            self._store.get("__health_probe__")
            store_reachable = True
        except Exception:
            store_reachable = False
        return self._health.report(
            store_reachable=store_reachable, breaker_open=self._breaker.is_open
        )


def _redact(exc: Exception | None) -> str:
    if exc is None:
        return "unknown error"
    return type(exc).__name__
