"""Generate doc tables from policy constants so docs cannot drift from behavior.

`FAILURE_POLICY.md` and the runbook's alert thresholds are derived from
`policy.py`. Run this module to regenerate the tables; a test asserts the
committed `FAILURE_POLICY.md` matches the generated output.
"""

from __future__ import annotations

from . import policy


def failure_policy_table() -> str:
    """Render FAILURE_MODES as a Markdown table."""

    header = (
        "| Failure mode | Detection | Action | Surfaced as |\n"
        "| --- | --- | --- | --- |\n"
    )
    rows = "".join(
        f"| {m.name} | {m.detection} | {m.action} | {m.surfaced_as} |\n"
        for m in policy.FAILURE_MODES
    )
    return header + rows


def alert_thresholds() -> str:
    """Render the operator-facing thresholds the runbook references."""

    return (
        f"- Error rate over last {policy.HEALTH_WINDOW} calls "
        f">= {policy.UNHEALTHY_ERROR_RATE:.0%} -> subsystem reports unhealthy.\n"
        f"- {policy.BREAKER_THRESHOLD} consecutive transport failures -> circuit "
        f"breaker opens for {policy.BREAKER_COOLDOWN_S:.0f}s.\n"
        f"- Retry budget: {policy.MAX_RETRIES} retries, "
        f"{policy.BACKOFF_BASE_S:.0f}s base backoff, "
        f"{policy.CALL_TIMEOUT_S:.0f}s per-call deadline.\n"
    )


if __name__ == "__main__":  # pragma: no cover - manual regeneration helper
    print(failure_policy_table())
    print(alert_thresholds())
