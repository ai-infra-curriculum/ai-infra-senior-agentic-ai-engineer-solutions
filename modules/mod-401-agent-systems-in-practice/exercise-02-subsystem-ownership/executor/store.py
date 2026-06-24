"""In-process idempotency store with a reachability flag for health checks."""

from __future__ import annotations

from .contract import ToolResult


class InMemoryStore:
    """Dict-backed store. `reachable` lets tests simulate a store outage."""

    def __init__(self) -> None:
        self._records: dict[str, ToolResult] = {}
        self.reachable = True

    def get(self, call_id: str) -> ToolResult | None:
        if not self.reachable:
            raise ConnectionError("store unreachable")
        return self._records.get(call_id)

    def put(self, call_id: str, result: ToolResult) -> None:
        if not self.reachable:
            raise ConnectionError("store unreachable")
        self._records.setdefault(call_id, result)
