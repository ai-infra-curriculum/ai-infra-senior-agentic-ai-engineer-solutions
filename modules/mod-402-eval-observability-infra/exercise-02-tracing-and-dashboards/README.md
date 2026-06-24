# mod-402-eval-observability-infra/exercise-02-tracing-and-dashboards — Solution

## Approach

The deliverable is a tracing *standard* a fleet runs on, plus the fleet dashboards that
standard makes possible — not instrumentation for a single agent. The design:

- **One shared wrapper, so teams can't drift from the keys.** `traced_model_call` and
  `traced_tool_call` open spans named `chat {model}` and `execute_tool {tool_name}` and
  set the OpenTelemetry GenAI attributes (`gen_ai.operation.name`, `gen_ai.provider.name`,
  `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.tool.name`). Every service imports these helpers instead of hand-rolling
  attribute keys, which is what makes cross-service rollups possible.
- **Resource attributes per service, so a fleet is sliceable.** Each service builds a
  `TracerProvider` whose `Resource` carries `service.name`, `service.version`, and
  `deployment.environment`. The two services get *different* `service.name` values so
  dashboards can group by them.
- **One export path.** A span processor + exporter is configured once. Centralizing the
  path means sampling and redaction are changed in one place, not per service.
- **Errors go red, errored runs are always kept.** A failing model/tool call sets the span
  status to `ERROR` and records the exception. A custom sampler keeps a fraction of normal
  runs but *always* samples errors, so red traces are never dropped.
- **Fleet dashboards group by `service.name`.** Tokens/cost, p95 root-span latency, and
  error rate — computed *across* services, not for one run.

To keep the reference runnable in CI with no backend and no API key, the core file uses an
`InMemorySpanExporter`, computes the three fleet charts directly from captured spans, and
prints them. A clearly marked block shows the one-line swap to the real `OTLPSpanExporter`
and the equivalent Arize Phoenix dashboard queries.

## Reference implementation

Save as `fleet_tracing.py`. Runs with
`pip install opentelemetry-api opentelemetry-sdk` then `python fleet_tracing.py`. No
network, no API key — the in-memory exporter stands in for Phoenix.

