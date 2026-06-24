"""Substitutability: stub and real executor both satisfy the protocol.

If these pass, every neighbor that built against the stub can swap in the real
executor without a code change — the whole point of the frozen interface.
"""

from __future__ import annotations

from executor import (
    InMemoryStore,
    RealExecutor,
    StubExecutor,
    ToolExecutor,
)
from executor.tests.fakes import ScriptedTransport, ok_payload


def test_stub_satisfies_protocol() -> None:
    assert isinstance(StubExecutor(), ToolExecutor)


def test_real_executor_satisfies_protocol() -> None:
    real = RealExecutor(
        transport=ScriptedTransport([ok_payload({"x": 1})]),
        store=InMemoryStore(),
    )
    assert isinstance(real, ToolExecutor)
