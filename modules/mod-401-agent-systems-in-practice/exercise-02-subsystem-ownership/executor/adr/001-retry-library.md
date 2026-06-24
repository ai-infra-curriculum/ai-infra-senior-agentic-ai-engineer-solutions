# ADR-001: Retry-with-backoff — build vs. adopt

- **Status:** Accepted (2026-06-24)
- **Context:** The failure policy requires bounded retries with exponential
  backoff for transient transport errors. Mature libraries (`tenacity`,
  `backoff`) solve exactly this and have years of edge-case fixes — jitter,
  budget caps, exception predicates.
- **Decision (build, narrowly):** Keep the ~10-line retry loop in-process rather
  than adopt a library. Applying the Chapter 4 grid: retry is *plumbing, not our
  differentiator* (a point for buy), but our requirements are *standard and
  small*, the *cost of being wrong is low* (it is 10 lines behind the executor's
  own boundary), and — decisively — we need the retry decision *fused with the
  circuit breaker and the transient classifier*, which a generic decorator would
  fragment across call sites.
- **Consequence:** We own ~10 lines and their tests. We forgo library-provided
  jitter; if thundering-herd retries become a problem we add jitter to one
  function or adopt `tenacity` behind the same loop — a contained change, since
  no caller sees the retry mechanism. This is the *exception* that proves the
  rule: build was justified only because the surface is tiny and tightly coupled
  to two other policy concerns.
