---
name: Academic provider routing
description: Durable routing and privacy rules for the structured academic search layer.
---

Resolve a DOI's registration agency before selecting a metadata provider. Crossref and DataCite are exact DOI metadata sources; DataCite must not become a generic academic search provider. If agency discovery is unavailable, exact fallback lookups may prove ownership, otherwise return only a safe DOI landing URL.

**Why:** DOI prefixes alone do not reliably identify the registration agency, and assuming Crossref can return incorrect or missing metadata for DataCite records.

**How to apply:** Keep OpenAlex responsible for author/topic discovery, citation counts, open-access enrichment, and graph work. Do not embed graph edges in each academic result; load them only for an explicit graph/citation request. Academic provider calls stay in the WEB privacy boundary and never receive private file chunks or conversation history.