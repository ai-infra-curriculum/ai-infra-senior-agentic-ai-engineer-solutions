# mod-402-eval-observability-infra: Building Eval & Observability Infrastructure — Solutions

Reference solutions for the senior eval, tracing, and gate infrastructure exercises. Each
exercise folder holds an annotated, runnable walkthrough that maps directly to the
learning module's acceptance criteria.

## Exercises

- [exercise-01-reusable-eval-harness](exercise-01-reusable-eval-harness/README.md) — an
  agent-agnostic eval harness: one `Grader` protocol, three grader families
  (trajectory, tool-call, LLM-judge), a versioned JSONL dataset, and a JSON-serializable
  `EvalReport`. Runs offline; proves reusability across two agents with zero harness edits.
- [exercise-02-tracing-and-dashboards](exercise-02-tracing-and-dashboards/README.md) — a
  fleet tracing standard: a shared GenAI-conventions wrapper, per-service resource
  attributes, one export path, error-biased sampling, and fleet dashboards grouped by
  `service.name`. Runs offline against an in-memory exporter with a one-line OTLP swap.
- [exercise-03-regression-gates](exercise-03-regression-gates/README.md) — a CI deploy
  gate that turns the `EvalReport` + trace stats into a merge decision: four signals with
  absolute and regression thresholds, baseline discipline, GitHub Actions wiring, and an
  evidence-rich PR comment that blocks a regressing PR.

## Running the code

Each solution's `## Reference implementation` block is a complete file. Exercise 01 and 03
use only the Python standard library; exercise 02 needs
`pip install opentelemetry-api opentelemetry-sdk`. Every file ends with a runnable
`main`/demo and a `## Verification` section describing the expected output.
