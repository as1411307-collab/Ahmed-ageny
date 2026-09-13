---
name: Evaluation baseline provenance
description: Ahmed Agent must separate contract seeds from real-case quality evaluation.
---

Contract seeds validate deterministic interfaces but are not evidence of real-user quality. A quality scoreboard must require qualified `real_case` entries with documented provenance and must report deterministic and semantic axes separately.

**Why:** Historical user conversations are not automatically available inside the workspace, and inventing them would create a misleading baseline that could drive the wrong Memory or Retrieval changes.

**How to apply:** Keep the import schema and dataset hash stable. Reject missing provenance, duplicate IDs, conflicting tool expectations, and secret fields. Return `REAL_CASE_DATA_REQUIRED` instead of a quality score until real cases are imported.