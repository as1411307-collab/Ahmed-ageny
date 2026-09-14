---
name: Evaluation baseline provenance
description: Ahmed Agent must separate contract seeds from real-case quality evaluation.
---

Contract seeds validate deterministic interfaces but are not evidence of real-user quality. A quality scoreboard must require qualified `real_case` entries with documented provenance and must report deterministic and semantic axes separately. The current harness still needs an execution adapter that runs Ahmed and captures traces before live deterministic evaluation is possible.

**Why:** Historical user conversations are not automatically available inside the workspace, and inventing them would create a misleading baseline that could drive the wrong Memory or Retrieval changes.

**How to apply:** Keep the import schema and dataset hash stable. Reject missing provenance, duplicate IDs, conflicting tool expectations, and secret fields. Return `REAL_CASE_DATA_REQUIRED` without traces, and `LIVE_EVAL_EXECUTION_PATH_REQUIRED` until an adapter can execute cases against Ahmed safely.

When authorized live sources replace a historical AA-RC fixture, bind them in a dated manifest that records source IDs, versions, hashes, and the superseded pack hash; never rewrite the historical fixture.

**Why:** A live source identity/hash change is evidence to compare, not permission to retroactively change prior evaluation results.

**How to apply:** Evaluate the live manifest against exact owner sources, record identity/version conflicts explicitly, and keep original-source precedence over memory or summaries.