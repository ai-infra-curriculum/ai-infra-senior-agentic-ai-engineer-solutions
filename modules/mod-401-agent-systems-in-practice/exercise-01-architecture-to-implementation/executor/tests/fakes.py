"""Test doubles for the executor's injected seams."""

from __future__ import annotations

from collections.abc import Callable


class ScriptedTransport:
    """A transport whose behavior per attempt is scripted.

    ``script`` is a list of callables, one per invocation: each either returns a
    payload dict or raises. Records every call so tests can assert the transport
    was (or was not) hit again on replay.
    """

    def __init__(self, script: list[Callable[[], dict]]) -> None:
        self._script = list(script)
        self.calls: list[tuple[str, dict]] = []

    def run(self, name: str, args: dict) -> dict:
        self.calls.append((name, args))
        index = len(self.calls) - 1
        if index >= len(self._script):
            raise AssertionError("transport invoked more times than scripted")
        return self._script[index]()


def ok_payload(payload: dict) -> Callable[[], dict]:
    return lambda: dict(payload)


def raises(exc: Exception) -> Callable[[], dict]:
    def _raise() -> dict:
        raise exc

    return _raise
