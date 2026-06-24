# mod-403-multi-agent-at-scale/exercise-03 (Token And Latency Budgets) — Solution

## Approach

The exercise asks us to put real numbers on what a multi-agent run costs and how
long it takes, then enforce a budget you can defend with measurements. The
reference instruments a single orchestrator → workers → synthesizer run,
emitting per-role tokens, dollars, and **critical-path** latency; sets explicit
cost and latency budgets; routes by difficulty; caches shared context; and wires
a soft cap and a hard cap. The model call is stubbed to return a usage object
with plausible token counts and latency, so the budgeting logic is fully
testable offline (no provider, no spend).

Design choices:

1. **Per-role instrumentation, not per-call.** Every `call_model` emits a
   `Usage` record tagged with the `role` (`orchestrator`, `worker`,
   `synthesizer`) and the model used. A `RunLedger` aggregates by role so the
   final report answers "which role dominated cost?" and "which dominated
   latency?" directly.
2. **Critical-path latency ≠ sum of latencies.** Workers run in parallel, so the
   user waits for `orchestrator + max(worker) + synthesizer`, not the sum. The
   ledger records each step's wall-clock latency *and* reconstructs the critical
   path from the dependency structure (decompose → parallel workers → synthesize).
3. **Dollars priced from a rate card.** Input and output tokens are priced
   separately per model (`IN_PRICE` / `OUT_PRICE`), exactly as providers bill.
4. **Routing by difficulty.** `route(step)` sends easy steps (decomposition,
   classification, easy workers) to the `small` model and reserves `large` for
   genuinely hard reasoning. We run the same task set with routing off and on and
   report the delta against *both* budgets — including the latency cost when the
   cheap model needs an extra turn.
5. **Context caching.** A long shared system prompt and a shared corpus are read
   by every worker. A `ContextCache` charges the shared input tokens *once* (a
   cache write) and lets subsequent reads hit the cache at a steep discount,
   modelling provider prompt caching. Identical sub-queries are memoized so two
   workers don't pay twice.
6. **Soft and hard caps.** `RunBudget` tracks spend and elapsed time. The soft
   cap (`max_usd` / `max_latency_s`) stops fan-out and synthesizes from what we
   have; the hard cap (`hard_usd`) aborts the run with a partial result — the
   defense against a decomposition bug spawning 200 workers.

## Reference implementation

