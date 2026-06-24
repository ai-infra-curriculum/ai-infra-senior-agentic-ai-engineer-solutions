# mod-404-reliability-cost-incident/exercise-02 — Solution

## Approach

The brief asks for the cost-control layer of an agent: a **per-run budget
guard** that bounds a single invocation and a **per-tenant circuit breaker**
that bounds a noisy customer — both **failing closed** — wired into a loop that
emits attributable cost records. The reference implementation keeps the model
and tool calls stubbed so the whole thing is deterministic, free to run, and
testable in CI, exactly as the exercise suggests.

Four design decisions drive the implementation:

- **Check before, charge after, fail closed.** The per-run guard checks the
  budget *before* each model/tool call so a run never overshoots by a full
  expensive step, and charges *after* so the numbers reflect real usage. On a
  breach it stops the loop and returns a graceful bounded result — it never
  silently continues past the cap.
- **Caps are config, not constants.** `RunBudget` reads from a mutable
  `BudgetConfig` so on-call can tighten step/token/USD caps during an incident
  without a code deploy (this is the lever exercise-03 pulls).
- **The breaker rejects fast from a shared store.** `TenantBreaker` checks a
  rolling per-tenant spend bucket *before* admitting a run, so a tenant over cap
  costs **zero** model spend. Buckets expire so the store doesn't grow
  unbounded. The store is abstracted behind a tiny interface; an in-memory stub
  mimics Redis `get` / `incrbyfloat` / `expire` for the demo, and the same code
  runs against real Redis.
- **One attributable cost record per run.** Every run emits
  `tenant`, `feature`, `model`, `tokens_in/out`, `tool_calls`, `usd`, and
  `outcome` (`ok` / `budget_exceeded` / `rejected`). Those records aggregate
  into a p99-cost-per-run SLI and a per-tenant spend view.

The store **fails closed on cost**: if the shared store is unreachable, the
breaker raises (rejecting the run) rather than admitting unbounded spend. That
is the right call for a cost control — an unavailable breaker must not become an
open spigot. (For an availability control you might choose the opposite; the
trade-off is discussed in `NOTES.md`.)

## Reference implementation

Runnable on Python 3.11+ with no third-party dependencies. Save as
`cost_controls.py` and run `python cost_controls.py` for the worked demo.

