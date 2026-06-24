# mod-404-reliability-cost-incident/exercise-01 — Solution

## Approach

The brief asks for the *measurement and alerting layer* of an agent SLO: pick
quality SLIs, compute each as a `good / valid` ratio from traces, attach a
target plus error budget, and fire two complementary alerts (burn-rate and
baseline-drift). The reference implementation treats this as one small,
dependency-free library so it stays runnable in CI and matches the starter
`RunRecord` shape from the exercise.

Four design decisions drive the implementation:

- **Four indicators from the four families in Chapter 1.** Task success
  (judged subset), grounding/faithfulness, tool-call validity, and loop-health.
  Each catches a failure that a pure availability SLI — "returned non-error
  under a latency bound" — passes straight through.
- **`good / valid`, with the empty case made explicit.** A counting SLI over a
  window. The denominator (`valid`) is stated per SLI. A window with no valid
  events returns a sentinel (`None`) so the alerting layer decides what to do
  instead of reading a quiet hour as a false `100%` or paging on `NaN`.
- **Success rate over the judged subset, with a Wilson confidence interval.**
  We never judge every run, so the success SLI carries sampling error. We report
  the interval and size the sample so its half-width is tighter than the alert
  threshold; diluting with unlabeled runs would silently inflate the number.
- **Two alerts, not one threshold.** A multi-window burn-rate alert protects
  the error budget (fast burn pages, slow burn tickets). A baseline-drift alert
  compares the current window to a trailing baseline and fires on a significant
  drop *even while still above the absolute SLO* — the case a static threshold
  never catches.

## Reference implementation

Runnable on Python 3.11+ with no third-party dependencies. Save as
`agentic_slos.py` and run `python agentic_slos.py` for the worked demo, or
`python -m pytest` if you adapt the `_demo` asserts into tests.

