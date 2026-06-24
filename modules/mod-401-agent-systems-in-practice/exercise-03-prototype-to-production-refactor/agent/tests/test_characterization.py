"""Characterization tests: behavior is provably unchanged by the refactor (Task 1).

The prototype's behavior on representative inputs is frozen as expected snapshots.
Each test asserts the *refactored* ``agent.run_agent`` reproduces it exactly, and
a paired test confirms the snapshot still matches the original prototype — so the
snapshots are pinned to real prototype behavior, not invented.

These must stay green through every refactor step. Green == behavior preserved.
"""

from __future__ import annotations

import os

import pytest

from agent import AgentConfig, DemoModelAdapter, LocalToolTransport
from agent import run_agent as refactored_run
from prototype.prototype import run_agent as prototype_run

# Representative inputs covering: one-tool path, arithmetic-tool path, and the
# unknown-question fallback.
CASES = [
    "What is the weather in Phoenix?",
    "Please add 2 + 3 + 4",
    "Tell me a joke",
]

# Snapshots captured once from the prototype (the frozen "current behavior").
EXPECTED = {
    "What is the weather in Phoenix?": {
        "answer": "Result: phoenix: 72F sunny",
        "trace": [{"tool": "get_weather", "args": {"city": "phoenix"}}],
    },
    "Please add 2 + 3 + 4": {
        "answer": "Result: 9",
        "trace": [{"tool": "add", "args": {"numbers": [2, 3, 4]}}],
    },
    "Tell me a joke": {"answer": "I don't know.", "trace": []},
}


def _config() -> AgentConfig:
    # Config from a test env: proves the hard-coded key is gone (Task 2).
    return AgentConfig.from_env({"AGENT_API_KEY": "test-key"})


@pytest.mark.parametrize("question", CASES)
def test_refactored_matches_frozen_snapshot(question: str) -> None:
    result = refactored_run(
        question,
        model=DemoModelAdapter(_config()),
        tools=LocalToolTransport(),
        config=_config(),
    )
    assert result == EXPECTED[question]


@pytest.mark.parametrize("question", CASES)
def test_snapshot_still_matches_prototype(question: str) -> None:
    # Guards against the snapshot drifting away from real prototype behavior.
    assert prototype_run(question) == EXPECTED[question]


def test_no_secret_in_refactored_source() -> None:
    # The hard-coded key is a prototype smell; assert it never reappears in the
    # refactored package (the env is now the only source of the key).
    import pathlib

    pkg = pathlib.Path(__file__).resolve().parent.parent
    for py in pkg.glob("*.py"):
        assert "sk-prototype-HARDCODED" not in py.read_text()
        assert os.environ.get("AGENT_API_KEY") != "sk-prototype-HARDCODED"