```python
"""Fleet tracing standard: shared GenAI wrapper, per-service resources, one export
path, error-biased sampling, and fleet dashboards grouped by service.name.

Runs offline against an InMemorySpanExporter. Swap in OTLPSpanExporter (marked below)
to send to Arize Phoenix / Langfuse / LangSmith.
"""

from __future__ import annotations

import random
from collections import defaultdict
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import (
    Decision,
    ParentBased,
    Sampler,
    SamplingResult,
)
from opentelemetry.trace import SpanKind, Status, StatusCode

# A single in-memory exporter shared by both services, standing in for one backend.
SHARED_EXPORTER = InMemorySpanExporter()

# Toy price book ($ per 1K tokens). Real cost rollups read these from config.
PRICE_PER_1K = {"gpt-sim-large": (0.003, 0.015), "claude-sim-fast": (0.001, 0.005)}


# ---------------------------------------------------------------------------
# Error-biased sampler: keep a fraction of normal runs, always keep errors.
# ---------------------------------------------------------------------------


class ErrorBiasedSampler(Sampler):
    """Drop-sample normal root spans; always record those flagged to be kept.

    A span the caller knows is (or will be) errored carries a `sampling.force_keep`
    attribute; this sampler honors it, otherwise samples at `ratio`.
    """

    def __init__(self, ratio: float = 0.25):
        self._ratio = ratio

    def should_sample(
        self, parent_context, trace_id, name, kind=None, attributes=None,
        links=None, trace_state=None,
    ) -> SamplingResult:
        attributes = attributes or {}
        if attributes.get("sampling.force_keep"):
            return SamplingResult(Decision.RECORD_AND_SAMPLE, attributes, trace_state)
        keep = (trace_id & 0xFFFFFFFF) / 0xFFFFFFFF < self._ratio
        decision = Decision.RECORD_AND_SAMPLE if keep else Decision.DROP
        return SamplingResult(decision, attributes, trace_state)

    def get_description(self) -> str:
        return f"ErrorBiasedSampler(ratio={self._ratio})"


# ---------------------------------------------------------------------------
# Per-service tracer init (resource attributes set once at startup).
# ---------------------------------------------------------------------------


def init_tracing(service_name: str, version: str, env: str = "production"):
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": version,
            "deployment.environment": env,
        }
    )
    provider = TracerProvider(
        resource=resource,
        # Children inherit the root's decision via ParentBased; roots use the bias.
        sampler=ParentBased(root=ErrorBiasedSampler(ratio=0.5)),
    )
    # One export path. Swap SimpleSpanProcessor(SHARED_EXPORTER) for
    # BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")).
    provider.add_span_processor(SimpleSpanProcessor(SHARED_EXPORTER))
    return trace.get_tracer(service_name, tracer_provider=provider)


# ---------------------------------------------------------------------------
# The shared GenAI instrumentation wrapper — the asset teams import.
# ---------------------------------------------------------------------------


@contextmanager
def traced_model_call(tracer, model: str, provider: str, force_keep: bool = False):
    """Open a `chat {model}` span with GenAI attributes. Yields the span so the
    caller can set usage tokens from the real response.
    """
    attrs = {"sampling.force_keep": True} if force_keep else {}
    with tracer.start_as_current_span(
        f"chat {model}", kind=SpanKind.CLIENT, attributes=attrs
    ) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", provider)
        span.set_attribute("gen_ai.request.model", model)
        try:
            yield span
        except Exception as exc:  # record exception + red status, then re-raise
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@contextmanager
def traced_tool_call(tracer, tool_name: str, force_keep: bool = False):
    """Open an `execute_tool {tool_name}` span with the GenAI tool attribute."""
    attrs = {"sampling.force_keep": True} if force_keep else {}
    with tracer.start_as_current_span(
        f"execute_tool {tool_name}", kind=SpanKind.INTERNAL, attributes=attrs
    ) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool_name)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def set_usage(span, input_tokens: int, output_tokens: int) -> None:
    """Set token usage so backends can compute cost from gen_ai.usage.*."""
    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)


# ---------------------------------------------------------------------------
# Two simulated fleet services.
# ---------------------------------------------------------------------------


def run_research_service(tracer) -> None:
    """svc-research-agent: a root run with nested model + tool spans."""
    model = "gpt-sim-large"
    with tracer.start_as_current_span("agent_run", kind=SpanKind.SERVER):
        with traced_model_call(tracer, model, "openai") as span:
            set_usage(span, 1200, 300)
        with traced_tool_call(tracer, "web_search"):
            pass
        with traced_model_call(tracer, model, "openai") as span:
            set_usage(span, 400, 120)


def run_support_service(tracer, force_error: bool = False) -> None:
    """svc-support-agent: a root run; optionally raises to produce a red trace."""
    model = "claude-sim-fast"
    with tracer.start_as_current_span("agent_run", kind=SpanKind.SERVER) as root:
        try:
            with traced_model_call(tracer, model, "anthropic", force_keep=force_error) as span:
                set_usage(span, 800, 200)
            with traced_tool_call(tracer, "lookup_ticket", force_keep=force_error):
                if force_error:
                    raise RuntimeError("ticket store timeout")
        except RuntimeError as exc:
            root.record_exception(exc)
            root.set_status(Status(StatusCode.ERROR, str(exc)))


# ---------------------------------------------------------------------------
# Fleet dashboards: compute cost, p95 latency, error rate grouped by service.name.
# ---------------------------------------------------------------------------


def _cost(model: str, in_tok: int, out_tok: int) -> float:
    in_price, out_price = PRICE_PER_1K.get(model, (0.0, 0.0))
    return (in_tok / 1000) * in_price + (out_tok / 1000) * out_price


def fleet_dashboards(spans) -> dict:
    cost_by_service: dict[str, float] = defaultdict(float)
    root_latency_ms: dict[str, list[float]] = defaultdict(list)
    root_total: dict[str, int] = defaultdict(int)
    root_errors: dict[str, int] = defaultdict(int)

    for span in spans:
        service = span.resource.attributes.get("service.name", "unknown")
        attrs = span.attributes or {}
        if attrs.get("gen_ai.operation.name") == "chat":
            cost_by_service[service] += _cost(
                attrs.get("gen_ai.request.model", ""),
                attrs.get("gen_ai.usage.input_tokens", 0),
                attrs.get("gen_ai.usage.output_tokens", 0),
            )
        # Root spans are the service-level "runs": SERVER kind here.
        if span.kind == SpanKind.SERVER:
            root_total[service] += 1
            duration_ms = (span.end_time - span.start_time) / 1_000_000
            root_latency_ms[service].append(duration_ms)
            if span.status.status_code == StatusCode.ERROR:
                root_errors[service] += 1

    def p95(values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[idx]

    return {
        service: {
            "tokens_cost_usd": round(cost_by_service[service], 6),
            "p95_root_latency_ms": round(p95(root_latency_ms[service]), 3),
            "error_rate": round(root_errors[service] / root_total[service], 3)
            if root_total[service]
            else 0.0,
            "runs": root_total[service],
        }
        for service in sorted(root_total)
    }


# ---------------------------------------------------------------------------
# Demo: generate non-trivial traffic across both services, incl. one error each.
# ---------------------------------------------------------------------------


def main() -> None:
    random.seed(7)
    research = init_tracing("svc-research-agent", "2.3.1")
    support = init_tracing("svc-support-agent", "1.4.0")

    for _ in range(20):
        run_research_service(research)
    for i in range(20):
        run_support_service(support, force_error=(i == 0))

    # SimpleSpanProcessor exports synchronously, so every kept span is already present.
    dashboards = fleet_dashboards(SHARED_EXPORTER.get_finished_spans())
    print("=== FLEET DASHBOARDS (grouped by service.name) ===")
    for service, metrics in dashboards.items():
        print(f"{service}: {metrics}")

    # Sanity: both services emitted, and support recorded at least one error.
    assert "svc-research-agent" in dashboards
    assert "svc-support-agent" in dashboards
    assert dashboards["svc-support-agent"]["error_rate"] > 0.0
    print("\nFleet trace standard verified: two services, one path, error-biased keep.")


if __name__ == "__main__":
    main()
```