```python
"""Quality-aware SLIs, error budgets, and drift alerting for an agent.

All SLIs are good/valid ratios. The empty window returns None (not 1.0 and not
NaN) so the alerting layer handles "no signal" explicitly. Pure stdlib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RunRecord:
    """One agent run. judged_success is None where the run was not sampled."""

    grounded_claims: int
    total_claims: int
    steps: int
    total_tokens: int
    tool_calls_valid: int
    tool_calls_total: int
    judged_success: bool | None  # None => unsampled


# --- SLIs: each returns good/valid, or None for an empty (no-valid) window ----


def grounding_sli(runs: list[RunRecord]) -> float | None:
    """Good = grounded claims. Valid = all claims made. Catches hallucination."""
    valid = sum(r.total_claims for r in runs)
    if valid == 0:
        return None  # no claims this window => no faithfulness signal
    good = sum(r.grounded_claims for r in runs)
    return good / valid


def tool_validity_sli(runs: list[RunRecord]) -> float | None:
    """Good = well-formed, appropriate tool calls. Valid = all tool calls."""
    valid = sum(r.tool_calls_total for r in runs)
    if valid == 0:
        return None
    good = sum(r.tool_calls_valid for r in runs)
    return good / valid


def loop_health_sli(runs: list[RunRecord], max_steps: int = 12) -> float | None:
    """Good = runs within the step budget. Valid = all runs. Precedes loops."""
    if not runs:
        return None
    good = sum(1 for r in runs if r.steps <= max_steps)
    return good / len(runs)


@dataclass(frozen=True)
class SuccessSLI:
    point: float | None  # good/valid over the judged subset, or None if empty
    n: int               # size of the judged subset (the valid denominator)
    ci_low: float
    ci_high: float

    @property
    def half_width(self) -> float:
        return (self.ci_high - self.ci_low) / 2 if self.point is not None else 1.0


def success_sli(runs: list[RunRecord], z: float = 1.96) -> SuccessSLI:
    """Task success over the JUDGED subset only, with a Wilson interval.

    Diluting with unlabeled runs would understate the failure rate, so we drop
    every record whose judged_success is None.
    """
    judged = [r for r in runs if r.judged_success is not None]
    n = len(judged)
    if n == 0:
        return SuccessSLI(point=None, n=0, ci_low=0.0, ci_high=1.0)
    good = sum(1 for r in judged if r.judged_success)
    p = good / n
    # Wilson score interval: well-behaved at small n and near 0/1.
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return SuccessSLI(point=p, n=n, ci_low=center - margin, ci_high=center + margin)


def required_judged_n(target_half_width: float, p_guess: float = 0.9,
                      z: float = 1.96) -> int:
    """Judged sample size so the success CI half-width <= target_half_width.

    Use this to make the interval tighter than your alert threshold before you
    trust the success SLI to gate a release.
    """
    if not 0 < target_half_width < 1:
        raise ValueError("target_half_width must be in (0, 1)")
    n = (z * z * p_guess * (1 - p_guess)) / (target_half_width * target_half_width)
    return math.ceil(n)


# --- Error budget + burn-rate -------------------------------------------------


@dataclass(frozen=True)
class SLO:
    name: str
    target: float       # e.g. 0.95
    window_days: float   # e.g. 28


def budget_consumed(sli_value: float | None, slo: SLO) -> float | None:
    """Fraction of the error budget already spent. None when no signal.

    allowed_bad = 1 - target. spent = observed_bad / allowed_bad, clamped >= 0.
    """
    if sli_value is None:
        return None
    allowed_bad = 1.0 - slo.target
    if allowed_bad <= 0:
        return 0.0 if sli_value >= 1.0 else float("inf")
    observed_bad = max(0.0, 1.0 - sli_value)
    return observed_bad / allowed_bad


def burn_rate(budget_fraction: float, window_fraction: float) -> float:
    """budget_fraction and window_fraction in [0, 1]. >1 burns too fast."""
    if window_fraction <= 0:
        return float("inf")
    return budget_fraction / window_fraction


@dataclass(frozen=True)
class BurnAlert:
    firing: bool
    severity: str  # "page" | "ticket" | "ok"
    rate: float


def evaluate_burn(short_consumed: float | None, short_window_frac: float,
                  long_consumed: float | None, long_window_frac: float,
                  *, page_at: float = 14.4, ticket_at: float = 1.0) -> BurnAlert:
    """Multi-window burn-rate (SRE workbook).

    Page on a fast burn that *also* shows in the short window (cuts false pages
    from a single spiky minute). Ticket on a sustained slow burn.
    """
    if short_consumed is None or long_consumed is None:
        return BurnAlert(firing=False, severity="ok", rate=0.0)
    short_rate = burn_rate(short_consumed, short_window_frac)
    long_rate = burn_rate(long_consumed, long_window_frac)
    if long_rate >= page_at and short_rate >= page_at:
        return BurnAlert(firing=True, severity="page", rate=long_rate)
    if long_rate >= ticket_at:
        return BurnAlert(firing=True, severity="ticket", rate=long_rate)
    return BurnAlert(firing=False, severity="ok", rate=long_rate)


# --- Baseline-drift -----------------------------------------------------------


@dataclass(frozen=True)
class DriftAlert:
    firing: bool
    current: float | None
    baseline: float | None
    drop: float  # baseline - current, in absolute SLI points


def evaluate_drift(current: float | None, baseline: float | None,
                   *, min_drop: float = 0.03) -> DriftAlert:
    """Fire when the current window drops a meaningful amount below baseline.

    Catches a regression that lands *above* the absolute SLO (e.g. 0.99 -> 0.95
    when the SLO is 0.90) — the burn-rate alert never sees it.
    """
    if current is None or baseline is None:
        return DriftAlert(firing=False, current=current, baseline=baseline, drop=0.0)
    drop = baseline - current
    return DriftAlert(firing=drop >= min_drop, current=current,
                      baseline=baseline, drop=drop)


# --- Worked demo --------------------------------------------------------------


def _demo() -> None:
    # A healthy baseline window.
    baseline = [
        RunRecord(grounded_claims=10, total_claims=10, steps=4, total_tokens=8_000,
                  tool_calls_valid=3, tool_calls_total=3, judged_success=True)
        for _ in range(200)
    ]
    grounding_baseline_window = [
        RunRecord(grounded_claims=99, total_claims=100, steps=4, total_tokens=8_000,
                  tool_calls_valid=3, tool_calls_total=3, judged_success=True)
        for _ in range(200)
    ]
    grounding_baseline = grounding_sli(grounding_baseline_window)
    assert grounding_sli(baseline) == 1.0
    assert grounding_baseline is not None and abs(grounding_baseline - 0.99) < 1e-9

    # Drift case A: grounding slides from a 0.99 baseline to 0.92 while the SLO
    # is 0.90. It is still above the absolute SLO and, over the full budget
    # window, consumes only 80% of the budget -> burn-rate stays quiet. But the
    # 7-point drop from baseline is a real regression -> baseline-drift fires.
    drifted = [
        RunRecord(grounded_claims=92, total_claims=100, steps=4, total_tokens=8_000,
                  tool_calls_valid=3, tool_calls_total=3, judged_success=True)
        for _ in range(200)
    ]
    slo = SLO(name="grounding", target=0.90, window_days=28)
    g_now = grounding_sli(drifted)
    assert g_now is not None and abs(g_now - 0.92) < 1e-9
    # Evaluate accumulated burn over the full budget window (fraction ~1.0).
    burn = evaluate_burn(
        short_consumed=budget_consumed(g_now, slo), short_window_frac=1.0,
        long_consumed=budget_consumed(g_now, slo), long_window_frac=1.0,
    )
    drift = evaluate_drift(g_now, grounding_baseline, min_drop=0.03)
    assert not burn.firing          # 0.8 budget over the full window -> no alert
    assert drift.firing             # 7 points below baseline -> fires
    print(f"[A] burn={burn.severity} drift_fires={drift.firing} drop={drift.drop:.3f}")

    # Drift case B: a sudden cliff below the SLO in the last hour. Burn-rate
    # pages now; baseline-drift, if the trailing baseline already absorbed a
    # slow slide, can lag. Burn catches the cliff.
    cliff = [
        RunRecord(grounded_claims=5, total_claims=10, steps=4, total_tokens=8_000,
                  tool_calls_valid=3, tool_calls_total=3, judged_success=True)
        for _ in range(200)
    ]
    g_cliff = grounding_sli(cliff)  # 0.50, far below 0.90
    hour_frac = (1 / 24) / slo.window_days  # one hour of a 28-day window
    burn_cliff = evaluate_burn(
        short_consumed=budget_consumed(g_cliff, slo), short_window_frac=hour_frac,
        long_consumed=budget_consumed(g_cliff, slo), long_window_frac=hour_frac,
    )
    assert burn_cliff.firing and burn_cliff.severity == "page"
    print(f"[B] burn={burn_cliff.severity} rate={burn_cliff.rate:.1f}")

    # Empty window: no false 100%, no page.
    assert grounding_sli([]) is None
    assert loop_health_sli([]) is None
    assert evaluate_burn(budget_consumed(None, slo), 1 / 24,
                         budget_consumed(None, slo), 1 / 24).firing is False
    print("[C] empty window: no signal, no page")

    # Success SLI on a judged subset with a reported interval + sizing.
    runs = [
        RunRecord(grounded_claims=1, total_claims=1, steps=3, total_tokens=5_000,
                  tool_calls_valid=1, tool_calls_total=1,
                  judged_success=(i % 10 != 0))  # ~90% success, every 10th fails
        for i in range(400)
    ]
    s = success_sli(runs)
    need = required_judged_n(target_half_width=0.03)
    assert s.point is not None
    print(f"[D] success={s.point:.3f} ci=[{s.ci_low:.3f},{s.ci_high:.3f}] "
          f"n={s.n} need_n(+/-0.03)={need}")


if __name__ == "__main__":
    _demo()
    print("OK")
```