```python
"""Per-run budget guard + per-tenant circuit breaker for an agent loop.

Both fail closed. Caps are config so they can be tightened at runtime. Every
run emits an attributable cost record. Pure stdlib; the model/tool calls are
stubbed so the demo is deterministic and free.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    """Raised when a run exceeds a hard per-run limit. Fail closed."""


class CircuitOpen(Exception):
    """Raised when a tenant is over its window cap. Reject fast, no spend."""


# --- Config (mutable so on-call can tighten without a deploy) ------------------


@dataclass
class BudgetConfig:
    max_steps: int = 12
    max_total_tokens: int = 120_000
    max_usd: float = 0.50


@dataclass
class BreakerConfig:
    cap_usd: float = 5.00
    window_s: int = 3600


# --- Per-run guard ------------------------------------------------------------


@dataclass
class RunBudget:
    config: BudgetConfig
    steps: int = 0
    total_tokens: int = 0
    usd: float = 0.0

    def check(self) -> None:
        """Call BEFORE each model/tool call. Trips on the first breach."""
        c = self.config
        if self.steps >= c.max_steps:
            raise BudgetExceeded(f"step cap {c.max_steps} reached")
        if self.total_tokens >= c.max_total_tokens:
            raise BudgetExceeded(f"token cap {c.max_total_tokens} reached")
        if self.usd >= c.max_usd:
            raise BudgetExceeded(f"usd cap ${c.max_usd:.2f} reached")

    def charge(self, *, tokens: int, usd: float) -> None:
        """Call AFTER each model/tool call to record real spend."""
        self.steps += 1
        self.total_tokens += tokens
        self.usd += usd


# --- Shared store + per-tenant breaker ----------------------------------------


class StoreUnavailable(Exception):
    """The shared store could not be reached."""


class InMemoryStore:
    """Mimics the Redis ops the breaker needs. Swap for real Redis in prod."""

    def __init__(self, *, fail: bool = False) -> None:
        self._data: dict[str, float] = {}
        self._expiry: dict[str, float] = {}
        self.fail = fail  # flip to simulate an outage

    def _expire_sweep(self) -> None:
        now = time.time()
        for k in [k for k, t in self._expiry.items() if t <= now]:
            self._data.pop(k, None)
            self._expiry.pop(k, None)

    async def get(self, key: str) -> float | None:
        if self.fail:
            raise StoreUnavailable("store down")
        self._expire_sweep()
        return self._data.get(key)

    async def incrbyfloat(self, key: str, amount: float) -> float:
        if self.fail:
            raise StoreUnavailable("store down")
        self._data[key] = self._data.get(key, 0.0) + amount
        return self._data[key]

    async def expire(self, key: str, ttl_s: int) -> None:
        if self.fail:
            raise StoreUnavailable("store down")
        self._expiry[key] = time.time() + ttl_s


class TenantBreaker:
    def __init__(self, store: InMemoryStore, config: BreakerConfig) -> None:
        self.store = store
        self.config = config

    def _key(self, tenant: str) -> str:
        bucket = int(time.time()) // self.config.window_s
        return f"spend:{tenant}:{bucket}"

    async def guard(self, tenant: str) -> None:
        """Call before admitting a run. Over cap (or store down) => reject."""
        try:
            spent = float(await self.store.get(self._key(tenant)) or 0.0)
        except StoreUnavailable as exc:
            # Fail CLOSED on cost: an unreachable breaker must not admit spend.
            raise CircuitOpen(f"breaker store unavailable: {exc}") from exc
        if spent >= self.config.cap_usd:
            raise CircuitOpen(
                f"tenant {tenant} over ${self.config.cap_usd:.2f}/window")

    async def record(self, tenant: str, usd: float) -> None:
        key = self._key(tenant)
        try:
            await self.store.incrbyfloat(key, usd)
            await self.store.expire(key, self.config.window_s * 2)
        except StoreUnavailable:
            # Best-effort accounting; the guard already failed closed on read.
            pass


# --- Attributable cost record + the wrapped loop ------------------------------


@dataclass
class CostRecord:
    tenant: str
    feature: str
    model: str
    tokens_in: int
    tokens_out: int
    tool_calls: int
    usd: float
    outcome: str  # "ok" | "budget_exceeded" | "rejected"


@dataclass
class StubStep:
    tokens_in: int
    tokens_out: int
    usd: float
    done: bool


@dataclass
class StubAgent:
    """A deterministic stand-in for a real model/tool loop."""

    steps_to_finish: int
    per_step_tokens_in: int = 4_000
    per_step_tokens_out: int = 1_000
    per_step_usd: float = 0.05
    _emitted: int = field(default=0)

    async def step(self) -> StubStep:
        self._emitted += 1
        return StubStep(
            tokens_in=self.per_step_tokens_in,
            tokens_out=self.per_step_tokens_out,
            usd=self.per_step_usd,
            done=self._emitted >= self.steps_to_finish,
        )


async def run_agent(
    *, tenant: str, feature: str, model: str, agent: StubAgent,
    budget: RunBudget, breaker: TenantBreaker, sink: list[CostRecord],
) -> CostRecord:
    """Admit via the breaker, run under the per-run guard, record spend."""
    # Admission: reject fast, zero model spend, if the tenant is over cap.
    try:
        await breaker.guard(tenant)
    except CircuitOpen:
        rec = CostRecord(tenant, feature, model, 0, 0, 0, 0.0, "rejected")
        sink.append(rec)
        return rec

    tokens_in = tokens_out = tool_calls = 0
    outcome = "ok"
    try:
        while True:
            budget.check()                      # fail closed BEFORE spending
            out = await agent.step()            # the spend happens here
            budget.charge(tokens=out.tokens_in + out.tokens_out, usd=out.usd)
            tokens_in += out.tokens_in
            tokens_out += out.tokens_out
            tool_calls += 1
            if out.done:
                break
    except BudgetExceeded:
        outcome = "budget_exceeded"             # graceful bounded result

    await breaker.record(tenant, budget.usd)    # attribute real spend
    rec = CostRecord(tenant, feature, model, tokens_in, tokens_out,
                     tool_calls, budget.usd, outcome)
    sink.append(rec)
    return rec


# --- Aggregation: p99 cost per run + per-tenant spend -------------------------


def p99_cost_per_run(records: list[CostRecord]) -> float:
    billed = sorted(r.usd for r in records if r.outcome != "rejected")
    if not billed:
        return 0.0
    idx = max(0, math.ceil(0.99 * len(billed)) - 1)
    return billed[idx]


def spend_by_tenant(records: list[CostRecord]) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in records:
        out[r.tenant] = out.get(r.tenant, 0.0) + r.usd
    return out


# --- Worked demo --------------------------------------------------------------


async def _demo() -> None:
    sink: list[CostRecord] = []
    store = InMemoryStore()
    breaker = TenantBreaker(store, BreakerConfig(cap_usd=5.00, window_s=3600))

    # 1. A normal run finishes well under the caps.
    ok = await run_agent(
        tenant="acme", feature="search", model="stub-1",
        agent=StubAgent(steps_to_finish=4),
        budget=RunBudget(BudgetConfig()), breaker=breaker, sink=sink)
    assert ok.outcome == "ok" and ok.tool_calls == 4
    print(f"[1] normal: outcome={ok.outcome} usd=${ok.usd:.2f} steps={ok.tool_calls}")

    # 2. A runaway run trips the per-run cap and returns a bounded result.
    runaway = await run_agent(
        tenant="acme", feature="search", model="stub-1",
        agent=StubAgent(steps_to_finish=10_000),         # never finishes on its own
        budget=RunBudget(BudgetConfig(max_steps=6)),     # tightened cap
        breaker=breaker, sink=sink)
    assert runaway.outcome == "budget_exceeded"
    assert runaway.tool_calls == 6                       # stopped exactly at cap
    print(f"[2] runaway: outcome={runaway.outcome} steps={runaway.tool_calls} "
          f"usd=${runaway.usd:.2f}")

    # 3. A noisy tenant is pushed over its window cap, then rejected with ZERO spend.
    noisy_store = InMemoryStore()
    noisy_breaker = TenantBreaker(noisy_store, BreakerConfig(cap_usd=0.30, window_s=3600))
    first = await run_agent(
        tenant="loud", feature="chat", model="stub-1",
        agent=StubAgent(steps_to_finish=8),              # spends 8 * 0.05 = $0.40 > cap
        budget=RunBudget(BudgetConfig()), breaker=noisy_breaker, sink=sink)
    rejected = await run_agent(
        tenant="loud", feature="chat", model="stub-1",
        agent=StubAgent(steps_to_finish=8),
        budget=RunBudget(BudgetConfig()), breaker=noisy_breaker, sink=sink)
    assert rejected.outcome == "rejected"
    assert rejected.usd == 0.0 and rejected.tool_calls == 0   # zero model spend
    # Another tenant on the same breaker is unaffected.
    other = await run_agent(
        tenant="quiet", feature="chat", model="stub-1",
        agent=StubAgent(steps_to_finish=2),
        budget=RunBudget(BudgetConfig()), breaker=noisy_breaker, sink=sink)
    assert other.outcome == "ok"
    print(f"[3] noisy first=${first.usd:.2f} then rejected (usd=${rejected.usd:.2f}); "
          f"other tenant outcome={other.outcome}")

    # 4. Store outage => breaker fails CLOSED (rejects), no unbounded spend.
    down = TenantBreaker(InMemoryStore(fail=True), BreakerConfig())
    blocked = await run_agent(
        tenant="acme", feature="search", model="stub-1",
        agent=StubAgent(steps_to_finish=4),
        budget=RunBudget(BudgetConfig()), breaker=down, sink=sink)
    assert blocked.outcome == "rejected" and blocked.usd == 0.0
    print(f"[4] store down: outcome={blocked.outcome} (failed closed)")

    # 5. Aggregate the attributable records.
    print(f"[5] p99_cost_per_run=${p99_cost_per_run(sink):.2f}")
    for tenant, usd in sorted(spend_by_tenant(sink).items()):
        print(f"    spend[{tenant}]=${usd:.2f}")


if __name__ == "__main__":
    asyncio.run(_demo())
    print("OK")
```

