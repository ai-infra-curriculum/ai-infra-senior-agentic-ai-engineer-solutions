# mod-402-eval-observability-infra/exercise-01-reusable-eval-harness — Solution

## Approach

The exercise is not "evaluate one agent well" — it is "build the asset a team adopts."
That reframing drives every design decision below:

- **One grader contract.** Every grader — trajectory, tool-call, LLM-judge — conforms
  to a single `Grader` protocol with a `name` attribute and a
  `grade(case, trajectory) -> GradeResult` method. The harness never special-cases a
  grader; it loops over a list and applies each uniformly. That uniformity is what lets
  scores aggregate and thresholds apply across grader families.
- **An agent-agnostic boundary.** The only thing an agent must provide is a callable
  `agent_fn(task) -> Trajectory`. The harness imports no agent class, knows no model
  provider, and adds a second agent by being pointed at a second `agent_fn` — zero
  harness edits. We prove this by running the identical harness, graders, and dataset
  against a "good" agent and a deliberately broken one.
- **Normalized scores.** Every `GradeResult.score` is in `[0.0, 1.0]`. Heterogeneous
  graders (an in-order-subset boolean, a precision/recall float, a rubric judgment)
  collapse onto one scale, so the report can average them and a gate
  (exercise-03) can threshold them.
- **Versioned datasets, structured reports.** Cases load from a JSONL file carrying a
  `dataset_version`; the `EvalReport` records that version so "the score dropped" is
  never ambiguous between an agent regression and a dataset edit. The report is the
  product — JSON-serializable, with per-case results and per-grader aggregates.
- **Fail soft, report hard.** A single case raising an exception records a failed case
  and the run continues. A harness that dies on case 3 of 200 is useless in CI, so the
  LLM-judge is wrapped to degrade to `passed=False` rather than propagate.

The reference implementation is self-contained and runs with no network access: the
LLM-judge accepts an injectable `judge_client`, and the demo passes a deterministic stub
so the file is runnable in CI without an API key. A note shows exactly where a real
Anthropic/OpenAI client slots in.

## Reference implementation

Save as `harness.py`. It runs end-to-end with `python harness.py` (Python 3.10+,
standard library only) and prints two reports plus a reusability assertion.

