"""Scripted transport for simulating each failure mode deterministically."""

from __future__ import annotations

from collections.abc import Callable


class ScriptedTransport:
    """Runs one scripted behavior per invocation (return payload or raise)."""

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


def returns(value: object) -> Callable[[], dict]:
    """Return an arbitrary (possibly malformed, non-dict) value."""

    return lambda: value  # type: ignore[return-value]
