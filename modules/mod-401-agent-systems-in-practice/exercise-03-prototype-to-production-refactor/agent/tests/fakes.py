"""FakeModel (replay) + tool fakes (Task 1, Task 4).

``FakeModel`` replays recorded raw responses keyed by the *number* of completions
so far, removing nondeterminism. ``ScriptedModel`` plays a fixed list of raw
strings in order, for asserting exact tool-call sequences.
"""

from __future__ import annotations

import json


class ScriptedModel:
    """Returns a fixed list of raw model strings, one per ``complete`` call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, messages: list[dict]) -> str:
        i = self.calls
        self.calls += 1
        if i >= len(self._responses):
            raise AssertionError("model called more times than scripted")
        return self._responses[i]


def tool_call(name: str, args: dict) -> str:
    return json.dumps({"tool": name, "args": args})


def answer(text: str) -> str:
    return json.dumps({"answer": text})


class RecordingTools:
    """Records every (name, args) the loop dispatched, returns a fixed observation."""

    def __init__(self, observation: str = "ok") -> None:
        self._observation = observation
        self.calls: list[tuple[str, dict]] = []

    def run(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        return self._observation


class RaisingTools:
    """A tool transport that raises, to exercise the loop's partial-failure path."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls: list[tuple[str, dict]] = []

    def run(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        raise self._exc
