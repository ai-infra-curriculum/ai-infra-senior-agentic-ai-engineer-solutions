# mod-402-eval-observability-infra/exercise-03-regression-gates — Solution

## Approach

This exercise turns the exercise-01 `EvalReport` (and exercise-02 trace stats) into a
deploy gate that blocks a regression in CI. The harness already tells the truth; the gate
turns truth into a merge decision stable enough that teams won't disable it.

- **A signal is a scored answer to one question.** Four signals cover most agents:
  `answer_quality` (from the judge aggregate), `tool_correctness` (mean of the trajectory
  - tool-call aggregates), `cost`, and `latency` (both normalized from trace stats so
  *lower is better* maps to a `0.0–1.0` score where higher passes). Each has an absolute
  threshold.
- **Two ways to fail, both enforced.** The gate fails on an **absolute** breach (a signal
  below its threshold) *or* a **regression** (a signal dropping more than `max_drop` below
  the baseline, the last green run on `main`). The regression check is what actually
  protects the fleet, because it adapts as the agent improves.
- **Baseline discipline.** The baseline is a committed/artifact file of per-signal scores.
  It updates **only** on a green merge to `main` — never from a PR run, which would let a
  regressing PR quietly lower the bar.
- **Two suites, two cadences.** A fast smoke suite (tens of cases, no judge) runs on every
  push for quick feedback; the full suite (hundreds of cases, with judge) is the
  merge-blocking gate on PRs. A nightly full-fidelity run against `main` catches slow
  drift the per-PR gate can't afford to measure.
- **Report failures where the engineer is.** On block, the gate posts a PR comment naming
  the regressed signal, the score delta, and the newly-failing case ids — not a bare
  "eval failed" that trains people to retry until green.
- **Don't mistake a dataset edit for a regression.** When `dataset_version` changes, the
  baseline's scores are no longer comparable; the gate drops the regression check for that
  run and enforces absolute thresholds only, then a fresh baseline is taken on the next
  green merge.

The reference `gate.py` is self-contained and runs offline with the standard library; it
consumes JSON files an upstream harness/trace job produces, so it slots into any CI.

## Reference implementation

Save as `gate.py`. Run `python gate.py` for the built-in demo, or
`python gate.py <report.json> <baseline.json> <trace_stats.json> [newest_failing_ids...]`
in CI (exit code 0 pass / 1 fail).

