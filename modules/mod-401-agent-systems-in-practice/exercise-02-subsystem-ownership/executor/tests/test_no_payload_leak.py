"""The boundary invariant: secrets in args/payloads never reach logs or metrics."""

from __future__ import annotations

import logging

from executor import (
    InMemoryStore,
    InstrumentedExecutor,
    ToolCall,
)
from executor.tests.fakes import ScriptedTransport, ok_payload, raises

SECRET = "sk-live-DO-NOT-LOG-1234567890"


def _run(caplog, transport: ScriptedTransport, call: ToolCall):
    executor = InstrumentedExecutor(transport, InMemoryStore(), sleep=lambda _s: None)
    with caplog.at_level(logging.INFO, logger="executor.boundary"):
        return executor.execute(call)


def test_secret_arg_never_appears_in_logs(caplog) -> None:
    transport = ScriptedTransport([ok_payload({"answer": SECRET})])
    call = ToolCall("c1", "lookup", {"api_key": SECRET, "q": SECRET})

    _run(caplog, transport, call)

    emitted = "\n".join(rec.getMessage() for rec in caplog.records)
    assert SECRET not in emitted
    # Shapes ARE logged: arg keys and the tool name, but not values.
    assert "api_key" in emitted
    assert "lookup" in emitted


def test_secret_in_error_message_never_appears_in_logs(caplog) -> None:
    # A tool that echoes a secret in its exception text must not leak it.
    transport = ScriptedTransport([raises(ValueError(SECRET))])
    call = ToolCall("c2", "tool", {"token": SECRET})

    result = _run(caplog, transport, call)

    emitted = "\n".join(rec.getMessage() for rec in caplog.records)
    assert SECRET not in emitted
    assert result.error == "ValueError"  # type name only, no message