```python
"""Reusable, agent-agnostic eval harness.

One Grader protocol, three grader families, a versioned JSONL dataset, and a
JSON-serializable EvalReport. Runs offline: the LLM-judge takes an injectable
client, and the demo passes a deterministic stub.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Trajectory: the captured record of what an agent did. This is the agent-agnostic
# contract — any agent that can emit one of these can be graded.
# ---------------------------------------------------------------------------


@dataclass
class Step:
    """One step in an agent run. kind in {reason, tool_call, tool_result, answer}."""

    kind: str
    tool_name: str | None = None  # set when kind == "tool_call"
    content: str = ""  # final text when kind == "answer"


@dataclass
class Trajectory:
    """An ordered list of steps plus the final answer text."""

    steps: list[Step] = field(default_factory=list)

    @property
    def tool_calls(self) -> list[str]:
        return [s.tool_name for s in self.steps if s.kind == "tool_call" and s.tool_name]

    @property
    def final_answer(self) -> str:
        answers = [s.content for s in self.steps if s.kind == "answer"]
        return answers[-1] if answers else ""


# ---------------------------------------------------------------------------
# Core schemas
# ---------------------------------------------------------------------------


@dataclass
class GradeResult:
    name: str
    score: float  # normalized 0.0–1.0
    passed: bool
    detail: str = ""


@dataclass
class EvalCase:
    id: str
    task: str
    expected_tools: list[str] | None = None
    reference: str | None = None
    max_steps: int = 8
    metadata: dict | None = None


@runtime_checkable
class Grader(Protocol):
    """The whole design: every grader conforms to this one shape."""

    name: str

    def grade(self, case: EvalCase, trajectory: Trajectory) -> GradeResult: ...


@dataclass
class EvalReport:
    run_id: str
    dataset_version: str
    agent_label: str
    per_case: dict[str, list[dict]] = field(default_factory=dict)
    aggregates: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Grader family 1: trajectory (in-order subset + step budget)
# ---------------------------------------------------------------------------


def _is_in_order_subset(expected: list[str], actual: list[str]) -> bool:
    """True if every item in `expected` appears in `actual` in the same order."""
    it = iter(actual)
    return all(tool in it for tool in expected)


class TrajectoryGrader:
    """Required tools appear in order, and the run stays within its step budget.

    Reference-free when a case gives no expected_tools: only the budget is checked.
    """

    name = "trajectory"

    def grade(self, case: EvalCase, trajectory: Trajectory) -> GradeResult:
        n_steps = len(trajectory.steps)
        within_budget = n_steps <= case.max_steps

        if not case.expected_tools:
            score = 1.0 if within_budget else 0.0
            return GradeResult(
                self.name,
                score,
                within_budget,
                f"reference-free: {n_steps} steps (budget {case.max_steps})",
            )

        order_ok = _is_in_order_subset(case.expected_tools, trajectory.tool_calls)
        passed = order_ok and within_budget
        # Two equally weighted sub-checks so the score is informative, not just 0/1.
        score = 0.5 * float(order_ok) + 0.5 * float(within_budget)
        return GradeResult(
            self.name,
            score,
            passed,
            f"order_ok={order_ok}, within_budget={within_budget} "
            f"({n_steps}/{case.max_steps} steps)",
        )


# ---------------------------------------------------------------------------
# Grader family 2: tool-call (precision/recall over the tool set)
# ---------------------------------------------------------------------------


class ToolCallGrader:
    """F1 over the set of tools used vs. the set expected.

    Precision penalizes extra tools; recall penalizes missing ones. The harmonic
    mean (F1) normalizes both into a single 0.0–1.0 score.
    """

    name = "tool_call"

    def grade(self, case: EvalCase, trajectory: Trajectory) -> GradeResult:
        if not case.expected_tools:
            return GradeResult(self.name, 1.0, True, "no expected_tools; trivially satisfied")

        used = set(trajectory.tool_calls)
        expected = set(case.expected_tools)
        true_pos = len(used & expected)

        precision = true_pos / len(used) if used else 0.0
        recall = true_pos / len(expected) if expected else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

        passed = f1 >= 0.99  # exact set match within float tolerance
        return GradeResult(
            self.name,
            f1,
            passed,
            f"precision={precision:.2f} recall={recall:.2f} f1={f1:.2f}; "
            f"used={sorted(used)} expected={sorted(expected)}",
        )


# ---------------------------------------------------------------------------
# Grader family 3: LLM-judge (rubric score; fails soft on judge error)
# ---------------------------------------------------------------------------


class JudgeClient(Protocol):
    """The minimal judge surface. A real Anthropic/OpenAI client adapts to this."""

    def score(self, prompt: str) -> dict: ...


class LLMJudgeGrader:
    """Score the final answer against a faithfulness + no-hallucinated-citation rubric.

    The judge model and temperature are pinned and recorded in the detail so the run is
    reproducible. A judge failure degrades to passed=False with a detail — never an
    exception that sinks the run.
    """

    name = "llm_judge"

    def __init__(self, client: JudgeClient, model: str = "judge-v1", temperature: float = 0.0):
        self.client = client
        self.model = model
        self.temperature = temperature

    def grade(self, case: EvalCase, trajectory: Trajectory) -> GradeResult:
        answer = trajectory.final_answer
        prompt = (
            "Rubric: rate faithfulness to the reference and absence of hallucinated "
            "citations, 0.0–1.0.\n"
            f"model={self.model} temperature={self.temperature}\n"
            f"REFERENCE: {case.reference or '(none)'}\n"
            f"ANSWER: {answer}\n"
        )
        try:
            result = self.client.score(prompt)
            raw = float(result["score"])
            score = max(0.0, min(1.0, raw))  # clamp into range
            passed = score >= 0.7
            detail = (
                f"judge={self.model}@{self.temperature} score={score:.2f} "
                f"reason={result.get('reason', '')}"
            )
            return GradeResult(self.name, score, passed, detail)
        except Exception as exc:  # fail soft: a flaky judge must not crash the run
            return GradeResult(
                self.name,
                0.0,
                False,
                f"judge call failed ({type(exc).__name__}: {exc}); scored 0.0",
            )


# ---------------------------------------------------------------------------
# Versioned dataset loading
# ---------------------------------------------------------------------------


def load_cases(path: str) -> tuple[list[EvalCase], str]:
    """Load a JSONL dataset. The first line is a header carrying dataset_version;
    every subsequent line is one EvalCase. Returns (cases, dataset_version).
    """
    cases: list[EvalCase] = []
    version = "unknown"
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if lineno == 0 and "dataset_version" in record:
                version = record["dataset_version"]
                continue
            cases.append(EvalCase(**record))
    return cases, version


# ---------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------

AgentFn = Callable[[str], Awaitable[Trajectory]]


class Harness:
    def __init__(self, graders: list[Grader]):
        self.graders = graders

    async def run(
        self,
        agent_fn: AgentFn,
        cases: list[EvalCase],
        dataset_version: str,
        agent_label: str = "agent",
    ) -> EvalReport:
        report = EvalReport(
            run_id=str(uuid.uuid4()),
            dataset_version=dataset_version,
            agent_label=agent_label,
        )
        per_grader_scores: dict[str, list[float]] = {g.name: [] for g in self.graders}

        for case in cases:
            try:
                trajectory = await agent_fn(case.task)
            except Exception as exc:  # fail soft at the agent boundary
                report.errors[case.id] = f"{type(exc).__name__}: {exc}"
                report.per_case[case.id] = [
                    asdict(GradeResult(g.name, 0.0, False, "agent_fn raised"))
                    for g in self.graders
                ]
                for name in per_grader_scores:
                    per_grader_scores[name].append(0.0)
                continue

            results: list[GradeResult] = []
            for grader in self.graders:
                try:
                    result = grader.grade(case, trajectory)
                except Exception as exc:  # a buggy grader also fails soft
                    result = GradeResult(grader.name, 0.0, False, f"grader raised: {exc}")
                results.append(result)
                per_grader_scores[grader.name].append(result.score)

            report.per_case[case.id] = [asdict(r) for r in results]

        report.aggregates = {
            name: round(statistics.mean(scores), 4) if scores else 0.0
            for name, scores in per_grader_scores.items()
        }
        return report


# ---------------------------------------------------------------------------
# Demo: prove reusability against two different agents, zero harness changes
# ---------------------------------------------------------------------------


class StubJudge:
    """Deterministic judge stub. Returns high score unless the answer says 'wrong'."""

    def score(self, prompt: str) -> dict:
        is_bad = "ANSWER: wrong" in prompt or "ANSWER: \n" in prompt
        return {"score": 0.2 if is_bad else 0.95, "reason": "stub heuristic"}


def _good_agent_factory() -> AgentFn:
    async def good_agent(task: str) -> Trajectory:
        return Trajectory(
            steps=[
                Step("reason"),
                Step("tool_call", tool_name="search"),
                Step("tool_call", tool_name="fetch"),
                Step("answer", content="Paris is the capital of France."),
            ]
        )

    return good_agent


def _broken_agent_factory() -> AgentFn:
    async def broken_agent(task: str) -> Trajectory:
        # Skips the required 'fetch' tool and returns a bad answer.
        return Trajectory(
            steps=[
                Step("reason"),
                Step("tool_call", tool_name="search"),
                Step("answer", content="wrong"),
            ]
        )

    return broken_agent


def _write_demo_dataset() -> str:
    path = Path(tempfile.gettempdir()) / "eval_dataset.jsonl"
    rows = [
        {"dataset_version": "2026.06.1"},
        {"id": "c1", "task": "capital of France?", "expected_tools": ["search", "fetch"],
         "reference": "Paris", "max_steps": 6},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(path)


async def _main() -> None:
    dataset_path = _write_demo_dataset()
    cases, version = load_cases(dataset_path)

    graders: list[Grader] = [
        TrajectoryGrader(),
        ToolCallGrader(),
        LLMJudgeGrader(StubJudge()),
    ]
    harness = Harness(graders)

    good_report = await harness.run(_good_agent_factory(), cases, version, "good_agent")
    broken_report = await harness.run(_broken_agent_factory(), cases, version, "broken_agent")

    print("=== GOOD AGENT ===")
    print(good_report.to_json())
    print("\n=== BROKEN AGENT ===")
    print(broken_report.to_json())

    # Reusability assertion: identical harness, graders, and dataset; reports differ.
    assert good_report.dataset_version == broken_report.dataset_version == "2026.06.1"
    assert good_report.aggregates["tool_call"] > broken_report.aggregates["tool_call"]
    assert good_report.aggregates["llm_judge"] > broken_report.aggregates["llm_judge"]
    print("\nReusability proven: same harness, two agents, zero harness edits.")


if __name__ == "__main__":
    asyncio.run(_main())
```