The three indicators not shown as a single ratio in the starter — success,
tool-validity, loop-health — round out the four-family set; you can add a
fifth (cost-per-run) from exercise-02 with the same `good / valid` shape by
counting runs under a USD cap.

## Meeting the acceptance criteria

- **3–5 quality SLIs, each an explicit `good / valid` ratio, with an
  availability justification.** Four are implemented:
  - *Grounding* — good = grounded claims, valid = all claims. Availability
    misses a fast, well-formed, **hallucinated** answer; this counts the
    unsupported claims inside it.
  - *Tool-call validity* — good = well-formed and appropriate calls, valid =
    all calls. Availability misses a 200 response that emailed the wrong
    customer; this counts the bad call.
  - *Loop-health* — good = runs within the step budget, valid = all runs.
    Availability misses a run that returned, eventually, after 40 oscillating
    steps; this counts it as bad before it becomes an outage.
  - *Task success* — good = judged-successful runs, valid = the judged subset.
    Availability misses a confident wrong answer the user had to re-ask;
    the eval label catches it.
- **Success rate over the judged subset with a confidence interval, and every
  SLI handles the empty case.** `success_sli` drops `None` labels, returns a
  Wilson interval, and exposes `half_width`; `required_judged_n` sizes the
  sample so the interval beats the threshold. Every SLI returns `None` on an
  empty window — `_demo` case **[C]** asserts no page and no false 100%.
