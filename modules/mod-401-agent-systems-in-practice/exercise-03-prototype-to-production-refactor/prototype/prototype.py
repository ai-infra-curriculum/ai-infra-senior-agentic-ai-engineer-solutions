"""BEFORE: the single-file prototype, preserved unchanged for comparison.

Everything is fused: the API key is hard-coded, the model client is a global, the
prompt is inline, tool dispatch is an if/elif ladder, the loop, parsing, and
config all live here. It works — and it is nearly impossible to test, because the
loop is welded to a concrete model client and a literal secret.

The refactored, layered version lives in ../agent/. The characterization tests in
../agent/tests/test_characterization.py pin THIS file's behavior and stay green
through the refactor, proving observable behavior never changed.
"""

from __future__ import annotations

import json

# --- Hard-coded secret: a refactor blocker AND a security incident. ---
API_KEY = "sk-prototype-HARDCODED-do-not-ship"  # noqa: S105 - intentional smell

MODEL_NAME = "demo-model-v1"
MAX_STEPS = 4


class _DemoModelClient:
    """A stand-in 'LLM' so the prototype runs offline.

    It returns a scripted tool-call-or-answer based on the conversation, so the
    prototype is deterministic enough to demonstrate. In a real prototype this
    would be ``openai.OpenAI(api_key=API_KEY)`` — concrete and untestable.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key  # would authenticate a real client

    def complete(self, messages: list[dict]) -> str:
        last = messages[-1]["content"]
        # Naive scripted policy: ask for a tool, then answer from its result.
        if "weather in" in last.lower() and "observed:" not in last.lower():
            city = last.lower().split("weather in", 1)[1].strip(" ?.")
            return json.dumps({"tool": "get_weather", "args": {"city": city}})
        if "add" in last.lower() and "observed:" not in last.lower():
            nums = [int(s) for s in last.replace("+", " ").split() if s.isdigit()]
            return json.dumps({"tool": "add", "args": {"numbers": nums}})
        if "observed:" in last.lower():
            observed = last.split("observed:", 1)[1].strip()
            return json.dumps({"answer": f"Result: {observed}"})
        return json.dumps({"answer": "I don't know."})


# Module-global client: another reason the loop can't be tested in isolation.
_client = _DemoModelClient(API_KEY)


def _run_tool(name: str, args: dict) -> str:
    # Inline tool dispatch fused into the loop module.
    if name == "get_weather":
        return f"{args['city']}: 72F sunny"
    if name == "add":
        return str(sum(args["numbers"]))
    raise ValueError(f"unknown tool: {name}")


def run_agent(question: str) -> dict:
    """The fused reason-act loop. Returns the final answer + the trace of steps."""

    messages = [
        {"role": "system", "content": "You are a helpful agent."},
        {"role": "user", "content": question},
    ]
    trace: list[dict] = []

    for _ in range(MAX_STEPS):
        raw = _client.complete(messages)
        parsed = json.loads(raw)
        if "answer" in parsed:
            return {"answer": parsed["answer"], "trace": trace}
        name = parsed["tool"]
        args = parsed["args"]
        trace.append({"tool": name, "args": args})
        observation = _run_tool(name, args)
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"observed: {observation}"})

    return {"answer": "step limit reached", "trace": trace}


if __name__ == "__main__":  # pragma: no cover - manual demo
    print(run_agent("What is the weather in Phoenix?"))
    print(run_agent("Please add 2 + 3 + 4"))
