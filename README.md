# Senior Agentic AI Engineer — Solutions Repository

<!-- aicg:site-banner -->
> 🎓 Part of the free, open-source **AI Career Curriculum** ecosystem — [Infrastructure](https://github.com/ai-infra-curriculum) · [ML Engineering](https://github.com/ml-engineering-curriculum) · [AI Engineering](https://github.com/ai-engineering-curriculum) · [Governance](https://github.com/ai-governance-curriculum). Live cohorts &amp; team programs: **[ai-infra-curriculum.github.io](https://ai-infra-curriculum.github.io/)**.
<!-- /aicg:site-banner -->

> **Reference solutions for every exercise in the Senior Agentic AI Engineer (L40) track.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Modules](https://img.shields.io/badge/modules-5-326CE5.svg)](#repository-structure)
[![Reference solutions](https://img.shields.io/badge/solutions-15-success.svg)](#modules)

## 🎯 Overview

This repository holds the **reference solutions** for the paired
[`ai-infra-senior-agentic-ai-engineer-learning`](https://github.com/ai-engineering-curriculum/senior-agentic-ai-engineer-learning)
track. The Senior Agentic AI Engineer rung sits at **L40**, and the bar is
different from earlier tracks: the module exercises grade **judgment over
mechanics**. A senior is expected to choose between implementations of a known
pattern, defend the tradeoff in writing, own a subsystem someone else can be
paged for, and lead the people building alongside them.

The solutions here are built to match that bar. Each one pairs three things:

- ✅ **Runnable code** — complete, self-contained Python 3.11+ references
  (standard library plus `pytest`; no live model, no network), so every claim
  the walkthrough makes is something you can execute.
- ⚖️ **Judgment and tradeoffs** — every solution shows *why* it is shaped the
  way it is: the option that was rejected, the seam left reversible, the
  stopping point, the cost of going further.
- 🧭 **Leadership artifacts** — the senior-level decision and operability
  documents a staff reviewer actually looks for: ADRs, failure policies,
  runbooks, RFCs, golden-path templates, SLO definitions, incident postmortems,
  and review rubrics.

Together that means a reader can not only see *what* a passing answer looks like,
but reconstruct the senior reasoning that produced it.

> **Status**: ✅ Reference solutions complete for all 15 module exercises across
> mod-401 through mod-405. The two capstone projects (project-401, project-402)
> are scaffolded and land on an upcoming autonomous cycle. AI-assisted content
> is under ongoing human review.

## Repository Structure

```text
ai-infra-senior-agentic-ai-engineer-solutions/
├── modules/
│   ├── mod-401-agent-systems-in-practice/   # contract-first ownership, ADRs, refactors
│   ├── mod-402-eval-observability-infra/    # eval harness, tracing, regression gates
│   ├── mod-403-multi-agent-at-scale/        # orchestration, durable execution, budgets
│   ├── mod-404-reliability-cost-incident/   # agentic SLOs, cost controls, incidents
│   └── mod-405-technical-leadership/        # review standards, paved roads, sequencing
├── projects/
│   ├── project-401-production-subsystem/    # capstone (scaffolded)
│   └── project-402-reliability-hardening/   # capstone (scaffolded)
└── README.md                                # this file
```

Each `modules/mod-4XX-*/` directory has a module `README.md` index plus one
sub-directory per exercise. In **mod-401**, each exercise ships as a real Python
package — source, an injected-seam design, and a passing `pytest` suite (45
passing tests across the module). In **mod-402 through mod-405**, each exercise
`README.md` is a self-contained annotated walkthrough whose `## Reference
implementation` block is a complete, copy-runnable file (or, for the operational
and leadership exercises, the completed runbook / postmortem / RFC artifact), and
whose `## Verification` section names the expected output.

## Modules

| Module | Solutions |
| --- | --- |
| [mod-401 — Agent Systems in Practice](modules/mod-401-agent-systems-in-practice/README.md) | 3 exercises: own a tool-executor behind a frozen typed contract (stub + injected-seam executor + idempotency-store ADR); make it operable (failure policy, telemetry, health, runbook, build-vs-buy ADRs); refactor a fused prototype into layers with behavior held constant via characterization tests. Runnable packages, 45 passing tests. |
| [mod-402 — Eval & Observability Infrastructure](modules/mod-402-eval-observability-infra/README.md) | 3 exercises: an agent-agnostic eval harness (one `Grader` protocol, trajectory/tool-call/LLM-judge families, versioned JSONL dataset, JSON `EvalReport`); a fleet tracing standard (GenAI-conventions wrapper, error-biased sampling, per-`service.name` dashboards); a CI regression gate turning eval + trace stats into a blocking merge decision. |
| [mod-403 — Multi-Agent Systems at Scale](modules/mod-403-multi-agent-at-scale/README.md) | 3 exercises: orchestration under load (bounded concurrency, backpressure, per-hop timeouts, graceful degradation); durable execution (checkpointed state, crash-and-resume, idempotent side effects, bounded retries + dead-letter); token and latency budgets (per-role cost + critical-path instrumentation, difficulty routing, context caching, soft/hard caps). |
| [mod-404 — Reliability, Cost & Incident Response](modules/mod-404-reliability-cost-incident/README.md) | 3 exercises: agentic SLOs (quality SLIs as good/valid ratios, Wilson-interval success SLI, error budgets, burn-rate + baseline-drift alerts); cost controls (per-run budget guard and per-tenant circuit breaker, both fail-closed, feeding a p99-cost SLI); incident response (runaway-loop drill, containment levers, completed runbook, blameless postmortem). |
| [mod-405 — Technical Leadership for Agentic Teams](modules/mod-405-technical-leadership/README.md) | 3 exercises: an agent-PR review rubric + severity-ordered review that finds the CRITICAL tool-authority-meets-untrusted-input path; a paved-road RFC + golden-path template wiring the safe defaults; a one-page delivery plan that scopes, de-risks first, and ties decision points to measured go/pivot/kill signals. |

## How to Use

The solutions assume you have already attempted the matching exercise in the
learning repo. They are most valuable as a comparison and a model, not a
shortcut.

1. **Attempt the exercise first** in
   [`ai-infra-senior-agentic-ai-engineer-learning`](https://github.com/ai-engineering-curriculum/senior-agentic-ai-engineer-learning),
   including the written artifacts — the ADR, the runbook, the RFC. At L40 the
   writing *is* the work.
2. **Run the reference.** For mod-401, from any exercise directory:

   ```bash
   cd modules/mod-401-agent-systems-in-practice/exercise-01-architecture-to-implementation
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
   ```

   For mod-402 through mod-405, copy the `## Reference implementation` block from
   the exercise `README.md` into a `.py` file and run it (mod-402 exercise-02 is
   the only one needing third-party packages — `pip install opentelemetry-api
   opentelemetry-sdk`); compare against the `## Verification` section.
3. **Diff your judgment, not just your code.** Read the `## Approach` and the
   tradeoff/stopping-point notes, then ask where your decision diverged and
   whether you could defend the difference. That gap is the senior signal the
   track is training.
4. **Reuse the artifacts as templates.** The ADRs, failure policy, runbook, RFC,
   golden-path template, SLO definitions, and postmortem are written to be
   adapted into real systems, not just graded.

## Paired Learning Repository

This repo is the answer key. The exercises, stubs, and concept chapters live in
the paired learning repository — start there:

- **[ai-infra-senior-agentic-ai-engineer-learning](https://github.com/ai-engineering-curriculum/senior-agentic-ai-engineer-learning)**
  — learning materials, exercise specs, and acceptance criteria for the Senior
  Agentic AI Engineer (L40) track.

## Related Repositories

- **[ai-infra-agentic-ai-engineer-solutions](https://github.com/ai-engineering-curriculum/agentic-ai-engineer-solutions)**
  — the L30 rung below this track on the agentic ladder.
- **[ai-infra-systems-architect-solutions](https://github.com/ai-infra-curriculum/ai-infra-systems-architect-solutions)**
  — the L48 rung above this track on the agentic ladder.
- **[ai-infra-curriculum](https://github.com/ai-infra-curriculum)** — the full
  curriculum organization, with every learning/solutions track.

---

<!-- aicg:maintained-by -->
Maintained by [VeriSwarm.ai](https://veriswarm.ai)
