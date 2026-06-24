"""The executable form of the contract.

``StubExecutor`` does no real work but honors every boundary promise: it
returns the declared type, never raises, and keys its result on the call id.
Neighbor teams build against this on day one; the real executor must remain
substitutable for it.
"""

from __future__ import annotations

from .contract import STATUS_OK, ToolCall, ToolResult


class StubExecutor:
    """Honors the contract, does nothing real. Unblocks neighbors immediately."""

    def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(call_id=call.id, status=STATUS_OK, payload={"stub": True})
