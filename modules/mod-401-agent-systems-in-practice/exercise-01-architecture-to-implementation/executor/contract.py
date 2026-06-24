"""Frozen, typed contract for the tool-executor box.

This module *is* the architecture's contract expressed as code. Nothing here
depends on a transport, a store, retries, or a framework — those are internals
of the box and live elsewhere. Neighbors (planner, synthesizer) import only
from this file, which is why it must stay small and stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Status values the contract promises at the boundary. The executor never
# raises past its edge, so every outcome is one of these two strings.
STATUS_OK = "ok"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class ToolCall:
    """A request to run one registered tool.

    Frozen so a call cannot mutate after the planner emits it; ``id`` is the
    idempotency key the contract guarantees we dedupe on.
    """

    id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """The single shape every execution returns — success or failure.

    ``status`` is one of ``STATUS_OK`` / ``STATUS_ERROR``. On error, ``error``
    carries a short, payload-free reason; ``payload`` stays ``None``.
    """

    call_id: str
    status: str
    payload: dict | None = None
    error: str | None = None


@runtime_checkable
class ToolExecutor(Protocol):
    """The boundary the architecture fixes: one method, one return type.

    Marked ``runtime_checkable`` so tests can assert both the stub and the real
    executor satisfy the same protocol with ``isinstance``.
    """

    def execute(self, call: ToolCall) -> ToolResult: ...


@runtime_checkable
class Transport(Protocol):
    """How a tool actually runs. May raise; the executor traps it."""

    def run(self, name: str, args: dict) -> dict: ...


@runtime_checkable
class Store(Protocol):
    """Idempotency store: the durable record of a call_id's result."""

    def get(self, call_id: str) -> ToolResult | None: ...

    def put(self, call_id: str, result: ToolResult) -> None: ...