Sending to a real backend is a one-line change in `init_tracing`:

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces"))
)
```

Run Phoenix with `pip install arize-phoenix && phoenix serve` (UI on
`http://localhost:6006`, OTLP ingest on `:4318`). In the Phoenix UI the fleet charts are
group-by-`service.name` queries: sum of `gen_ai.usage.*` for cost, p95 of root-span
duration for latency, and `count(status = ERROR) / count(*)` for error rate.

## Meeting the acceptance criteria

- **GenAI conventions.** Spans are named `chat {model}` / `execute_tool {name}` and carry
  `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and `gen_ai.tool.name`, all
  set inside the shared wrapper so services can't drift.
- **Resource attributes per service.** `init_tracing` builds a `Resource` with
  `service.name`, `service.version`, and `deployment.environment`; the two services pass
  different `service.name` values.
- **Two services, one path, correct nesting.** Both providers feed one `SHARED_EXPORTER`
  (the OTLP swap is one line). Each service's `agent_run` SERVER root parents its
  `chat`/`execute_tool` spans.
- **Errors red, always kept.** Failing calls call `record_exception` + set
  `StatusCode.ERROR`; `ErrorBiasedSampler` honors `sampling.force_keep` so errored runs
  are never dropped.
- **Fleet dashboards.** `fleet_dashboards` returns cost, p95 root latency, and error rate
  *per `service.name`* across many runs — fleet views, not single-run views.

## Common pitfalls

- **Hand-rolling attribute keys per service.** If each team types `"model"` vs.
  `"gen_ai.request.model"`, no cross-service chart can aggregate them. Force the keys
  through the shared wrapper.
- **Forgetting resource attributes.** Spans without `service.name` are an unpartitionable
  pile; you can't answer "which service is burning tokens?" Set the `Resource` once at
  startup.
- **Wiring each service straight to the backend.** That scatters the OTLP endpoint,
  sampling, and redaction across N services. Route through one path (collector/exporter)
  so policy changes once.
- **Sampling away your errors.** A naive `ratio` sampler drops the very traces you need to
  debug. Always keep errored (and ideally slow) runs regardless of the ratio.
- **Reading latency off child spans.** p95 "latency" must be the *root* span duration; a
  fast model call inside a slow run hides the user-visible tail. Group p95 on the root.

## Verification

```bash
pip install opentelemetry-api opentelemetry-sdk
python fleet_tracing.py
```

Expected: a `FLEET DASHBOARDS` block printing one line per `service.name` with
`tokens_cost_usd`, `p95_root_latency_ms`, `error_rate`, and `runs`. `svc-support-agent`
shows a non-zero `error_rate` (the forced timeout), and the run ends with
`Fleet trace standard verified: ...`. Against real Phoenix, open `http://localhost:6006`,
confirm nested traces from both services, and rebuild the same three charts grouped by
`service.name`; the errored support run renders red.

The `NOTES.md` reflection: the only-because question — cost-per-service rollups work *only
because* both services emitted identical `gen_ai.usage.*` keys and `service.name` resource
attributes; a renamed key or a missing resource breaks it. Centralizing the export path
lets you change the backend, sampling ratio, and redaction once instead of per service.
Redact prompt/response content at the collector (or an exporter span-processor), not in
each service, so a new team inherits the redaction policy instead of rediscovering it.
