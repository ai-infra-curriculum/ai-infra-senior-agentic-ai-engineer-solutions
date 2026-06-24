"""Boundary types and protocols, carried forward from exercise-01.

Unchanged from the architecture-to-implementation exercise: this is the frozen
contract that exercise-02 wraps with operability (telemetry, health, policy).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

STATUS_OK = "ok"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: str
    payload: dict | None = None
    error: str | None = None


@runtime_checkable
class ToolExecutor(Protocol):
    def execute(self, call: ToolCall) -> ToolResult: ...


@runtime_checkable
class Transport(Protocol):
    def run(self, name: str, args: dict) -> dict: ...


@runtime_checkable
class Store(Protocol):
    def get(self, call_id: str) -> ToolResult | None: ...

    def put(self, call_id: str, result: ToolResult) -> None: ...