```python
"""Token + latency budgeting and enforcement for a multi-agent run.

Stubbed model calls return plausible usage + latency so the budgeting logic is
fully testable offline. Stdlib only. Python 3.11+. Run: python3 exercise_03.py
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field

# --- Rate card ($/token), input and output priced separately ----------------

IN_PRICE = {"small": 0.20 / 1_000_000, "large": 3.00 / 1_000_000}
OUT_PRICE = {"small": 0.80 / 1_000_000, "large": 15.0 / 1_000_000}

# Provider prompt-cache discount: cached input tokens cost a fraction of fresh.
CACHE_READ_DISCOUNT = 0.1

# Budgets for this task type.
MAX_USD = 0.08            # soft cost cap, p95 target
MAX_LATENCY_S = 8.0       # soft latency cap, p95 target
HARD_USD = 0.20           # hard abort ceiling (> soft)

FANOUT_WAVE = 5           # workers dispatched per fan-out wave

# Latency budget split across the critical path -> per-hop timeouts.
ORCH_SLICE_S = 1.0
WORKER_SLICE_S = 5.0
SYNTH_SLICE_S = 2.0
assert ORCH_SLICE_S + WORKER_SLICE_S + SYNTH_SLICE_S <= MAX_LATENCY_S


class BudgetExceeded(Exception):
    """Raised when the hard cap is blown; the run aborts with a partial result."""


@dataclass
class Usage:
    role: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float

    @property
    def usd(self) -> float:
        return (self.input_tokens * IN_PRICE[self.model]
                + self.output_tokens * OUT_PRICE[self.model])


# --- Per-role ledger --------------------------------------------------------


@dataclass
class RunLedger:
    """Aggregates usage by role and reconstructs critical-path latency."""

    records: list[Usage] = field(default_factory=list)

    def record(self, u: Usage) -> None:
        self.records.append(u)

    def by_role(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for u in self.records:
            r = out.setdefault(u.role, {"in": 0, "out": 0, "usd": 0.0,
                                        "latency_s": 0.0, "calls": 0})
            r["in"] += u.input_tokens
            r["out"] += u.output_tokens
            r["usd"] += u.usd
            r["latency_s"] += u.latency_s
            r["calls"] += 1
        return out

    @property
    def total_usd(self) -> float:
        return sum(u.usd for u in self.records)

    def critical_path_s(self) -> float:
        """orchestrator + slowest worker + synthesizer (workers run parallel)."""
        orch = sum(u.latency_s for u in self.records if u.role == "orchestrator")
        synth = sum(u.latency_s for u in self.records if u.role == "synthesizer")
        worker_lat = [u.latency_s for u in self.records if u.role == "worker"]
        return orch + (max(worker_lat) if worker_lat else 0.0) + synth


# --- Budget enforcement -----------------------------------------------------


@dataclass
class RunBudget:
    max_usd: float
    max_latency_s: float
    hard_usd: float
    spent_usd: float = 0.0
    elapsed_s: float = 0.0          # accumulated critical-path time (sim clock)

    def charge(self, u: Usage) -> None:
        self.spent_usd += u.usd

    def soft_exceeded(self) -> bool:
        return self.spent_usd > self.max_usd or self.elapsed_s > self.max_latency_s

    def hard_exceeded(self) -> bool:
        return self.spent_usd > self.hard_usd


# --- Shared-context cache ----------------------------------------------------


@dataclass
class ContextCache:
    """Charges shared input tokens once; later reads hit at a discount.

    Also memoizes identical sub-queries so two workers don't pay twice.
    """

    _written: set[str] = field(default_factory=set)
    _subquery: dict[str, Usage] = field(default_factory=dict)

    def input_tokens_for(self, key: str, raw_tokens: int) -> int:
        """Billable input tokens for shared context `key`."""
        if key in self._written:
            return int(raw_tokens * CACHE_READ_DISCOUNT)   # cache read
        self._written.add(key)
        return raw_tokens                                  # cache write (full)

    def memoized(self, key: str) -> Usage | None:
        return self._subquery.get(key)

    def memoize(self, key: str, u: Usage) -> None:
        self._subquery[key] = u


# --- The stubbed model call -------------------------------------------------


async def call_model(rng: random.Random, *, role: str, model: str,
                     in_tok: int, out_tok: int) -> Usage:
    """Deterministic stub: latency scales with model and output length."""
    base = 0.4 if model == "small" else 1.2
    latency = base + out_tok / 800.0 + rng.uniform(0, 0.2)
    await asyncio.sleep(0)                  # keep it async without real waiting
    return Usage(role, model, in_tok, out_tok, latency)


# --- The agents -------------------------------------------------------------


@dataclass
class Step:
    step_id: str
    is_hard: bool
    out_tok: int


def route(step: Step, *, enabled: bool) -> str:
    if not enabled:
        return "large"                     # naive baseline: everything big
    return "large" if step.is_hard else "small"


SHARED_PROMPT_TOKENS = 4000               # long system prompt every worker reads
SHARED_CORPUS_TOKENS = 6000               # corpus several workers read
WORKER_PRIVATE_TOKENS = 300               # the worker's own unique input


async def run_pipeline(rng: random.Random, steps: list[Step], *,
                       routing: bool, caching: bool,
                       budget: RunBudget | None = None) -> dict:
    """Orchestrate -> parallel workers -> synthesize, with optional controls."""
    ledger = RunLedger()
    cache = ContextCache()

    # 1. Orchestrator decomposes the task (an easy step).
    decomp_model = route(Step("decompose", is_hard=False, out_tok=200),
                         enabled=routing)
    u = await call_model(rng, role="orchestrator", model=decomp_model,
                         in_tok=800, out_tok=200)
    ledger.record(u)
    if budget:
        budget.charge(u)
        budget.elapsed_s += u.latency_s

    # 2. Workers run in parallel; each reads shared context + its own input.
    # Fan out in waves. The soft cap stops launching NEW waves (graceful); the
    # hard cap aborts mid-wave (the backstop when a single buggy decomposition
    # dispatches a huge batch the soft cap can't gracefully unwind).
    results = []
    for wave_start in range(0, len(steps), FANOUT_WAVE):
        if budget and budget.soft_exceeded():
            break                          # soft cap: stop fanning out new waves

        wave = steps[wave_start:wave_start + FANOUT_WAVE]
        for step in wave:
            model = route(step, enabled=routing)

            # Shared context billing: full once, discounted thereafter.
            if caching:
                prompt_in = cache.input_tokens_for(
                    "system_prompt", SHARED_PROMPT_TOKENS)
                corpus_in = cache.input_tokens_for("corpus", SHARED_CORPUS_TOKENS)
            else:
                prompt_in = SHARED_PROMPT_TOKENS
                corpus_in = SHARED_CORPUS_TOKENS
            in_tok = prompt_in + corpus_in + WORKER_PRIVATE_TOKENS

            out_tok = step.out_tok
            # A cheap model on a hard step needs a second turn (latency + cost).
            extra_turn = routing and step.is_hard is False and step.out_tok > 400
            u = await call_model(rng, role="worker", model=model,
                                 in_tok=in_tok, out_tok=out_tok)
            if extra_turn:
                u2 = await call_model(rng, role="worker", model=model,
                                      in_tok=in_tok // 2, out_tok=out_tok // 2)
                u = Usage(u.role, u.model, u.input_tokens + u2.input_tokens,
                          u.output_tokens + u2.output_tokens,
                          u.latency_s + u2.latency_s)

            ledger.record(u)
            results.append({"step_id": step.step_id, "model": model})
            if budget:
                budget.charge(u)
                if budget.hard_exceeded():
                    raise BudgetExceeded(
                        f"hard cap blown at ${budget.spent_usd:.3f} "
                        f"after {len(results)} workers")

    if budget:
        # Workers are parallel: critical path adds only the slowest worker.
        worker_lat = [r.latency_s for r in ledger.records if r.role == "worker"]
        budget.elapsed_s += max(worker_lat) if worker_lat else 0.0

    # 3. Synthesizer combines worker outputs (hard reasoning -> large model).
    if not budget or not budget.hard_exceeded():
        su = await call_model(rng, role="synthesizer", model="large",
                              in_tok=1500, out_tok=600)
        ledger.record(su)
        if budget:
            budget.charge(su)
            budget.elapsed_s += su.latency_s

    return {"ledger": ledger, "results": results,
            "complete": len(results) == len(steps)}


# --- Demonstrations ---------------------------------------------------------


def _make_steps() -> list[Step]:
    # 3 easy workers, 2 hard ones — a realistic mix.
    return [
        Step("classify", is_hard=False, out_tok=150),
        Step("extract", is_hard=False, out_tok=200),
        Step("summarize-easy", is_hard=False, out_tok=500),  # triggers extra turn
        Step("reason-A", is_hard=True, out_tok=700),
        Step("reason-B", is_hard=True, out_tok=650),
    ]


def _report(label: str, out: dict) -> None:
    ledger: RunLedger = out["ledger"]
    print(f"\n[{label}]")
    for role, agg in ledger.by_role().items():
        print(f"  {role:<12} calls={agg['calls']} in={agg['in']:>6} "
              f"out={agg['out']:>5} ${agg['usd']:.4f} "
              f"sum_lat={agg['latency_s']:.2f}s")
    print(f"  TOTAL ${ledger.total_usd:.4f}  "
          f"critical_path={ledger.critical_path_s():.2f}s  "
          f"complete={out['complete']}")


async def main() -> None:
    seed = 7

    print("=== Task 1+2: per-role instrumentation; committed budgets ===")
    print(f"  budgets: cost <= ${MAX_USD}/task, latency p95 <= {MAX_LATENCY_S}s")
    print(f"  latency split: orch={ORCH_SLICE_S}s worker={WORKER_SLICE_S}s "
          f"synth={SYNTH_SLICE_S}s -> per-hop timeouts")
    baseline = await run_pipeline(random.Random(seed), _make_steps(),
                                  routing=False, caching=False)
    _report("no routing, no caching", baseline)

    print("\n=== Task 3: route by difficulty (report both budgets) ===")
    routed = await run_pipeline(random.Random(seed), _make_steps(),
                                routing=True, caching=False)
    _report("routing on", routed)
    b, r = baseline["ledger"], routed["ledger"]
    print(f"  cost delta: ${b.total_usd:.4f} -> ${r.total_usd:.4f} "
          f"({(1 - r.total_usd / b.total_usd):.0%} cheaper)")
    print(f"  latency delta: {b.critical_path_s():.2f}s -> "
          f"{r.critical_path_s():.2f}s "
          f"(note: cheap model's extra turn adds worker latency)")

    print("\n=== Task 4: cache shared context ===")
    cached = await run_pipeline(random.Random(seed), _make_steps(),
                                routing=True, caching=True)
    _report("routing + caching", cached)
    print(f"  token/cost reduction from caching: "
          f"${routed['ledger'].total_usd:.4f} -> "
          f"${cached['ledger'].total_usd:.4f}")

    print("\n=== Task 5a: soft cap stops early, synthesizes partial ===")
    # A 15-worker task (3 waves). The soft cost cap trips between waves, so we
    # stop launching new waves and still synthesize from what completed.
    big_task = [Step(f"w{i}", is_hard=True, out_tok=700) for i in range(15)]
    tight = RunBudget(max_usd=0.05, max_latency_s=MAX_LATENCY_S, hard_usd=HARD_USD)
    soft = await run_pipeline(random.Random(seed), big_task,
                              routing=True, caching=True, budget=tight)
    print(f"  soft cap fired: completed {len(soft['results'])}/15 workers, "
          f"then synthesized; complete={soft['complete']} "
          f"spent=${tight.spent_usd:.4f} (cap ${tight.max_usd})")

    print("\n=== Task 5b: hard cap aborts a runaway run ===")
    # A decomposition bug spawns 200 hard workers. The soft caps are set high
    # (mis-estimated for this task), so the HARD cap is the backstop that stops
    # spend running away.
    runaway_steps = [Step(f"w{i}", is_hard=True, out_tok=900) for i in range(200)]
    hard = RunBudget(max_usd=10.0, max_latency_s=1e9, hard_usd=HARD_USD)
    try:
        await run_pipeline(random.Random(seed), runaway_steps,
                           routing=True, caching=True, budget=hard)
        print("  ERROR: hard cap did not fire")
    except BudgetExceeded as exc:
        print(f"  hard cap aborted the run: {exc} "
              f"(stopped at ${hard.spent_usd:.3f}, ceiling ${HARD_USD})")


if __name__ == "__main__":
    asyncio.run(main())
```

