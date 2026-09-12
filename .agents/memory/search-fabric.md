---
name: Search fabric routing
description: Provider-neutral web search routing and Brave adoption policy.
---

Tavily remains the primary web-search provider. Brave is an optional independent-index adapter and must stay disabled by default until a benchmark shows useful additional sources, primary sources, coverage, or resilience.

**Why:** A second provider adds request cost and latency without proving source independence or quality. Missing Brave configuration must not degrade Tavily FAST/DEEP or Doctor.

**How to apply:** Keep FAST Tavily-only. Use Brave selectively in DEEP only when explicitly enabled and configured; normalize URLs, deduplicate cross-provider results, fuse by rank rather than raw scores, and retain `found_by` provenance.