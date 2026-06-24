# mod-403-multi-agent-at-scale/exercise-02 (Durable Execution In Production) — Solution

## Approach

The exercise asks us to make a long-running, side-effecting workflow survive a
crash: model it as explicit checkpointed state, kill it mid-run, prove it
resumes from where it stopped, make the side effects idempotent so resumption
doesn't duplicate work, and add bounded retries with a dead-letter path. The
reference is the **hand-rolled** version (the exercise asks for that first) so
you can see exactly what a durable-execution engine would otherwise hide.

Design choices:

1. **State is explicit and serializable.** `WorkflowState` carries a `run_id`,
   an ordered `pending` list, a `completed` map (step id → result), a
   `dead_letter` map (step id → final failure), and a `status`. It is a plain
   dataclass so it round-trips through SQLite as one JSON blob.
2. **SQLite is the durable store, not a bare JSON file.** SQLite gives us
   *atomic transactions* for the checkpoint (the headline requirement) and a
   second table that makes the side effect idempotent via a primary-key upsert
   keyed on `(run_id, step_id)`. A JSON file with `os.replace` also satisfies
   atomicity and the code notes where; SQLite is the production-shaped choice
   and lets status be queried concurrently.
3. **Checkpoint after every step, inside a transaction.** `run()` executes one
   step, records its result, removes it from `pending`, and commits the whole
   state in a single transaction *before* moving on. A crash mid-commit leaves
   the previous committed state intact — SQLite's atomicity is the
   write-temp-then-rename equivalent.
4. **The side effect is idempotent by construction.** Each step appends an
   "effect" row keyed on `(run_id, step_id)` with `INSERT OR IGNORE`. Re-running
   a step writes zero extra rows. We *also* demonstrate the hazard first (a
   non-idempotent append) so the fix is meaningful.
5. **Crash injection is explicit and resumable.** A crash either fires *after*
   a step's checkpoint (the clean-resume case) or *after its effect but before
   the checkpoint* (the idempotency-hazard case). We catch the injected
   exception, throw away the in-memory object, and call `resume()`, which
   reloads state from disk exactly as a fresh process would.
6. **Bounded retry + dead-letter.** `with_retry` retries transient failures with
   exponential backoff and jitter, capped at `attempts`. A step that can never
   succeed raises `PermanentFailure`, is routed to a `dead_letter` table, and
   the run continues with that step labelled — rather than looping forever or
   aborting the whole run.

The whole thing runs in-process against a temporary on-disk SQLite database.

## Reference implementation

