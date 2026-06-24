"""New tests the prototype could not support (Task 4): tool order + partial failure.

These exercise the loop directly via a scripted FakeModel — impossible before the
refactor, when the loop was welded to a live client.
"""

from __future__ import annotations

from agent import AgentConfig
from agent import run_agent
from agent.tests.fakes import (
    RaisingTools,
    RecordingTools,
    ScriptedModel,
    answer,
    tool_call,
)


def _config(max_steps: int = 4) -> AgentConfig:
    return AgentConfig.from_env(
        {"AGENT_API_KEY": "test-key", "AGENT_MAX_STEPS": str(max_steps)}
    )


def test_tool_call_order_is_exactly_as_scripted() -> None:
    model = ScriptedModel(
        [
            tool_call("get_weather", {"city": "phoenix"}),
            tool_call("add", {"numbers": [1, 2]}),
            answer("done"),
        ]
    )
    tools = RecordingTools(observation="obs")

    result = run_agent("go", model=model, tools=tools, config=_config())

    assert result["answer"] == "done"
    assert [name for name, _ in tools.calls] == ["get_weather", "add"]
    assert result["trace"] == [
        {"tool": "get_weather", "args": {"city": "phoenix"}},
        {"tool": "add", "args": {"numbers": [1, 2]}},
    ]


def test_partial_failure_path_is_handled_not_crashed() -> None:
    # A tool errors mid-run; the loop turns it into an observation and continues,
    # then the model answers. The whole run does not raise.
    model = ScriptedModel(
        [tool_call("flaky", {}), answer("recovered")]
    )
    tools = RaisingTools(ValueError("boom"))

    result = run_agent("go", model=model, tools=tools, config=_config())

    assert result["answer"] == "recovered"
    assert tools.calls == [("flaky", {})]  # the failing tool was attempted once


def test_step_limit_is_respected() -> None:
    # Model never answers; the loop must stop at max_steps, not run forever.
    model = ScriptedModel([tool_call("get_weather", {"city": "x"})] * 10)
    tools = RecordingTools()

    result = run_agent("go", model=model, tools=tools, config=_config(max_steps=3))

    assert result["answer"] == "step limit reached"
    assert len(tools.calls) == 3
