# Reflection — exercise-03

## Stopping point (Task 5): the abstraction I deliberately did NOT add

I stopped at **four small modules and two I/O interfaces**. The abstraction I was
most tempted to add and declined is a **tool registry / plugin system** — a
`ToolRegistry` that tools register into, with a decorator API, so "adding a tool
is just dropping a file." I did not build it.

Applying YAGNI/KISS: there are exactly two tools (`get_weather`, `add`), both
trivial, both in one adapter. A registry would be speculative generality — a layer
every future reader must learn, in exchange for flexibility no present pressure
demands. The concrete future event that would justify it: a *third-party* or
*dynamically discovered* tool set, or tools owned by a different team that must
register without editing `clients.py`. Until a second real source of tools exists,
the registry is complexity with no offsetting capability — the most expensive code
in the repo.

The seams I *did* add each relieve a named, present pressure: the `ModelClient`
interface is what lets `FakeModel` drive the loop with no network (it earns its
keep in `test_loop.py`); the `ToolTransport` interface is what lets `RaisingTools`
exercise the partial-failure path. Those pass the test "name the concrete pressure
this relieves." The registry fails it.

## 1. Which step turned characterization tests red first, and the coupling it exposed

Introducing the `ModelClient` interface (Task 3). The first cut had the loop still
reaching for a module-global client, so wiring in the adapter changed *which*
client answered and the snapshot shifted by one message. That localized the hidden
coupling instantly: the prototype's loop depended on a **module-global `_client`**,
not on a parameter. Behavior was tied to import-time state. The red run pointed
exactly at the global; passing the client in as an argument made the test green and
removed the coupling.

## 2. What prevented testing the loop's partial-failure path before

In the prototype, `_run_tool` raising propagated straight out of `run_agent` and
crashed the call, and the loop was welded to the concrete demo client and the
inline `_run_tool` dispatch. There was no seam to inject a *failing* tool without
editing the loop's source, and no way to drive the model toward calling that tool
deterministically. You could not reach the partial-failure branch because the
branch did not exist as a reachable, isolatable thing — it was an uncaught
exception fused into the loop body.

## 3. The abstraction I was most tempted to add for "flexibility"

Same as the stopping-point note: the tool registry. The honest temptation was "what
if we have lots of tools later?" — but "later" is not a present pressure, and the
wrong abstraction is harder to remove than the duplication it replaces. I will add
it the day a second, independently-owned source of tools is real, behind the
existing `ToolTransport` seam, which is already thin enough to extend then.