- **Target, window, and error budget per SLI, plus a release policy.** `SLO`
  carries target + window; `budget_consumed` computes the spent fraction.
  Release policy: while budget is healthy, ship freely; when a quality budget
  is exhausted (e.g. grounding budget spent over 28 days), **freeze
  prompt/model/tool changes and spend the next cycle on reliability** — the
  most common cause of a blown quality budget is a recent prompt or model
  change, so the gate sits exactly where the risk enters.
- **Burn-rate and baseline-drift alerts, each catching a case the other
  misses.** `_demo` case **[A]** is the drift-only case (grounding 0.99 → 0.92,
  still above the 0.90 SLO and only 80% of budget over the full window; burn
  stays quiet, drift fires on the 7-point drop). Case **[B]** is the burn-only
  case (a cliff to 0.50 in the last hour that burn-rate pages immediately,
  which a baseline that already absorbed a slow slide can lag).

## Common pitfalls

- **Diluting the success SLI with unlabeled runs.** Counting `None` labels as
  successes hides the failure rate. Compute success over the judged subset only
  and report the interval.
- **Letting an empty window read as 100%.** `good / total` with `total == 0`
  returning `1.0` silently masks an outage where no valid events flowed. Return
  a sentinel and make the alerting layer decide.
- **A single static threshold.** It fires late on a slow slide and never on a
  regression that lands above the SLO. You need burn-rate *and* baseline-drift.
- **Sizing the sample after picking the threshold.** If the success CI
  half-width is wider than your alert margin, the alert is noise. Size the
  judged sample (`required_judged_n`) first.
- **Treating the SLO as a dashboard, not a gate.** The payoff of the error
  budget is the release policy. If a blown budget doesn't stop a deploy, it is
  just decoration.

## Verification

```bash
cd modules/mod-404-reliability-cost-incident/exercise-01-agentic-slos
python agentic_slos.py
```

Expected: the script prints lines `[A]`–`[D]` and a final `OK`. `[A]` shows
the drift alert firing while burn stays quiet; `[B]` shows burn paging on the
cliff; `[C]` confirms an empty window neither pages nor reads 100%; `[D]`
prints the success point estimate, its Wilson interval, the judged `n`, and the
sample size needed for a ±0.03 interval. Every `assert` in `_demo` must pass for
the run to reach `OK`.
