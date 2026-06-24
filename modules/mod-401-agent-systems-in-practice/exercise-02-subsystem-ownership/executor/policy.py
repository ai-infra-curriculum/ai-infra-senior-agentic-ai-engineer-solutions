"""Failure-policy constants — the single source of truth for behavior under stress.

Every number an operator might tune lives here, and `FAILURE_POLICY.md` plus the
runbook's "top alerts" section are generated from these constants (see
`runbook.py`) so documentation and behavior cannot drift.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Retry budget for transient transport failures.
MAX_RETRIES = 2
BACKOFF_BASE_S = 0.05

# Per-call deadline. A tool exceeding this is treated as a timeout and fails
# closed (status="error") rather than blocking the boundary indefinitely.
CALL_TIMEOUT_S = 5.0

# Circuit breaker (stretch goal): after this many consecutive transport failures,
# fail fast for COOLDOWN_S instead of hammering a dependency that is clearly down.
BREAKER_THRESHOLD = 5
BREAKER_COOLDOWN_S = 30.0

# Health: the subsystem reports unhealthy when the rolling error rate over the
# recent window exceeds this fraction. 0.5 is a deliberate choice for THIS
# subsystem (see RUNBOOK.md / health.py) — tools fail individually all the time,
# so we only alarm when the majority of recent calls failed.
HEALTH_WINDOW = 50
UNHEALTHY_ERROR_RATE = 0.5


@dataclass(frozen=True)
class FailureMode:
    """One row of the failure-policy table, used to generate FAILURE_POLICY.md."""

    name: str
    detection: str
    action: str
    surfaced_as: str


# The enumerated failure modes at the boundary. test_failure_modes.py proves the
# subsystem behaves exactly as each row documents.
FAILURE_MODES: tuple[FailureMode, ...] = (
    FailureMode(
        name="Transient transport error",
        detection="retryable exception (e.g. ConnectionError)",
        action=f"retry x{MAX_RETRIES}, exponential backoff",
        surfaced_as='status="error" after budget',
    ),
    FailureMode(
        name="Hard tool error",
        detection="non-retryable exception (e.g. ValueError)",
        action="fail closed, no retry",
        surfaced_as='status="error"',
    ),
    FailureMode(
        name="Timeout",
        detection=f"deadline {CALL_TIMEOUT_S}s exceeded",
        action="fail closed",
        surfaced_as='status="error"',
    ),
    FailureMode(
        name="Rate limit / backpressure",
        detection="RateLimitError (treated as transient)",
        action=f"retry x{MAX_RETRIES} with backoff, then fail closed",
        surfaced_as='status="error" after budget',
    ),
    FailureMode(
        name="Malformed tool output",
        detection="output is not a dict (schema check)",
        action="fail closed, no retry",
        surfaced_as='status="error"',
    ),
)


class RateLimitError(Exception):
    """Backpressure signal from a transport; classified transient."""


class TimeoutExceeded(Exception):
    """Raised internally when a call exceeds CALL_TIMEOUT_S."""


def default_is_transient(exc: Exception) -> bool:
    """Transient = a retry might help. Timeouts and rate limits qualify."""

    return isinstance(exc, (TimeoutError, TimeoutExceeded, RateLimitError, ConnectionError))


# Type alias mirrored from exercise-01 for the injectable classifier.
TransientClassifier = Callable[[Exception], bool]