The `global` rate/spend ceiling from the stretch goals slots in at the
admission point next to `breaker.guard` — the same fail-fast pattern, keyed on
the platform instead of the tenant.

## Meeting the acceptance criteria

- **A runaway run stops at the per-run cap with a graceful bounded result.**
  Demo step **[2]** runs an agent that never finishes on its own under a
  `max_steps=6` cap; it stops at exactly 6 steps with `outcome=budget_exceeded`
  and returns a record — it never loops unbounded and never continues past the
  cap. Because the guard *checks before* spending, the run also never overshoots
  by a full step.
- **A tenant over cap is rejected fast with zero model spend, others
  unaffected.** Demo step **[3]**: tenant `loud` spends $0.40 against a $0.30
  window cap, so its next run is `rejected` with `usd == 0.0` and zero tool
  calls (no model was called). Tenant `quiet` on the same breaker runs normally.
- **Caps are config-driven and tightenable at runtime without a code change.**
  `BudgetConfig` and `BreakerConfig` are mutable dataclasses passed in by
  reference; step **[2]** demonstrates running under a tightened `max_steps`,
  the same move on-call makes mid-incident in exercise-03.
- **Every run emits an attributable cost record, and you can produce p99 cost
  and per-tenant spend.** Each `run_agent` appends a `CostRecord` with tenant,
  feature, model, tokens in/out, tool calls, USD, and outcome; step **[5]**
  prints `p99_cost_per_run` and `spend_by_tenant` from those records.

