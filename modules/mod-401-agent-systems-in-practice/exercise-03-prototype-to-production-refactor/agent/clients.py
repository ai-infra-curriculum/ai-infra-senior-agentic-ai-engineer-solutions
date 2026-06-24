"""I/O interfaces and real adapters (Task 3).

The loop depends on these interfaces, never on a concrete client — so a
``FakeModel`` plugs in for tests and the loop runs with no network. The real
adapters wrap the same scripted demo model the prototype used, preserving
behavior exactly.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from .config import AgentConfig


@runtime_checkable
class ModelClient(Protocol):
    """One method: turn a message list into a raw model string."""

    def complete(self, messages: list[dict]) -> str: ...


@runtime_checkable
class ToolTransport(Protocol):
    """Run a named tool with args, return a string observation. May raise."""

    def run(self, name: str, args: dict) -> str: ...


class DemoModelAdapter:
    """Real ModelClient adapter wrapping the prototype's scripted demo model.

    Behavior is identical to the prototype's ``_DemoModelClient`` so
    characterization tests stay green. A production adapter would call the
    provider SDK here using ``config.api_key`` / ``config.model_name``.
    """

    def __init__(self, config: AgentConfig) -> None:
        self._config = config  # carries key + model name for a real SDK call

    def complete(self, messages: list[dict]) -> str:
        last = messages[-1]["content"]
        if "weather in" in last.lower() and "observed:" not in last.lower():
            city = last.lower().split("weather in", 1)[1].strip(" ?.")
            return json.dumps({"tool": "get_weather", "args": {"city": city}})
        if "add" in last.lower() and "observed:" not in last.lower():
            nums = [int(s) for s in last.replace("+", " ").split() if s.isdigit()]
            return json.dumps({"tool": "add", "args": {"numbers": nums}})
        if "observed:" in last.lower():
            observed = last.split("observed:", 1)[1].strip()
            return json.dumps({"answer": f"Result: {observed}"})
        return json.dumps({"answer": "I don't know."})


class LocalToolTransport:
    """Real ToolTransport adapter: the same two tools the prototype dispatched."""

    def run(self, name: str, args: dict) -> str:
        if name == "get_weather":
            return f"{args['city']}: 72F sunny"
        if name == "add":
            return str(sum(args["numbers"]))
        raise ValueError(f"unknown tool: {name}")
