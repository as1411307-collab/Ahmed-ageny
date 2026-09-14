---
name: AA-RC-026 review boundary
description: Build-vs-buy evidence can be execution-ready while semantic closure remains blocked by independent review.
---

For build-vs-buy evaluations, deterministic architecture and official external-source provenance are necessary but do not prove claim-level correctness or completeness. Keep the comparison artifact and all source identities bounded, and leave the case `NOT_DETERMINED` when an independent reviewer cannot support the material claims.

**Why:** The runtime can complete both project inspection and official documentation retrieval while the review packet still lacks enough claim-to-source entailment for a defensible PASS.

**How to apply:** Treat `EXECUTED` and `READY` evidence preconditions as separate from semantic closure; never convert a reviewer `FAIL` or `REVIEW_REQUIRED` into a pass merely because the recommendation is plausible.