```python
"""Regression gate: turn an EvalReport + trace stats into a merge decision.

Signals carry absolute thresholds and are checked against a baseline for regressions.
Self-contained (standard library only); consumes JSON produced by the harness (ex-01)
and tracing job (ex-02).
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass


@dataclass
class Signal:
    name: str
    score: float  # 0.0–1.0, higher is better
    threshold: float

    @property
    def passed(self) -> bool:
        return self.score >= self.threshold


# Budgets that normalize "lower is better" stats into a higher-is-better 0–1 score.
COST_BUDGET_USD = 0.05  # per-run cost that scores 0.0
LATENCY_BUDGET_MS = 4000.0  # p95 latency that scores 0.0


def _norm_cost(cost_usd: float) -> float:
    return max(0.0, min(1.0, 1.0 - cost_usd / COST_BUDGET_USD))


def _norm_latency(latency_ms: float) -> float:
    return max(0.0, min(1.0, 1.0 - latency_ms / LATENCY_BUDGET_MS))


def signals_from_report(report: dict, trace_stats: dict) -> list[Signal]:
    """Map harness aggregates + trace stats onto the four quality signals."""
    aggregates = report["aggregates"]
    answer_quality = aggregates.get("llm_judge", 0.0)
    # Tool correctness blends the two path-checking graders.
    tool_correctness = (
        aggregates.get("tool_call", 0.0) + aggregates.get("trajectory", 0.0)
    ) / 2.0
    return [
        Signal("answer_quality", answer_quality, 0.70),
        Signal("tool_correctness", tool_correctness, 0.90),
        Signal("cost", _norm_cost(trace_stats["cost_usd"]), 0.50),
        Signal("latency", _norm_latency(trace_stats["p95_latency_ms"]), 0.50),
    ]


def gate(
    current: list[Signal], baseline: dict[str, float], max_drop: float = 0.02
) -> tuple[bool, list[str]]:
    """Fail on an absolute breach OR a regression beyond max_drop vs. baseline."""
    failures: list[str] = []
    for s in current:
        if not s.passed:
            failures.append(f"{s.name} {s.score:.3f} < absolute threshold {s.threshold:.3f}")
        base = baseline.get(s.name)
        if base is not None:
            drop = base - s.score
            if drop > max_drop:
                failures.append(
                    f"{s.name} regressed {drop:.3f} (now {s.score:.3f}, "
                    f"baseline {base:.3f}, max_drop {max_drop:.3f})"
                )
    return (len(failures) == 0, failures)


def render_pr_comment(passed: bool, failures: list[str], newest_failing: list[str]) -> str:
    """Evidence-rich comment: name the signal, the delta, and the new failures."""
    if passed:
        return "Eval gate PASSED — no signal below threshold or baseline."
    lines = ["Eval gate FAILED. Regressed signals:", ""]
    lines += [f"- {f}" for f in failures]
    if newest_failing:
        lines += ["", "Newly-failing cases:"]
        lines += [f"  - `{cid}`" for cid in newest_failing]
    return "\n".join(lines)


def update_baseline_on_green(
    current: list[Signal], baseline_path: str, is_main_green_merge: bool
) -> bool:
    """Write a fresh baseline ONLY on a green merge to main. PR runs never overwrite."""
    if not is_main_green_merge:
        return False
    new_baseline = {s.name: round(s.score, 4) for s in current}
    with open(baseline_path, "w", encoding="utf-8") as fh:
        json.dump(new_baseline, fh, indent=2, sort_keys=True)
    return True


def run_gate_from_files(
    report_path: str,
    baseline_path: str,
    trace_stats_path: str,
    newest_failing: list[str],
    max_drop: float = 0.02,
) -> int:
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    with open(trace_stats_path, encoding="utf-8") as fh:
        trace_stats = json.load(fh)
    try:
        with open(baseline_path, encoding="utf-8") as fh:
            baseline = json.load(fh)
    except FileNotFoundError:
        baseline = {}

    current = signals_from_report(report, trace_stats)

    # A dataset edit changes the meaning of the scores: drop regression checks this run.
    baseline_version = baseline.get("__dataset_version__")
    if baseline_version is not None and baseline_version != report.get("dataset_version"):
        print("Dataset version changed; enforcing absolute thresholds only this run.")
        baseline = {}

    passed, failures = gate(current, baseline, max_drop=max_drop)
    print(render_pr_comment(passed, failures, newest_failing))
    print("\nSignals:")
    for s in current:
        print(f"  {json.dumps(asdict(s))} passed={s.passed}")
    return 0 if passed else 1  # non-zero blocks the merge


def _demo() -> None:
    good_report = {
        "dataset_version": "2026.06.1",
        "aggregates": {"llm_judge": 0.95, "tool_call": 1.0, "trajectory": 1.0},
    }
    regressed_report = {
        "dataset_version": "2026.06.1",
        "aggregates": {"llm_judge": 0.93, "tool_call": 0.40, "trajectory": 0.55},
    }
    trace_stats = {"cost_usd": 0.012, "p95_latency_ms": 1500.0}
    baseline = {
        "answer_quality": 0.95,
        "tool_correctness": 1.0,
        "cost": 0.76,
        "latency": 0.625,
    }

    print("=== BENIGN PR ===")
    ok, fails = gate(signals_from_report(good_report, trace_stats), baseline)
    print(render_pr_comment(ok, fails, []))
    assert ok, "benign PR should pass"

    print("\n=== REGRESSING PR (removed a required tool call) ===")
    cur = signals_from_report(regressed_report, trace_stats)
    ok, fails = gate(cur, baseline)
    print(render_pr_comment(ok, fails, ["c41", "c88", "c102"]))
    assert not ok, "regressing PR must be blocked"
    assert any("tool_correctness" in f for f in fails)

    print("\nGate proven: benign PR passes, regressing PR blocked with named signal.")


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        sys.exit(
            run_gate_from_files(
                sys.argv[1], sys.argv[2], sys.argv[3], newest_failing=sys.argv[4:]
            )
        )
    _demo()
```

### Wiring it into CI

A `.github/workflows/eval-gate.yml` runs the smoke suite on every push and the
merge-blocking full suite on PRs. The baseline is committed at `eval/baseline.json` and
refreshed only by the `main`-branch job.

