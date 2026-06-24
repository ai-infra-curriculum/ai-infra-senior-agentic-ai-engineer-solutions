"""Pure parse / validate / shape functions (Task 4).

No I/O, no client, no config — just data in, data out. Pure functions are the
cheapest thing in the world to test, which is why parsing and shaping are pulled
out of the loop and into here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDecision:
    """The model's parsed intent: either a tool call or a final answer."""

    is_answer: bool
    answer: str | None = None
    tool: str | None = None
    args: dict | None = None


def parse_decision(raw: str) -> ModelDecision:
    """Parse a raw model string into a ModelDecision.

    Mirrors the prototype's ``json.loads`` + key check, but as a pure function
    with explicit validation instead of inline ``parsed["tool"]`` indexing.
    """

    data = json.loads(raw)
    if "answer" in data:
        return ModelDecision(is_answer=True, answer=str(data["answer"]))
    if "tool" in data and "args" in data:
        return ModelDecision(
            is_answer=False, tool=str(data["tool"]), args=dict(data["args"])
        )
    raise ValueError("model output has neither 'answer' nor 'tool'+'args'")


def shape_observation(observation: str) -> str:
    """Shape a tool observation into the user-message content the loop appends."""

    return f"observed: {observation}"


def initial_messages(question: str) -> list[dict]:
    """The opening conversation — identical to the prototype's seed messages."""

    return [
        {"role": "system", "content": "You are a helpful agent."},
        {"role": "user", "content": question},
    ]
