"""Health signal: can this subsystem serve, and is its recent error rate sane?

"Unhealthy" is a senior judgment call, written down in policy.py and RUNBOOK.md:
for a tool-executor, individual tool failures are normal, so we only report
unhealthy when (a) a hard dependency is unreachable, or (b) the *majority* of
recent calls failed. A single failing tool must not page anyone.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from . import policy


@dataclass(frozen=True)
class HealthReport:
    healthy: bool
    reason: str
    error_rate: float
    sample_size: int
    breaker_open: bool


class HealthTracker:
    """Rolling error-rate window plus a hook for breaker state and store reachability."""

    def __init__(self, window: int = policy.HEALTH_WINDOW) -> None:
        self._outcomes: deque[bool] = deque(maxlen=window)  # True = error

    def record(self, *, is_error: bool) -> None:
        self._outcomes.append(is_error)

    def error_rate(self) -> float:
        if not self._outcomes:
            return 0.0
        return sum(self._outcomes) / len(self._outcomes)

    def report(self, *, store_reachable: bool, breaker_open: bool) -> HealthReport:
        rate = self.error_rate()
        size = len(self._outcomes)

        if not store_reachable:
            return HealthReport(False, "idempotency store unreachable", rate, size, breaker_open)
        if breaker_open:
            return HealthReport(False, "circuit breaker open", rate, size, breaker_open)
        if size > 0 and rate >= policy.UNHEALTHY_ERROR_RATE:
            return HealthReport(
                False,
                f"error rate {rate:.0%} over last {size} calls "
                f"exceeds {policy.UNHEALTHY_ERROR_RATE:.0%}",
                rate,
                size,
                breaker_open,
            )
        return HealthReport(True, "serving", rate, size, breaker_open)