To use a real judge, implement `JudgeClient.score` against your provider. For Anthropic,
the adapter wraps a Messages call and parses the model's JSON reply:

```python
class AnthropicJudge:
    """Adapter from the Anthropic SDK to the JudgeClient protocol."""

    def __init__(self, anthropic_client, model: str = "claude-sonnet-4-5"):
        self._client = anthropic_client
        self._model = model

    def score(self, prompt: str) -> dict:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            temperature=0.0,  # pinned for reproducibility
            messages=[{"role": "user", "content": prompt + "\nReply only JSON: "
                       '{"score": <0..1>, "reason": "<text>"}'}],
        )
        return json.loads(message.content[0].text)
```

## Meeting the acceptance criteria

- **Every grader conforms to one protocol; harness applies uniformly.** All three grader
  classes implement `name` + `grade(case, trajectory)`. `Harness.run` loops over
  `self.graders` with no type checks. `@runtime_checkable` lets `isinstance(g, Grader)`
  confirm conformance.
- **Three families, normalized 0.0–1.0.** `TrajectoryGrader` (in-order subset + budget),
  `ToolCallGrader` (F1), and `LLMJudgeGrader` (clamped rubric score) all return scores in
  range; the judge clamps with `max(0.0, min(1.0, raw))`.
- **Versioned dataset, recorded in the report.** `load_cases` reads JSONL with a header
  line carrying `dataset_version`; `EvalReport.dataset_version` records it.
