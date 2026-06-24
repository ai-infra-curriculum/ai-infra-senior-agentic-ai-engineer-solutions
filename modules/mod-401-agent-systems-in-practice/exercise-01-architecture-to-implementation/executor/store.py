"""In-process idempotency store.

The ADR (``adr/001-idempotency-store.md``) records *why* this is in-process for
now. It satisfies the ``Store`` protocol, so swapping in a Redis-backed store
later changes no executor code — only the wiring at the composition root.
"""

from __future__ import annotations

from .contract import ToolResult


class InMemoryStore:
    """A dict behind the ``Store`` protocol. Evaporates on restart by design."""

    def __init__(self) -> None:
        self._records: dict[str, ToolResult] = {}

    def get(self, call_id: str) -> ToolResult | None:
        return self._records.get(call_id)

    def put(self, call_id: str, result: ToolResult) -> None:
        # First write wins: a recorded id is immutable, matching the replay
        # semantics the executor relies on.
        self._records.setdefault(call_id, result)
