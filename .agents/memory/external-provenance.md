---
name: External evidence provenance
description: Rules for carrying web-search evidence into traces and independent review packets
---

External web results are provenance, not verified project evidence. Preserve a bounded canonical URL, title, snippet, source identity, and the explicit `UNVERIFIED_EXTERNAL` status through tool-event metadata, evaluation traces, and independent-review packets. Strip query and fragment components before persisting reviewer-facing URLs.

**Why:** A reviewer needs to distinguish an attributable external result from a verified project-file citation, while query strings can contain tracking or sensitive material. Treating a web result as verified would weaken the evidence gate.

**How to apply:** Add external provenance as a separate field from citation-ready evidence provenance. Never let its presence alone upgrade deterministic groundedness or semantic status.

Source-of-truth cases must also match the expected source identities, not merely find any authorized file with intact bytes.

**Why:** An unrelated but valid upload can otherwise satisfy a generic inspection check and falsely remove an external-input blocker.

**How to apply:** Compare bounded observed filenames/source identities against every case-declared expected source before allowing the case to proceed.