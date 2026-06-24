# mod-401-agent-systems-in-practice — Solutions

Reference solutions for the Senior Agentic AI Engineer module *Implementing Agent
Systems from an Architecture*. The module grades judgment over mechanics: how you
choose between implementations of known patterns, turn a prototype into something
a team can own, and defend a tradeoff in writing. Every solution pairs runnable
code with the decision artifacts (ADRs, failure policies, runbooks, stopping-point
notes) that distinguish a senior implementation.

All exercises are Python 3.11+, standard library plus `pytest` only — no live
model or network. Each runs with:

```bash
cd <exercise-dir>
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

(`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` only sidesteps unrelated globally-installed
pytest plugins; the suites need no third-party packages.)

## Exercises

| Exercise | Focus | Key artifacts | Tests |
| --- | --- | --- | --- |
| [exercise-01: Architecture to implementation](exercise-01-architecture-to-implementation/README.md) | Own the tool-executor box behind a frozen, typed interface | contract + stub + injected-seam executor + idempotency-store ADR | 11 passing |
| [exercise-02: Subsystem ownership](exercise-02-subsystem-ownership/README.md) | Make the executor *operable*: failure policy, telemetry, health, runbook | `FAILURE_POLICY.md`, `RUNBOOK.md`, two build-vs-buy ADRs (docs generated from policy constants) | 17 passing |
| [exercise-03: Prototype to production refactor](exercise-03-prototype-to-production-refactor/README.md) | Refactor a fused prototype into layers with behavior held constant | before/after split, characterization tests, stopping-point note | 17 passing |

## How the exercises build on each other

Exercise-01 produces the tool-executor behind a stable interface. Exercise-02
takes that same subsystem and adds the operability that makes someone willing to
be paged for it. Exercise-03 is the inverse direction — starting from a fused
spike and reaching, through safe refactoring, the kind of layered, testable
subsystem the first two exercises started from. Together they cover the senior arc
this module trains: read an architecture as a contract, own a box end to end, and
inherit a teammate's prototype without breaking it.
