---
name: External evidence provenance
description: Rules for carrying web-search evidence into traces and independent review packets
---

External web results are provenance, not verified project evidence. Preserve a bounded canonical URL, title, snippet, source identity, and the explicit `UNVERIFIED_EXTERNAL` status through tool-event metadata, evaluation traces, and independent-review packets. Strip query and fragment components before persisting reviewer-facing URLs.

**Why:** A reviewer needs to distinguish an attributable external result from a verified project-file citation, while query strings can contain tracking or sensitive material. Treating a web result as verified would weaken the evidence gate.

**How to apply:** Add external provenance as a separate field from citation-ready evidence provenance. Never let its presence alone upgrade deterministic groundedness or semantic status.