"""The real executor: replay-check -> retry loop -> error-trap -> record.

Every seam the architecture left open is injected: the ``Transport`` (how a
tool runs), the retry/timeout policy, and the idempotency ``Store``. The class
itself holds no policy constants and opens no sockets, so it runs identically
against a real HTTP tool, an MCP server, or an in-process fake.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .contract import (
    STATUS_ERROR,
    STATUS_OK,
    Store,
    ToolCall,
    ToolResult,
    Transport,
)

# A transient error is one a retry might fix (a timeout, a 503). The default
# classifier treats TimeoutError as transient and everything else as hard;
# inject your own to match your transport's error taxonomy.
TransientClassifier = Callable[[Exception], bool]


def _default_is_transient(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError)


class RealExecutor:
    """Production tool-executor honoring the contract in ``contract.py``."""

    def __init__(
        self,
        transport: Transport,
        store: Store,
        max_retries: int = 2,
        backoff_base_s: float = 0.05,
        is_transient: TransientClassifier = _default_is_transient,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._store = store
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._is_transient = is_transient
        self._sleep = sleep  # injected so tests need not wait on real backoff

    def execute(self, call: ToolCall) -> ToolResult:
        # 1. Replay check: a recorded call_id short-circuits before any work,
        #    so the transport is never hit twice for the same id.
        recorded = self._store.get(call.id)
        if recorded is not None:
            return recorded

        # 2. Retry loop with bounded attempts and exponential backoff.
        # 3. Error trap: anything raised becomes status="error"; nothing escapes.
        result = self._run_with_retries(call)

        # 4. Record the outcome so future replays are idempotent.
        self._store.put(call.id, result)
        return result

    def _run_with_retries(self, call: ToolCall) -> ToolResult:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                payload = self._transport.run(call.name, call.args)
                return ToolResult(
                    call_id=call.id, status=STATUS_OK, payload=payload
                )
            except Exception as exc:  # noqa: BLE001 - boundary trap is intentional
                last_error = exc
                if attempt < self._max_retries and self._is_transient(exc):
                    self._sleep(self._backoff_base_s * (2**attempt))
                    continue
                break
        return ToolResult(
            call_id=call.id,
            status=STATUS_ERROR,
            error=_redact(last_error),
        )


def _redact(exc: Exception | None) -> str:
    """Surface the error *type*, not its message.

    Tool exceptions can echo argument values back in their text; the contract
    forbids leaking payloads, so we report the class name only.
    """

    if exc is None:
        return "unknown error"
    return type(exc).__name__
