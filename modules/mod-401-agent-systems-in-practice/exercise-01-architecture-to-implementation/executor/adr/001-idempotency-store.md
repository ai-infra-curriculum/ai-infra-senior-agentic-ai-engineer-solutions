# ADR-001: Idempotency store for the tool-executor

- **Status:** Accepted (2026-06-24)
- **Context:** The contract requires idempotency on `call.id`, but the architecture
  did not say where that state lives. The executor runs single-process today,
  one instance per worker, and a replayed `call.id` only needs to dedupe within
  the lifetime of an in-flight plan — not across deploys.
- **Decision:** Keep idempotency state in an in-process `InMemoryStore` behind the
  `Store` protocol. Defer an external (Redis/Postgres) store until a second
  executor instance must share dedup state.
- **Consequence:** Zero network hops and trivial tests now; dedup does not survive
  a restart or span replicas. The `Store` seam means adopting Redis later is one
  adapter and a wiring change, not an executor rewrite. Revisit the moment the
  executor scales past one instance or must dedupe across restarts.