## Meeting the acceptance criteria

- **Per-role tokens, dollars, and critical-path latency.** `RunLedger.by_role`
  prints input/output tokens, dollars, and latency for `orchestrator`,
  `worker`, and `synthesizer`; `critical_path_s` reports
  `orchestrator + max(worker) + synthesizer` — the time the user actually waits,
  not the sum of all calls.
- **Committed budgets, latency split into per-hop timeouts.** `MAX_USD`,
  `MAX_LATENCY_S`, and `HARD_USD` are explicit, and the latency budget is split
  into `ORCH_SLICE_S` / `WORKER_SLICE_S` / `SYNTH_SLICE_S` (asserted to fit the
  budget) — those slices are the per-hop timeouts.
- **Routing reduces cost, reported against both budgets.** Task 3 runs the same
  task set with routing off then on and prints the cost delta (cheaper) *and*
  the critical-path latency delta, explicitly noting where the cheap model's
  extra turn on `summarize-easy` adds worker latency — the cost/latency trade
  the exercise asks you to surface.
- **Caching measurably reduces tokens/cost.** Task 4 charges the 10 000 shared
  context tokens at full price once and at a 90% discount thereafter; the
  printed total drops versus the un-cached routed run because four of the five
  workers read the shared prompt and corpus from cache.
