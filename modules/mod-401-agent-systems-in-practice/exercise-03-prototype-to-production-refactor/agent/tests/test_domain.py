"""Pure-function tests for domain.py — the cheapest tests in the suite."""

from __future__ import annotations

import pytest

from agent import parse_decision


def test_parse_answer() -> None:
    decision = parse_decision('{"answer": "hi"}')
    assert decision.is_answer is True
    assert decision.answer == "hi"


def test_parse_tool_call() -> None:
    decision = parse_decision('{"tool": "add", "args": {"numbers": [1, 2]}}')
    assert decision.is_answer is False
    assert decision.tool == "add"
    assert decision.args == {"numbers": [1, 2]}


def test_parse_rejects_output_with_neither_shape() -> None:
    with pytest.raises(ValueError):
        parse_decision('{"unexpected": true}')


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises(ValueError):
        parse_decision("not json")
