---
name: Architecture continuity evidence
description: Boundary for full Foundation review and continuity claims.
---

Architecture review uses fixed component groups with separate implementation,
wiring, and test-file evidence. A current fingerprint helps compare snapshots,
but it cannot prove historical continuity without a prior trusted snapshot.

**Why:** File presence and imports do not prove operational behavior, and a
current inspection alone cannot establish that architecture was unchanged over
time.

**How to apply:** Keep the adapter read-only and pathless from the model
perspective; report group status and provenance; never claim tests passed from
test-file presence or claim unchanged architecture without a baseline.