## Common pitfalls

- **Charging before checking (or checking after charging).** Reverse the order
  and a run overshoots by one full expensive step before it trips — for a
  120k-token step that is real money. Check before, charge after.
- **Failing open when the breaker store is down.** Swallowing
  `StoreUnavailable` and admitting the run turns an outage into unbounded spend.
  For a cost control, an unreachable breaker must **reject** (fail closed).
- **Spending model tokens on a rejected run.** If the breaker check happens
  *inside* the loop instead of at admission, a rejected tenant still pays for
  the first call. Guard at admission so rejection is free.
- **Buckets that never expire.** Without `expire`, the per-tenant spend keys
  grow without bound and old windows never roll off. Set a TTL of roughly twice
  the window.
- **Caps as constants.** Hard-coding `max_steps = 12` means tightening it during
  an incident requires a deploy — exactly when you can least afford one. Read
  caps from mutable config.

## Verification

```bash
cd modules/mod-404-reliability-cost-incident/exercise-02-cost-controls-in-production
python cost_controls.py
```

Expected: lines `[1]`–`[5]` then `OK`. `[2]` shows the runaway run stopping at
6 steps with `budget_exceeded`; `[3]` shows tenant `loud` rejected at `$0.00`
while `quiet` succeeds; `[4]` shows the breaker failing closed when the store is
down; `[5]` prints the p99 cost per run and per-tenant spend. Every `assert` in
`_demo` must pass for the run to reach `OK`.
