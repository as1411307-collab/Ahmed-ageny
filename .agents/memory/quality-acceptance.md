---
name: Quality acceptance and persisted evidence
description: Live acceptance must separate targeted quality from full-regression coverage and normalize persisted JSON metadata.
---

Targeted deterministic acceptance can pass while the full real-case scoreboard remains incomplete or fails on unrelated cases. Provider failures and capability gaps are separate coverage dimensions, not quality failures.

**Why:** The live evaluator exposed unrelated citation/tool gaps during a required full regression even though AA-RC-014 passed with valid evidence identity and the run had no provider failures.

**How to apply:** Keep targeted quality artifacts separate from promoted coverage baselines, preserve the unchanged dataset/configuration, and report semantic grading as deferred when no semantic grader is configured. Normalize JSONB metadata at evaluation boundaries because persisted JSON fields may be returned as strings.