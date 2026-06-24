"""Docs cannot drift: the committed Markdown matches the policy-generated tables.

This is the stretch goal — generate the runbook's alert thresholds and the
failure-policy table from `policy.py`, so behavior and documentation stay locked
together.
"""

from __future__ import annotations

from pathlib import Path

from executor import runbook

_DOC_DIR = Path(__file__).resolve().parent.parent


def _extract(marker: str, text: str) -> str:
    begin = f"<!-- BEGIN GENERATED: {marker} -->"
    end = f"<!-- END GENERATED: {marker} -->"
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return body.strip()


def test_failure_policy_table_matches_constants() -> None:
    doc = (_DOC_DIR / "FAILURE_POLICY.md").read_text()
    assert _extract("failure-policy", doc) == runbook.failure_policy_table().strip()


def test_runbook_thresholds_match_constants() -> None:
    doc = (_DOC_DIR / "RUNBOOK.md").read_text()
    assert _extract("alert-thresholds", doc) == runbook.alert_thresholds().strip()
