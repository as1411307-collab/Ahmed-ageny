---
name: Quality acceptance and persisted evidence
description: Live acceptance must separate targeted quality from full-regression coverage and normalize persisted JSON metadata.
---

Targeted deterministic acceptance can pass while the full real-case scoreboard remains incomplete or fails on unrelated cases. Provider failures and capability gaps are separate coverage dimensions, not quality failures.

**Why:** The live evaluator exposed unrelated citation/tool gaps during a required full regression even though AA-RC-014 passed with valid evidence identity and the run had no provider failures.

**How to apply:** Keep targeted quality artifacts separate from promoted coverage baselines, preserve the unchanged dataset/configuration, and report semantic grading as deferred when no semantic grader is configured. Normalize JSONB metadata at evaluation boundaries because persisted JSON fields may be returned as strings.

Persisted evidence items can be valid even when an older tool event has no
citation list. Rebuild citation-ready provenance at the trace boundary from
validated source identity, hash, and locator; never infer a citation from a
legacy file/line shape that lacks those fields.

**Why:** The live baseline exposed that raw runtime evidence and final output
citations had diverged even though the underlying tool evidence was present.

**How to apply:** Keep canonical provenance alongside available citations in
every evaluation trace, and classify provider/execution failures as
`NOT_DETERMINED` with a separate failure report rather than semantic answer
`FAIL`.