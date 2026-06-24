"""Stretch goal: a caching decorator that wraps *any* ToolExecutor.

This proves the value of the protocol seam: caching is added without touching
``RealExecutor``. The decorator is itself a ``ToolExecutor`` and so remains
substitutable for the stub and the real executor.
"""

from __future__ import annotations

from .contract import STATUS_OK, ToolCall, ToolExecutor, ToolResult


class CachingExecutor:
    """Serve a previously-seen call from cache; delegate misses to the inner executor.

    Only successful results are cached — caching an error would pin a transient
    failure forever. The cache key is ``call.id``, matching the executor's own
    idempotency contract.
    """

    def __init__(self, inner: ToolExecutor) -> None:
        self._inner = inner
        self._cache: dict[str, ToolResult] = {}

    def execute(self, call: ToolCall) -> ToolResult:
        hit = self._cache.get(call.id)
        if hit is not None:
            return hit
        result = self._inner.execute(call)
        if result.status == STATUS_OK:
            self._cache[call.id] = result
        return result