- **Soft and hard caps both fire.** Task 5a runs a 15-worker (3-wave) task with
  a low `max_usd`; the soft cap trips between waves, stops launching new waves
  after the first 5 workers, and still synthesizes a partial result
  (`complete=False`). Task 5b decomposes into 200 hard workers with the soft
  caps set high (mis-estimated); the hard cap raises `BudgetExceeded` and aborts
  the run the moment spend crosses the `HARD_USD` ceiling — the backstop the
  soft cap can't provide once a huge batch is already dispatched.

## Common pitfalls

- **Summing latencies instead of taking the critical path.** Adding every
  call's latency overcounts wildly when workers run in parallel — the user waits
  for the slowest worker, not all of them. Reconstruct the path from the
  dependency structure.
- **Pricing input and output at the same rate.** Output tokens cost ~4–5× input
  on most providers; a single blended price hides where the money goes and makes
  the synthesizer (output-heavy) look cheaper than it is.
- **Charging cached context at full price.** If your cost model doesn't credit
  the cache discount, caching shows no savings and you'll wrongly conclude it
  isn't worth it. Model the cache-write-once / cache-read-discounted split.
- **A soft cap with no hard cap (or vice versa).** The soft cap is for normal
  overruns (stop and synthesize); the hard cap is for pathological ones (a
  decomposition bug spawning 200 workers). You need both — the soft cap won't
  save you from a runaway because it only stops *new* fan-out, not an already
  enormous one.
- **Ignoring the extra-turn tax of cheap models.** Routing to a small model can
  erase its own savings if it needs enough extra turns. Always report routing's
  effect on *both* budgets, not just cost.

## Verification

```bash
python3 exercise_03.py
```

Confirm in the printed output:

1. Tasks 1+2 — per-role rows (orchestrator/worker/synthesizer) with tokens,
   dollars, latency; the committed budgets and the latency split print.
2. Task 3 — the routed total is cheaper than the baseline (printed percent), and
   the critical-path latency delta is shown with the extra-turn note.
3. Task 4 — `routing + caching` total is lower than `routing on` alone.
4. Task 5a — soft cap stops the 15-worker task after the first wave (5/15) and
   still synthesizes (`complete=False`).
5. Task 5b — hard cap prints `hard cap aborted the run` for the 200-worker
   runaway, stopping the moment spend crosses `$0.20`.

All RNG is seeded, so the numbers are reproducible run to run.
