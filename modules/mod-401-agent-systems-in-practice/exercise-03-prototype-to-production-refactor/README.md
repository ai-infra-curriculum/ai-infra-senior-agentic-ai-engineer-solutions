# mod-401-agent-systems-in-practice/exercise-03 — Solution

## Approach

The exercise is a refactor under a hard constraint: **observable behavior must
not change.** So the solution keeps the original prototype in the tree
(`prototype/prototype.py`, unchanged) and builds the layered version beside it
(`agent/`). The characterization tests then assert the refactored agent produces
*byte-identical* output to the prototype on representative inputs — the strongest
possible proof that the restructuring changed structure, not behavior.

The work follows the chapter's one-concern-at-a-time discipline:

1. **Pin behavior first** — a `ScriptedModel`/`FakeModel` removes nondeterminism;
   snapshots of the prototype's output on three representative inputs are frozen.
   A paired test confirms each snapshot still matches the *original* prototype, so
   the snapshots are pinned to real behavior rather than invented.
2. **Extract config** — keys/model/limits move into a typed `AgentConfig.from_env`.
   Removing the hard-coded key is both the first refactor step and a security fix;
   a test asserts the secret never reappears in the refactored source.
3. **Introduce I/O interfaces** — `ModelClient` and `ToolTransport` protocols, with
   real adapters that wrap the prototype's exact demo behavior so snapshots stay
   green.
4. **Lift the loop** — the reason-act loop moves into `agent.py`, depending only on
   interfaces and pure `domain.py` functions. *Now* the previously-impossible tests
   exist: tool-call order on a scripted fake, and a partial-failure path.
5. **Justify the stopping point** — `NOTES.md` names one abstraction (a tool
   registry) deliberately declined under YAGNI/KISS.

## Reference implementation

```text
exercise-03-prototype-to-production-refactor/
├── conftest.py
├── NOTES.md                       # reflection + stopping-point justification
├── prototype/
│   └── prototype.py               # BEFORE: everything fused, hard-coded key
└── agent/                         # AFTER: layered + tested
    ├── config.py                  # typed config from env; no secrets in source
    ├── clients.py                 # ModelClient + ToolTransport interfaces + adapters
    ├── agent.py                   # the reason-act loop; interfaces only
    ├── domain.py                  # pure parse / shape functions
    └── tests/
        ├── fakes.py               # ScriptedModel (replay) + recording/raising tools
        ├── test_characterization.py  # refactored output == prototype output
        ├── test_loop.py           # NEW: tool order, partial failure, step limit
        ├── test_domain.py         # pure-function tests
        └── test_config.py         # env loading + fail-fast on missing key
```

The behavior-preservation proof is the centerpiece — it runs the prototype and the
refactored agent through the same frozen expectations:

```python
EXPECTED = {
    "What is the weather in Phoenix?": {
        "answer": "Result: phoenix: 72F sunny",
        "trace": [{"tool": "get_weather", "args": {"city": "phoenix"}}],
    },
    ...
}

def test_refactored_matches_frozen_snapshot(question):
    result = refactored_run(question, model=DemoModelAdapter(_config()),
                            tools=LocalToolTransport(), config=_config())
    assert result == EXPECTED[question]

def test_snapshot_still_matches_prototype(question):
    assert prototype_run(question) == EXPECTED[question]   # snapshots pinned to reality
```

The payoff lands in `agent.py`, where the loop is finally isolated enough to test
the partial-failure path that was an uncatchable exception in the prototype:

```python
try:
    observation = tools.run(decision.tool, decision.args)
except Exception as exc:                       # untestable in the prototype
    observation = f"error: {type(exc).__name__}"  # becomes an observation, not a crash
```

Self-scored refactor rubric:

```text
| Property                          | Before | After |
| --------------------------------- | ------ | ----- |
| Secrets out of source             |   no   |  yes  |
| Loop testable without live API    |   no   |  yes  |
| Concerns in separate layers       |   no   |  yes  |
| Behavior unchanged (char. tests)  |   —    | green |
| Partial-failure path covered      |   no   |  yes  |
```

## Meeting the acceptance criteria

| Criterion | Where it is met |
| --- | --- |
| Characterization tests stay green through the final commit — behavior provably unchanged | `test_characterization.py` asserts refactored output equals the prototype's, parametrized over three inputs |
| No hard-coded secret; config loads from the environment | `config.py` (`AgentConfig.from_env`); `test_config.py` + `test_no_secret_in_refactored_source` |
| The loop depends on a `ModelClient` interface and runs under a fake with no network | `agent.py` takes `model: ModelClient`; `test_loop.py` drives it with `ScriptedModel` |
| New tests assert tool-call order and a partial-failure path | `test_loop.py` — `test_tool_call_order_is_exactly_as_scripted`, `test_partial_failure_path_is_handled_not_crashed` |
| Stopping-point note names a declined abstraction, justified by YAGNI/KISS | `NOTES.md` — the tool registry, with the concrete future event that would justify it |

Stretch goals: a second `ModelClient` is trivial to add behind the existing
interface (the `DemoModelAdapter` is the template, and `test_loop.py` already
proves the loop is client-agnostic); the pure `domain.parse_decision` is the
natural target for a property-based test; the suite runs in well under a second
because `FakeModel` removed the live API from the loop.

## Common pitfalls

- **"Improving" outputs while refactoring.** Changing a prompt or a parse so the
  answer is "better" is a rewrite wearing a refactor's clothes — and it turns the
  characterization tests red, hiding whether you also broke something. Behavior is
  held *exactly* constant; improvement is a separate day's work.
- **Snapshots invented instead of captured.** If `EXPECTED` were hand-written to
  match the new code, it would prove nothing. `test_snapshot_still_matches_prototype`
  pins the snapshots to the *original* prototype, so they characterize real
  behavior.
- **Adapters that subtly change behavior.** The `DemoModelAdapter` and
  `LocalToolTransport` reproduce the prototype's logic verbatim. A "cleaner"
  rewrite of the demo model's parsing would shift a snapshot and correctly fail.
- **Leaving the secret reachable.** Extracting config but leaving a fallback
  default key in source defeats the security half of the task. The config fails
  fast when `AGENT_API_KEY` is absent — there is no in-source default.
- **Over-refactoring past the stopping point.** Twelve interfaces and a plugin
  registry for two tools is the over-engineering the complexity rules warn
  against. Stop when the parts that genuinely need swapping/testing are reachable;
  `NOTES.md` defends exactly where that line was drawn.

## Verification

```bash
cd exercise-03-prototype-to-production-refactor
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

Expected: `17 passed`. Standard library plus `pytest` only;
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` only sidesteps unrelated globally-installed
pytest plugins. No live model or network is used.
