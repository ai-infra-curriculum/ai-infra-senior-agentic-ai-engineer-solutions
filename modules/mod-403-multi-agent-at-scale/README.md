# mod-403-multi-agent-at-scale — Solutions

Reference solutions for the **Multi-Agent Systems at Scale** module (~L40). Each
exercise directory below contains an annotated, runnable Python reference
implementation plus a walkthrough of how it meets the acceptance criteria.

## Index

- [exercise-01-orchestration-under-load](exercise-01-orchestration-under-load/README.md)
  — bounded concurrency, backpressure, per-hop timeouts, and graceful
  degradation for an orchestrator-worker system under load.
- [exercise-02-durable-execution-in-production](exercise-02-durable-execution-in-production/README.md)
  — checkpointed workflow state, crash-and-resume, idempotent side effects, and
  bounded retries with a dead-letter path.
- [exercise-03-token-and-latency-budgets](exercise-03-token-and-latency-budgets/README.md)
  — per-role cost and critical-path latency instrumentation, difficulty-based
  routing, context caching, and soft/hard budget caps.

## Running the references

Every reference implementation is a single self-contained Python file embedded
in its exercise README. It targets Python 3.11+ and uses only the standard
library (`asyncio`, `dataclasses`, `sqlite3`, `statistics`) — no third-party
packages, no network, no real model provider. Copy the fenced block into a
`.py` file and run it:

```bash
python3 exercise_01.py
```

Each script ends in a `main()` demonstration that prints the recorded numbers
the acceptance criteria ask for.