```yaml
name: eval-gate

on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["main"]

jobs:
  smoke:
    # Fast feedback on every push: tens of cases, no judge.
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python eval/run_harness.py --suite smoke --out report.json
      - run: python eval/gate.py report.json eval/baseline.json trace_stats.json

  full-gate:
    # Merge-blocking on PRs: hundreds of cases, with judge.
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python eval/run_harness.py --suite full --judge on --out report.json
      - id: gate
        run: |
          python eval/gate.py report.json eval/baseline.json trace_stats.json \
            $(python eval/newest_failing.py report.json eval/baseline_cases.json) \
            | tee gate_comment.txt
        continue-on-error: true
      - if: steps.gate.outcome == 'failure'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const body = fs.readFileSync('gate_comment.txt', 'utf8');
            await github.rest.issues.createComment({
              owner: context.repo.owner, repo: context.repo.repo,
              issue_number: context.issue.number, body,
            });
            core.setFailed('Eval gate blocked this PR.');

  update-baseline:
    # Only on a green merge to main: refresh the baseline artifact.
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python eval/run_harness.py --suite full --judge on --out report.json
      - run: python eval/update_baseline.py report.json trace_stats.json eval/baseline.json
      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore(eval): refresh baseline from green main"
          file_pattern: eval/baseline.json
```

## Meeting the acceptance criteria

- **Signals derived from the report + trace stats, normalized with thresholds.**
  `signals_from_report` maps `llm_judge` → `answer_quality`, the trajectory/tool-call mean
  → `tool_correctness`, and trace `cost_usd` / `p95_latency_ms` → normalized `cost` /
  `latency`; each `Signal` carries a threshold.
- **Fails on absolute breach OR regression.** `gate` appends a failure when
  `not s.passed` and a separate failure when `base - s.score > max_drop`.
- **Baseline updates only on green merges to `main`.** `update_baseline_on_green` returns
  `False` unless `is_main_green_merge`; the CI `update-baseline` job runs only on
  `push` to `main`. PR runs read the baseline, never write it.
- **Smoke on every push, full suite blocking on PRs.** The `smoke` job runs no-judge on
  all pushes; the `full-gate` job runs with judge and is the merge-blocking PR job.
- **Regressing PR blocked with evidence; benign PR passes.** The demo and the
  `github-script` step post a comment naming the signal, the delta, and the newly-failing
  cases, and `core.setFailed` blocks the merge; the benign path exits 0 with no comment.

## Common pitfalls

- **Overwriting the baseline from a PR run.** A regressing PR that lowers the baseline
  disables the very check meant to catch it. Gate baseline writes behind a
  green-merge-to-`main` condition.
- **A `max_drop` below the noise floor.** If the band is tighter than the suite's
  run-to-run variance, the gate flakes and gets disabled. Measure variance over repeated
  runs and set `max_drop` above it (and run enough cases to shrink that variance).
- **Treating a dataset edit as a regression.** When `dataset_version` changes, baseline
  scores aren't comparable. Detect the version change, drop the regression check that run,
  and re-baseline on the next green merge.
- **Failing with "eval failed."** A bare non-zero exit trains engineers to retry until
  green. Always emit the signal, the delta, and the offending case ids.
- **Gating only on absolute thresholds.** Absolute-only is brittle: too high flakes good
  PRs, too low lets slow drift through. Pair it with the regression delta vs. baseline.

## Verification

```bash
python gate.py
```

Expected: the benign PR prints `Eval gate PASSED`; the regressing PR prints
`Eval gate FAILED` naming `tool_correctness` with both the absolute breach and the
regression delta, lists the newly-failing case ids, and the run ends with
`Gate proven: ...`. For the file-driven CI path, write a `report.json`, `baseline.json`,
and `trace_stats.json`, then run
`python gate.py report.json baseline.json trace_stats.json c41 c88` and confirm exit code
`1` on a regression (`echo $?`) and `0` on a clean report.

The `NOTES.md` reflection: choose `max_drop` from measured run-to-run variance (run the
full suite N times, take the standard deviation of each signal, set the band a few sigma
above it); when `dataset_version` changes, suppress the regression check and re-baseline
on the next green merge so an edit isn't read as a drop; for a one-time bypass, allow a
labeled override (e.g. `eval-override`) that still runs the gate and logs the bypass with
the actor and the failing signals — visible and auditable, never silent.
