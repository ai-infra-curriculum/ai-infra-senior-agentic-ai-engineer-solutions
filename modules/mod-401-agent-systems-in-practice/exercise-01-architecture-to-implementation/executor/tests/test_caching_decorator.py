"""Stretch goal: the caching decorator is substitutable and never re-runs hits."""

from __future__ import annotations

from executor import (
    STATUS_OK,
    CachingExecutor,
    InMemoryStore,
    RealExecutor,
    ToolCall,
    ToolExecutor,
)
from executor.tests.fakes import ScriptedTransport, ok_payload


def test_caching_executor_satisfies_protocol() -> None:
    inner = RealExecutor(ScriptedTransport([ok_payload({"v": 1})]), InMemoryStore())
    assert isinstance(CachingExecutor(inner), ToolExecutor)


def test_cache_hit_does_not_touch_inner_executor() -> None:
    transport = ScriptedTransport([ok_payload({"v": 1})])
    inner = RealExecutor(transport, InMemoryStore())
    cached = CachingExecutor(inner)
    call = ToolCall("c1", "lookup", {})

    first = cached.execute(call)
    second = cached.execute(call)

    assert first == second
    assert first.status == STATUS_OK
    # Inner transport invoked exactly once; the second call was served from cache.
    assert len(transport.calls) == 1
