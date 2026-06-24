"""The reason-act loop, lifted into its own layer (Task 4).

Depends only on the I/O interfaces (`ModelClient`, `ToolTransport`) and the pure
domain functions — never on a concrete client or a literal secret. That is what
makes the loop testable: a scripted `FakeModel` drives it with no network, so we
can finally assert tool-call order and exercise a partial-failure path.

Observable behavior is identical to ``prototype.run_agent``; the characterization
tests prove it.
"""

from __future__ import annotations

from . import domain
from .clients import ModelClient, ToolTransport
from .config import AgentConfig


def run_agent(
    question: str,
    *,
    model: ModelClient,
    tools: ToolTransport,
    config: AgentConfig,
) -> dict:
    """Run the agent loop and return ``{"answer": str, "trace": list[dict]}``."""

    messages = domain.initial_messages(question)
    trace: list[dict] = []

    for _ in range(config.max_steps):
        raw = model.complete(messages)
        decision = domain.parse_decision(raw)

        if decision.is_answer:
            return {"answer": decision.answer, "trace": trace}

        trace.append({"tool": decision.tool, "args": decision.args})
        try:
            observation = tools.run(decision.tool, decision.args)
        except Exception as exc:  # noqa: BLE001 - surface tool failure into the loop
            # Partial-failure path: a tool error becomes an observation the model
            # can react to, rather than crashing the whole run. This path was
            # untestable in the prototype because the loop was welded to a live
            # client; now a FakeModel + a raising tool fake exercise it directly.
            observation = f"error: {type(exc).__name__}"

        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": domain.shape_observation(observation)}
        )

    return {"answer": "step limit reached", "trace": trace}
