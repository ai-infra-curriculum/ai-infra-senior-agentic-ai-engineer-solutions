# ADR-002: Metrics client — build vs. adopt

- **Status:** Accepted (2026-06-24)
- **Context:** The boundary must emit counters and latency timings. We could
  hand-roll aggregation (histograms, percentile buckets, exporters) or adopt a
  client (`prometheus-client`, `statsd`, or an OpenTelemetry SDK).
- **Decision (adopt — do NOT hand-roll):** Adopt an established metrics client in
  production. Chapter 4 grid: metrics is *pure plumbing*, mature maintained
  options *exist*, our needs are *standard*, and the *exit cost is low* because we
  emit through a two-method seam (`incr`, `timing`) that any backend satisfies.
  Hand-rolling percentile aggregation and an exporter is exactly the "own bugs
  the community already fixed" liability the chapter warns against.
- **Consequence:** We take on a dependency and its version churn, bounded by the
  thin `InMemoryMetrics`-shaped seam in `telemetry.py`. Tests use the in-process
  `InMemoryMetrics` (counters in a dict) so the suite needs no metrics backend;
  production swaps in the real client behind the same two methods. This is the
  build-vs-buy decision the exercise asks to justify *against* hand-rolling: the
  carrying cost of owning a metrics aggregator dwarfs the integration cost of a
  library.
