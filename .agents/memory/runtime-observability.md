---
name: Runtime observability
description: Ahmed Agent exposes bounded owner-only aggregate runtime metrics from PostgreSQL.
---

Use a bounded JSON metrics endpoint over persisted operational data before adding an external metrics stack.

**Why:** The runtime already records runs, leases, recovery conditions, stages, audit events, and idempotency hits; aggregating those records gives useful visibility without exposing prompts or provider payloads.

**How to apply:** Keep the window bounded to 1–720 hours and return only counts, durations, stage distributions, lease expirations, recovery attempts, and idempotency hits. Keep the endpoint owner-only and treat retention/alerts as separate operational work.