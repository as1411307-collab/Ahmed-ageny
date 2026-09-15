---
name: Evidence context budgets
description: How evidence-first preflight should preserve model-visible facts without weakening full audit traces.
---

Model-facing evidence context must be a bounded summary separate from the full
evidence envelope and persisted trace. Full citations, provenance, and raw
structured results can exceed the model context limit and silently remove the
most important later evidence, including decision records.

**Why:** A runtime evidence payload can be larger than the total preflight
context budget. Appending a decision payload after it does not make the
decision visible to the model.

**How to apply:** Keep complete evidence in the envelope/trace, but place
priority summaries early and include bounded structured facts, citation
locators, hashes, statuses, missing records, conflicts, and limitations in the
model payload. Never solve truncation by exposing raw files or raising the
global context limit without a bounded design.