```python
"""Durable, resumable, idempotent multi-step workflow with bounded retries
and a dead-letter path. Hand-rolled on SQLite (no engine).

Stdlib only. Python 3.11+. Run: python3 exercise_02.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sqlite3
import tempfile
from dataclasses import dataclass, field, asdict


class CrashInjected(Exception):
    """Simulates a process crash at a chosen point in the run."""


class PermanentFailure(Exception):
    """A step that will never succeed; destined for the dead-letter store."""


@dataclass
class WorkflowState:
    run_id: str
    pending: list[str]
    completed: dict[str, dict] = field(default_factory=dict)
    dead_letter: dict[str, str] = field(default_factory=dict)
    status: str = "running"          # running | done | failed


# --- Durable store (SQLite) -------------------------------------------------


class Store:
    """SQLite-backed durable store.

    `workflow_state` holds one JSON blob per run, written in a single
    transaction (atomic checkpoint). `effects` is the idempotency ledger:
    its primary key (run_id, step_id) makes a repeated side effect a no-op.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS workflow_state ("
            " run_id TEXT PRIMARY KEY, blob TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS effects ("
            " run_id TEXT, step_id TEXT, payload TEXT,"
            " PRIMARY KEY (run_id, step_id))"
        )
        self._conn.commit()

    def save(self, state: WorkflowState) -> None:
        """Atomic checkpoint: the whole state committed in one transaction.

        A JSON-file variant would write a temp file and os.replace(tmp, path);
        here the DB transaction gives the same all-or-nothing guarantee.
        """
        blob = json.dumps(asdict(state))
        with self._conn:                       # BEGIN ... COMMIT (or ROLLBACK)
            self._conn.execute(
                "INSERT INTO workflow_state(run_id, blob) VALUES(?, ?)"
                " ON CONFLICT(run_id) DO UPDATE SET blob=excluded.blob",
                (state.run_id, blob),
            )

    def load(self, run_id: str) -> WorkflowState | None:
        row = self._conn.execute(
            "SELECT blob FROM workflow_state WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return WorkflowState(**json.loads(row[0]))

    def apply_effect_idempotent(self, run_id: str, step_id: str,
                                payload: str) -> bool:
        """Idempotent side effect: returns True iff this is the first apply."""
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO effects(run_id, step_id, payload)"
                " VALUES(?, ?, ?)",
                (run_id, step_id, payload),
            )
        return cur.rowcount == 1               # 0 => already applied (no dup)

    def apply_effect_unsafe(self, run_id: str, step_id: str,
                            payload: str) -> None:
        """Deliberately NON-idempotent: appends a fresh row every call.

        Used only to demonstrate the duplication hazard before the fix. The
        effects PK would normally block this, so we write to a separate ledger.
        """
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS effects_unsafe ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " run_id TEXT, step_id TEXT, payload TEXT)"
            )
            self._conn.execute(
                "INSERT INTO effects_unsafe(run_id, step_id, payload)"
                " VALUES(?, ?, ?)",
                (run_id, step_id, payload),
            )

    def effect_count(self, run_id: str, step_id: str, *, unsafe: bool) -> int:
        table = "effects_unsafe" if unsafe else "effects"
        return self._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE run_id=? AND step_id=?",
            (run_id, step_id),
        ).fetchone()[0]

    def close(self) -> None:
        self._conn.close()


# --- Retry with backoff + jitter --------------------------------------------


async def with_retry(fn, *, attempts: int = 4, base: float = 0.05,
                     cap: float = 0.5, rng: random.Random) -> dict:
    """Retry transient failures; re-raise the last error when attempts run out.

    PermanentFailure is not retried — it raises immediately so the caller can
    dead-letter it without burning the retry budget. CrashInjected is not
    retried either: a simulated crash must propagate, not be papered over by a
    retry (otherwise the unsafe side effect would be applied once per attempt).
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await fn()
        except (PermanentFailure, CrashInjected):
            raise                              # never retry these
        except Exception as exc:               # transient
            last = exc
            if i == attempts - 1:
                break
            delay = min(cap, base * 2 ** i) + rng.uniform(0, base)
            await asyncio.sleep(delay)
    assert last is not None
    raise last


# --- The workflow -----------------------------------------------------------


@dataclass
class StepSpec:
    """Describes how a single step behaves, for deterministic demos."""

    step_id: str
    transient_failures: int = 0    # raise this many times, then succeed
    permanent: bool = False        # always raise -> dead-letter
    idempotent: bool = True        # use the safe effect path?


class Workflow:
    def __init__(self, store: Store, specs: dict[str, StepSpec],
                 rng: random.Random) -> None:
        self.store = store
        self.specs = specs
        self.rng = rng
        self._attempt_counts: dict[str, int] = {}

    async def _do_step(self, state: WorkflowState, step_id: str,
                       crash_before_checkpoint: bool) -> dict:
        spec = self.specs[step_id]
        await asyncio.sleep(0.01)                       # "expensive work"

        # Transient/permanent failure modelling (consumed by with_retry).
        seen = self._attempt_counts.get(step_id, 0)
        self._attempt_counts[step_id] = seen + 1
        if spec.permanent:
            raise PermanentFailure(f"{step_id} can never succeed")
        if seen < spec.transient_failures:
            raise RuntimeError(f"{step_id} transient (attempt {seen + 1})")

        # The side effect.
        payload = json.dumps({"step": step_id, "run": state.run_id})
        if spec.idempotent:
            first = self.store.apply_effect_idempotent(
                state.run_id, step_id, payload)
        else:
            self.store.apply_effect_unsafe(state.run_id, step_id, payload)
            first = True

        if crash_before_checkpoint:
            # Effect is durable, but the checkpoint has NOT happened yet:
            # this is the idempotency hazard window.
            raise CrashInjected(f"crash after {step_id} effect, before checkpoint")

        return {"step_id": step_id, "first_apply": first}

    async def run(self, state: WorkflowState, *, crash_after: str | None = None,
                  crash_before_checkpoint: bool = False) -> WorkflowState:
        """Execute pending steps in order, checkpointing after each."""
        for step_id in list(state.pending):       # iterate a copy; we mutate
            try:
                result = await with_retry(
                    lambda sid=step_id: self._do_step(
                        state, sid,
                        crash_before_checkpoint and sid == crash_after),
                    rng=self.rng,
                )
            except PermanentFailure as exc:
                state.dead_letter[step_id] = str(exc)   # route, don't loop
                state.pending.remove(step_id)
                self.store.save(state)                  # checkpoint the routing
                continue
            except CrashInjected:
                # Effect already applied but NOT checkpointed: re-raise so the
                # caller can simulate the crash. `pending` still has step_id.
                raise

            state.completed[step_id] = result
            state.pending.remove(step_id)
            self.store.save(state)                      # atomic checkpoint

            if crash_after == step_id and not crash_before_checkpoint:
                # Clean crash: state IS checkpointed, so resume runs only the
                # remaining steps.
                raise CrashInjected(f"crash after {step_id} checkpoint")

        state.status = "failed" if state.dead_letter else "done"
        self.store.save(state)
        return state


def resume(store: Store, run_id: str) -> WorkflowState:
    """Load durable state exactly as a fresh process would on restart."""
    state = store.load(run_id)
    if state is None:
        raise KeyError(f"no such run: {run_id}")
    return state


# --- Demonstrations ---------------------------------------------------------


async def demo_crash_and_resume(store: Store) -> None:
    print("=== Task 3: crash after step 6, resume runs only 7-10 ===")
    run_id = "run-resume"
    steps = [f"s{i}" for i in range(1, 11)]
    specs = {s: StepSpec(s) for s in steps}
    state = WorkflowState(run_id, pending=list(steps))
    store.save(state)

    wf = Workflow(store, specs, random.Random(1))
    try:
        await wf.run(state, crash_after="s6")           # checkpointed crash
    except CrashInjected as exc:
        print(f"  crashed: {exc}")

    reloaded = resume(store, run_id)
    print(f"  on restart: completed={sorted(reloaded.completed)} "
          f"pending={reloaded.pending}")

    wf2 = Workflow(store, specs, random.Random(1))      # fresh worker
    ran_before = set(reloaded.completed)
    final = await wf2.run(reloaded)
    newly = set(final.completed) - ran_before
    print(f"  resumed and finished: status={final.status} "
          f"newly_run={sorted(newly)} "
          f"steps_1_6_reran={any(s in newly for s in steps[:6])}")


async def demo_idempotency(store: Store) -> None:
    print("\n=== Task 4: idempotency hazard, then the fix ===")

    # Hazard: NON-idempotent effect, crash before checkpoint -> step re-runs.
    run_id = "run-hazard"
    specs = {"s1": StepSpec("s1", idempotent=False)}
    state = WorkflowState(run_id, pending=["s1"])
    store.save(state)
    try:
        await Workflow(store, specs, random.Random(2)).run(
            state, crash_after="s1", crash_before_checkpoint=True)
    except CrashInjected:
        pass
    reloaded = resume(store, run_id)                    # s1 still pending
    await Workflow(store, specs, random.Random(2)).run(reloaded)
    print(f"  NON-idempotent effect count for s1 = "
          f"{store.effect_count(run_id, 's1', unsafe=True)} (duplicate!)")

    # Fix: idempotent effect, same crash-before-checkpoint scenario.
    run_id = "run-fixed"
    specs = {"s1": StepSpec("s1", idempotent=True)}
    state = WorkflowState(run_id, pending=["s1"])
    store.save(state)
    try:
        await Workflow(store, specs, random.Random(2)).run(
            state, crash_after="s1", crash_before_checkpoint=True)
    except CrashInjected:
        pass
    reloaded = resume(store, run_id)
    await Workflow(store, specs, random.Random(2)).run(reloaded)
    print(f"  idempotent effect count for s1 = "
          f"{store.effect_count(run_id, 's1', unsafe=False)} (exactly one)")


async def demo_retry_and_dead_letter(store: Store) -> None:
    print("\n=== Task 5: bounded retry succeeds; permanent step dead-letters ===")
    run_id = "run-retry"
    specs = {
        "ok": StepSpec("ok"),
        "flaky": StepSpec("flaky", transient_failures=2),   # fails twice, then ok
        "broken": StepSpec("broken", permanent=True),       # never succeeds
        "tail": StepSpec("tail"),
    }
    state = WorkflowState(run_id, pending=["ok", "flaky", "broken", "tail"])
    store.save(state)
    final = await Workflow(store, specs, random.Random(3)).run(state)
    print(f"  completed={sorted(final.completed)} "
          f"dead_letter={final.dead_letter} status={final.status}")
    print("  'flaky' eventually succeeded after retries; "
          "'broken' is in dead-letter, not looping.")


async def demo_status_query(store: Store) -> None:
    print("\n=== Acceptance: status is queryable for any run_id ===")
    for run_id in ("run-resume", "run-retry"):
        st = store.load(run_id)
        print(f"  {run_id}: status={st.status} "
              f"completed={len(st.completed)} pending={len(st.pending)} "
              f"dead_letter={len(st.dead_letter)}")


async def main() -> None:
    db_path = os.path.join(tempfile.mkdtemp(), "workflow.db")
    store = Store(db_path)
    try:
        await demo_crash_and_resume(store)
        await demo_idempotency(store)
        await demo_retry_and_dead_letter(store)
        await demo_status_query(store)
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## Meeting the acceptance criteria

- **Crash after step 6 resumes and runs only 7–10.** `demo_crash_and_resume`
  injects a checkpointed crash after `s6`, reloads state, and prints
  `steps_1_6_reran=False` — the resumed worker runs only the steps still in
  `pending`. Completed steps are skipped because `run()` iterates `pending`,
  which no longer contains them.
- **The checkpoint write is atomic.** `Store.save` commits inside a `with
  self._conn:` block (`BEGIN`/`COMMIT`, auto-`ROLLBACK` on error); a crash
  mid-commit rolls back to the previous committed blob, never a half-written
  one. SQLite's transaction is the database equivalent of write-temp-then-
  rename, and the docstring marks where a JSON `os.replace` would slot in.
- **The idempotency hazard is shown and fixed.** `demo_idempotency` crashes
  *before* the checkpoint with a non-idempotent effect and prints an effect
  count of 2 (the duplicate). The fixed run uses the `INSERT OR IGNORE` ledger
  keyed on `(run_id, step_id)` and prints exactly 1 after the identical crash
  and resume.
- **Bounded retry + dead-letter.** `demo_retry_and_dead_letter` has a `flaky`
  step that fails twice then succeeds via `with_retry` (exponential backoff +
  jitter, capped at `attempts`), and a `broken` step that raises
  `PermanentFailure`, is routed to the `dead_letter` table, and the run
  continues to `tail` rather than looping forever.
- **Status is queryable at any time.** `demo_status_query` reads `status`,
  `completed`, `pending`, and `dead_letter` straight from the durable store for
  arbitrary `run_id`s, exactly as an external monitor would.

## Common pitfalls

- **Applying the side effect after the checkpoint instead of before.** It feels
  safer, but then a crash between checkpoint and effect *loses* the effect on
  resume (the step is marked done, so it never re-runs). The correct ordering
  is effect-then-checkpoint, made safe by idempotency — never "checkpoint then
  effect".
- **Idempotency keyed on the wrong thing.** Keying the upsert on step content
  or a timestamp instead of `(run_id, step_id)` lets a legitimately re-run step
  create a second row. The key must be the stable workflow coordinate.
- **Unbounded or un-jittered retries.** Retrying forever turns a permanent
  failure into an infinite loop; retrying without jitter synchronizes every
  worker's retries into a thundering herd against the same downstream. Cap the
  attempts and add jitter — both are in `with_retry`.
- **Treating a bare JSON file write as atomic.** `open(path, "w")` truncates
  first; a crash mid-write corrupts the file. You must write to a temp file and
  `os.replace` (atomic on POSIX and Windows), or use a DB transaction as here.
- **Mutating `pending` while iterating it.** `run()` iterates `list(pending)` (a
  copy) precisely so removing the just-completed step doesn't skip the next one.

## Verification

```bash
python3 exercise_02.py
```

Confirm in the printed output:

1. Task 3 — `steps_1_6_reran=False` and `status=done`; the resumed run executed
   only `s7`–`s10`.
2. Task 4 — the non-idempotent effect count is `2` (hazard) and the idempotent
   count is `1` (fixed) for the same crash-before-checkpoint scenario.
3. Task 5 — `flaky` lands in `completed`, `broken` lands in `dead_letter`, and
   `status=failed` (run finished without looping).
4. Status query — `pending`/`completed`/`dead_letter`/`status` print for each
   `run_id`.

The database lives in a fresh temp directory each run, so repeated invocations
start clean and stay deterministic (every RNG is seeded).
