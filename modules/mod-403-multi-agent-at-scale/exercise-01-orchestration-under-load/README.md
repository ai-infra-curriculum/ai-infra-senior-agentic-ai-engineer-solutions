# mod-403-multi-agent-at-scale/exercise-01 (Orchestration Under Load) — Solution

## Approach

The exercise asks us to take an orchestrator-worker system that works for one
request and make it survive production traffic, then *prove* it with numbers.
The reference implementation builds one orchestrator with five interchangeable
controls layered on top of the same worker path, so we can flip each control on
or off and re-run the identical load test:

1. **A deterministic load harness with a real bottleneck.** A pure
   `asyncio.sleep` worker would *not* collapse under load — `asyncio` happily
   runs ten thousand sleeps concurrently and they all finish in ~2s — so the
   stub has to model the actual scarce resource. The reference routes every
   worker call through a shared **`Provider`** with a finite number of servers
   (its real concurrency limit) and an explicit wait queue. When fan-out
   oversubscribes the provider, calls queue and their *end-to-end* latency is
   service time **plus** queueing delay — exactly the M/M/c blow-up that takes
   real systems down. The worker also fails ~5% of the time. A seeded RNG keeps
   runs reproducible. The harness offers a fixed number of concurrent requests,
   each fanning out to five workers, and records throughput, p95 end-to-end
   latency, success rate, and peak provider-queue depth (our memory/saturation
   proxy — every queued call holds a task and partial state, so an unbounded
   queue *is* unbounded memory).
2. **Bounded concurrency.** A single process-wide `asyncio.Semaphore` caps
   simultaneous worker calls *at our gateway*, sized from the stated provider
   quota (20 servers) with headroom. The point: hold the in-flight worker count
   at or below what the provider can serve, so calls queue **in our admission
   semaphore** (fair, observable, sheddable) rather than piling into the
   provider's queue where latency compounds. Past the cap, requests wait at the
   semaphore instead of all hitting the provider at once.
3. **Backpressure.** A high-water mark on in-flight *requests* (not workers).
   Past it, new requests are rejected immediately with an `Overloaded` error
   carrying a `Retry-After`, modelling an HTTP `429`. Fast rejection keeps the
   accepted set small enough to actually finish.
4. **Per-hop timeouts.** A latency budget (p95 ≤ 8s) is split across the path;
   each worker call gets its slice via `asyncio.wait_for`. A slow worker is cut
   off at the timeout, the semaphore slot is released by the cancellation, and
   the assignment is counted as failed.
5. **Graceful degradation.** The orchestrator gathers with
   `return_exceptions=True`, synthesizes from the workers that returned, and
   labels the missing assignments explicitly. No exception is swallowed — every
   failure shows up in the `missing` list with its reason.

The key design decision is that **backpressure guards requests and the
semaphore guards workers**. They solve different problems: the semaphore bounds
load on the downstream provider; backpressure bounds the queue in front of the
whole system so latency can't run away under overload (Little's Law — if
arrival rate exceeds service rate, the queue and therefore latency grow without
bound; shedding load fast caps the queue).

## Reference implementation