- **JSON-serializable report with per-case + per-grader aggregates.** `EvalReport.to_json`
  serializes `per_case` (case_id → list of `GradeResult` dicts) and `aggregates`
  (grader_name → mean score).
- **One raising case does not crash the run.** The `agent_fn` call and each
  `grader.grade` call are wrapped; a failure records a failed case in `errors` /
  `per_case` and the loop continues.
- **Same harness, two agents, zero changes.** The demo runs `harness.run` against
  `good_agent` and `broken_agent` and asserts the `tool_call` and `llm_judge` aggregates
  differ — with no edit to `Harness`, the graders, or the dataset.

## Common pitfalls

- **Leaking the agent type into the harness.** The moment the harness imports an agent
  class or branches on provider, the agent-agnostic boundary is gone. Keep the contract
  at `agent_fn(task) -> Trajectory` and nothing more.
- **Un-normalized scores.** A grader that returns raw token counts or unbounded sums
  cannot be averaged with a 0–1 judge score. Normalize *inside* the grader, not in the
  aggregator.
- **Letting the judge crash the run.** An unhandled exception from a flaky judge call
  takes down a 200-case run. Wrap it and degrade to `passed=False`; CI needs a report
  even on a bad night.
- **Hard-coding cases in the test.** Cases baked into Python make "the score dropped"
  unattributable. Externalize to a versioned JSONL file and record the version in the
  report.
- **Special-casing one grader in the runner.** If the harness has an
  `if grader.name == "llm_judge"` branch, you have lost uniformity and the next grader
  family needs a harness edit. Push all per-grader logic into the grader.

## Verification

```bash
python harness.py
```

Expected: two JSON `EvalReport`s print. The good agent shows `tool_call` and `llm_judge`
aggregates near `1.0` / `0.95`; the broken agent shows lower (`~0.0` tool_call from the
missing `fetch`, `0.2` judge from the bad answer). The final line confirms
`Reusability proven: same harness, two agents, zero harness edits.` Add a fail-soft check
by inserting a case whose `agent_fn` raises and confirm the run still completes with that
case recorded in `errors`.

The reflection answers live in a `NOTES.md` alongside the harness; key points: draw the
boundary at `agent_fn -> Trajectory` (a team adding a field to `Trajectory` everyone
reads is fine, but a team needing the harness to *call their agent differently* breaks
it — that belongs behind their `agent_fn`); pin the judge model + temperature and measure
run-to-run variance over N repeats before trusting it in a gate; a step budget that two
teams disagree on belongs in per-case config (`max_steps`), not hard-coded in the harness.