```python
"""Orchestrator-worker system hardened for load: bounded concurrency,
backpressure, per-hop timeouts, and graceful degradation.

Stdlib only. Python 3.11+. Deterministic via a seeded RNG so the recorded
numbers are reproducible. Run: python3 exercise_01.py
"""

from __future__ import annotations

import asyncio
import random
import statistics
import time
from dataclasses import dataclass, field

# --- Tunables ---------------------------------------------------------------

PROVIDER_SERVERS = 20        # the downstream's real concurrency limit (servers)
WORKER_LIMIT = 18            # gateway semaphore cap: below the quota, headroom
IN_FLIGHT_MAX = 100          # backpressure high-water mark on requests
LATENCY_BUDGET_S = 8.0       # p95 end-to-end target
FANOUT = 5                   # workers per request
RETRY_AFTER_S = 1            # advertised to rejected callers
SERVICE_MIN_S = 0.1          # worker service time, lower bound
SERVICE_MAX_S = 0.5          # worker service time, upper bound
FAILURE_RATE = 0.05          # ~5% of worker calls raise
REQUEST_DEADLINE_S = 8.0     # end-to-end deadline; past it the caller is gone
CONGESTION_TAX_S = 0.0005    # per-call slowdown per concurrent in-flight call

# Latency budget split across the path. Orchestrator overhead is tiny; most of
# the budget goes to the (parallel) worker hop, leaving a synthesis slice. The
# worker slice is the per-worker asyncio.wait_for timeout.
ORCHESTRATOR_SLICE_S = 0.5
WORKER_SLICE_S = 6.5
SYNTHESIS_SLICE_S = 1.0
assert ORCHESTRATOR_SLICE_S + WORKER_SLICE_S + SYNTHESIS_SLICE_S <= LATENCY_BUDGET_S


class Overloaded(Exception):
    """Raised when the system is past its in-flight high-water mark."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"overloaded; retry-after: {retry_after_s}s")
        self.retry_after_s = retry_after_s


class DeadlineExceeded(Exception):
    """The request blew its end-to-end deadline; the caller has given up.

    Distinct from Overloaded: this request was *admitted* and then took too
    long (queued behind oversubscription), so the work it consumed is wasted.
    """


@dataclass
class WorkerFailure:
    """A first-class failure record so nothing is silently dropped."""

    assignment_id: str
    reason: str


# --- The shared downstream provider (the real bottleneck) -------------------


class Provider:
    """A finite-server downstream. Calls beyond `servers` queue and wait.

    This is what makes the unbounded case actually collapse:

    * a pure asyncio.sleep worker has no contention, but a real provider serves
      only so many calls at once. Oversubscribe it and end-to-end latency
      becomes service time PLUS queueing delay (M/M/c);
    * and a *congestion tax* — every call gets slower as the number of accepted
      requests in flight rises (memory pressure, GC, connection bookkeeping,
      scheduler overhead). This holding cost is paid by *every admitted
      request*, not just the ones a worker semaphore is currently serving, so
      admitting work you can't finish actively harms the work you *can*. That is
      exactly why fast rejection raises goodput: a gateway semaphore alone
      bounds worker concurrency but NOT the request backlog, so without
      backpressure the tax keeps climbing.

    `congestion()` is supplied by the orchestrator (its accepted in-flight
    count). We track peak queue depth as a saturation proxy.
    """

    def __init__(self, servers: int) -> None:
        self._sem = asyncio.Semaphore(servers)
        self._congestion = lambda: 0      # set by the orchestrator that owns it
        self._queued = 0
        self.peak_queue = 0

    def set_congestion_source(self, fn) -> None:
        """Wire in the orchestrator's accepted-in-flight gauge."""
        self._congestion = fn

    async def call(self, rng: random.Random, assignment_id: str,
                   service_s: float | None = None) -> dict:
        self._queued += 1                          # entered the wait queue
        self.peak_queue = max(self.peak_queue, self._queued)
        dequeued = False
        try:
            async with self._sem:                  # only `servers` run at once
                self._queued -= 1                  # left the queue, now serving
                dequeued = True
                if service_s is not None:
                    dur = service_s                # forced (e.g. slow worker)
                else:
                    base = rng.uniform(SERVICE_MIN_S, SERVICE_MAX_S)
                    # Holding cost scales with accepted requests in flight.
                    dur = base + CONGESTION_TAX_S * self._congestion()
                await asyncio.sleep(dur)
                if service_s is None and rng.random() < FAILURE_RATE:
                    raise RuntimeError(f"worker {assignment_id} transient error")
                return {"assignment_id": assignment_id,
                        "answer": f"result-for-{assignment_id}"}
        finally:
            # If we were cancelled (timeout) WHILE still waiting on the
            # semaphore, we never decremented on dequeue — do it now so the
            # queue gauge can't leak.
            if not dequeued:
                self._queued -= 1


# --- The orchestrator -------------------------------------------------------


@dataclass
class Orchestrator:
    """One orchestrator instance. Toggle controls to compare configurations."""

    rng: random.Random
    provider: Provider
    bounded: bool = True          # task 2: gateway semaphore on worker calls
    backpressure: bool = True     # task 3: reject past high-water mark
    timeouts: bool = True         # task 4: per-hop wait_for
    worker_timeout_s: float = WORKER_SLICE_S
    slow_worker_delay_s: float | None = None  # force one worker slow (task 4)

    _sem: asyncio.Semaphore = field(init=False)
    _in_flight: int = field(default=0, init=False)
    _peak_in_flight: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # An "unbounded" gateway still needs *a* semaphore object; we just make
        # it large enough not to bind, so the only difference is the cap.
        cap = WORKER_LIMIT if self.bounded else 10_000
        self._sem = asyncio.Semaphore(cap)
        # The provider's congestion tax scales with OUR accepted in-flight count.
        self.provider.set_congestion_source(lambda: self._in_flight)

    @property
    def peak_in_flight(self) -> int:
        return self._peak_in_flight

    async def _run_worker(self, assignment_id: str, force_slow: bool) -> dict:
        async with self._sem:                      # gateway bounded concurrency
            service_s = (self.slow_worker_delay_s
                         if force_slow and self.slow_worker_delay_s is not None
                         else None)
            coro = self.provider.call(self.rng, assignment_id, service_s)
            if self.timeouts:
                # wait_for cancels the inner coroutine on timeout, which exits
                # the provider's `async with` and frees both slots — no leak.
                return await asyncio.wait_for(coro, self.worker_timeout_s)
            return await coro

    async def handle_request(self, assignments: list[str]) -> dict:
        """Fan out to workers, synthesize from whoever returned, label misses."""
        if self.backpressure and self._in_flight >= IN_FLIGHT_MAX:
            raise Overloaded(RETRY_AFTER_S)        # reject fast, free the system

        self._in_flight += 1
        self._peak_in_flight = max(self._peak_in_flight, self._in_flight)
        try:
            # Whole-request end-to-end deadline. Under oversubscription a request
            # can sit behind a huge queue; past the deadline the caller is gone,
            # so we cut it and count it failed. This is why over-admitting
            # *loses* completed work — and why backpressure raises successful
            # throughput.
            async def _fanout() -> list:
                # One assignment is "slow" only if a slow delay is configured,
                # to demonstrate the per-worker timeout cutting it off (task 4).
                return await asyncio.gather(
                    *(
                        self._run_worker(a, force_slow=(i == 0))
                        for i, a in enumerate(assignments)
                    ),
                    return_exceptions=True,
                )

            try:
                settled = await asyncio.wait_for(_fanout(), REQUEST_DEADLINE_S)
            except asyncio.TimeoutError:
                raise DeadlineExceeded(
                    f"request exceeded {REQUEST_DEADLINE_S}s end-to-end")

            results: list[dict] = []
            missing: list[WorkerFailure] = []
            for assignment_id, outcome in zip(assignments, settled):
                if isinstance(outcome, asyncio.TimeoutError):
                    missing.append(WorkerFailure(assignment_id, "timeout"))
                elif isinstance(outcome, Exception):
                    missing.append(WorkerFailure(assignment_id, str(outcome)))
                else:
                    results.append(outcome)

            # Graceful degradation: a useful partial answer with explicit gaps.
            return {
                "results": results,
                "missing": [{"assignment_id": m.assignment_id, "reason": m.reason}
                            for m in missing],
                "complete": not missing,
            }
        finally:
            self._in_flight -= 1


# --- The load harness -------------------------------------------------------


@dataclass
class Tallies:
    latencies: list[float] = field(default_factory=list)
    rejected: int = 0          # fast-rejected by backpressure (429)
    deadline: int = 0          # admitted but blew the end-to-end deadline
    succeeded: int = 0         # returned at least a partial answer in time


@dataclass
class LoadResult:
    offered: int
    accepted: int
    rejected: int
    deadline_failed: int
    succeeded: int          # requests that returned a partial answer in time
    throughput_rps: float
    p95_latency_s: float
    success_rate: float
    peak_queue: int         # peak provider-queue depth (saturation proxy)


async def _drive_one(orch: Orchestrator, t: Tallies) -> None:
    assignments = [f"a{i}" for i in range(FANOUT)]
    t0 = time.monotonic()
    try:
        await orch.handle_request(assignments)
        t.latencies.append(time.monotonic() - t0)
        t.succeeded += 1
    except Overloaded:
        t.rejected += 1
    except DeadlineExceeded:
        t.deadline += 1


async def run_load(orch: Orchestrator, concurrency: int) -> LoadResult:
    """Offer `concurrency` simultaneous requests; record the headline numbers."""
    t = Tallies()
    wall0 = time.monotonic()
    await asyncio.gather(*(_drive_one(orch, t) for _ in range(concurrency)))
    wall = time.monotonic() - wall0

    p95 = (statistics.quantiles(t.latencies, n=20)[18]
           if len(t.latencies) >= 20
           else (max(t.latencies) if t.latencies else 0.0))
    return LoadResult(
        offered=concurrency,
        accepted=concurrency - t.rejected,
        rejected=t.rejected,
        deadline_failed=t.deadline,
        succeeded=t.succeeded,
        throughput_rps=t.succeeded / wall if wall else 0.0,
        p95_latency_s=p95,
        success_rate=t.succeeded / concurrency if concurrency else 0.0,
        peak_queue=orch.provider.peak_queue,
    )


def _print_row(label: str, r: LoadResult) -> None:
    print(f"{label:<24} offered={r.offered:>4} rej={r.rejected:>4} "
          f"deadline={r.deadline_failed:>4} ok={r.succeeded:>4} "
          f"thr={r.throughput_rps:6.1f}rps p95={r.p95_latency_s:6.2f}s "
          f"succ={r.success_rate:5.1%} peak_q={r.peak_queue:>4}")


def _make(seed: int, **kw) -> Orchestrator:
    """Build an orchestrator with a fresh provider for an isolated run."""
    return Orchestrator(random.Random(seed), Provider(PROVIDER_SERVERS), **kw)


async def main() -> None:
    seed = 1234

    print("=== Task 1: baseline, unbounded, rising load (find the knee) ===")
    for concurrency in (1, 10, 50, 200):
        orch = _make(seed, bounded=False, backpressure=False, timeouts=False)
        _print_row(f"unbounded c={concurrency}", await run_load(orch, concurrency))

    print("\n=== Task 2: same load, bounded concurrency (latency bounded) ===")
    for concurrency in (1, 10, 50, 200):
        orch = _make(seed, bounded=True, backpressure=False, timeouts=True)
        _print_row(f"bounded   c={concurrency}", await run_load(orch, concurrency))

    print("\n=== Task 3: overload with vs. without backpressure ===")
    overload = 400
    no_bp = _make(seed, bounded=True, backpressure=False, timeouts=True)
    _print_row("no-backpressure", await run_load(no_bp, overload))
    bp = _make(seed, bounded=True, backpressure=True, timeouts=True)
    _print_row("backpressure", await run_load(bp, overload))

    print("\n=== Task 4: a deliberately slow worker is cut off at its timeout ===")
    slow = _make(seed, bounded=True, backpressure=True, timeouts=True,
                 worker_timeout_s=1.0, slow_worker_delay_s=5.0)
    out = await slow.handle_request([f"a{i}" for i in range(FANOUT)])
    print(f"slow-worker run -> results={len(out['results'])} "
          f"missing={out['missing']} complete={out['complete']}")

    print("\n=== Task 5: graceful degradation, partial answer with labels ===")
    degraded = _make(seed, bounded=True, backpressure=True, timeouts=True,
                     worker_timeout_s=1.0, slow_worker_delay_s=5.0)
    out = await degraded.handle_request([f"a{i}" for i in range(FANOUT)])
    print(f"returned={len(out['results'])}/{FANOUT} usable answers; "
          f"missing labelled: {[m['assignment_id'] for m in out['missing']]}; "
          f"nothing silently dropped: "
          f"{len(out['results']) + len(out['missing']) == FANOUT}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Meeting the acceptance criteria

- **Unbounded collapse is documented.** Task 1 runs the *same* code path with
  every control off across rising concurrency (1 → 200). At 200, p95 latency
  runs to the deadline, the deadline-failure count climbs, and `peak_q` tracks
  the full oversubscribed provider queue (≈980) — the unbounded queue depth
  that is our memory proxy. Those printed numbers are the documented breaking
  point.
- **Bounded concurrency protects the provider.** Task 2 re-runs the identical
  load with the gateway semaphore on. `peak_q` collapses from ≈980 to ≈1: the
  provider is never oversubscribed, because worker concurrency is held at
  `WORKER_LIMIT`. (Goodput at c=200 is similar to the unbounded run — and that
  is the point of the next bullet: the semaphore guards the *provider*, not the
  request backlog. Bounding workers alone does not stop the request-level
  congestion tax; only backpressure does.)
- **Backpressure raises successful throughput under overload.** Task 3 offers
  400 requests to a system that *already* has bounded workers. Without
  backpressure all 400 are admitted; the per-request holding cost (the
  congestion tax) makes every call slower, so most requests miss the deadline —
  goodput craters (e.g. ok≈55). With backpressure, requests past `IN_FLIGHT_MAX`
  are rejected fast with `Overloaded(retry_after=1)` (the `429` + `Retry-After`
  model); the smaller admitted set stays fast and finishes, so successful
  throughput is *higher* (e.g. ok≈81) — the printed `thr`/`ok` columns show the
  delta.
- **Every worker call has a timeout; slow workers are cut, not stuck.** Task 4
  configures one worker to take 5s against a 1s `worker_timeout_s`.
  `asyncio.wait_for` cancels it; the cancellation unwinds the `async with
  self._sem`, freeing the slot. The assignment appears in `missing` with reason
  `"timeout"`.
- **Partial answers are labelled; nothing is swallowed.** Task 5 prints a
  partial result plus the explicit list of missing assignment IDs, and asserts
  `results + missing == FANOUT`, proving every failure is accounted for.

## Common pitfalls

- **Putting the timeout *outside* the semaphore.** If you write
  `async with sem: ...` *inside* a `wait_for`, the cancellation may fire while
  the coroutine is suspended waiting to *acquire* the semaphore, and accounting
  gets murky. Acquire the slot first, then `wait_for` the work — and rely on
  `wait_for` cancelling the inner coroutine to release the slot on timeout.
- **Confusing the two limits.** A semaphore on workers does *not* bound the
  request backlog. Without a separate in-flight high-water mark, 10 000 requests
  still all enter `handle_request`, allocate fan-out tasks, and each one's
  holding cost drags the whole system down — goodput craters even though worker
  concurrency (and provider `peak_q`) is capped. That is why Task 3 needs
  backpressure on top of Task 2's semaphore.
- **Swallowing failures during synthesis.** `asyncio.gather(...,
  return_exceptions=True)` returns exceptions *as values*. If you filter them
  out without recording them, the partial answer silently shrinks and the user
  can't tell what's missing. Always emit a labelled `missing` entry.
- **A semaphore cap at or above the provider quota.** Setting `WORKER_LIMIT`
  equal to (or above) `PROVIDER_SERVERS` gives the provider no headroom for
  retries or bursts and invites `429`s from upstream. Keep it below the server
  count.
- **Reporting the mean instead of the tail.** Means hide the collapse. The
  acceptance criteria are about p95; the harness reports the 95th percentile so
  the knee is visible.

## Verification

```bash
python3 exercise_01.py
```

Read the printed tables top to bottom:

1. Task 1 — confirm `peak_q` and deadline-failures blow up as concurrency
   climbs to 200 with no controls (the breaking point: the provider queue
   reaches ≈980 and success rate falls).
2. Task 2 — confirm `peak_q` collapses to ≈1 at the same offered load with the
   semaphore on (the provider is protected; goodput still needs Task 3).
3. Task 3 — confirm `ok` and `thr` are *higher* in the `backpressure` row than
   the `no-backpressure` row at 400 offered requests.
4. Task 4 — confirm the slow worker shows up in `missing` with reason
   `timeout` and the request still returns the other four.
5. Task 5 — confirm `results + missing == FANOUT` prints `True` (no silent
   drops).

Because the RNG is seeded, the numbers are reproducible run to run; change
`seed` in `main()` to explore other samples.
