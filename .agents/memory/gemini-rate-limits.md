---
name: Gemini rate limits
description: Gemini live chat can return sustained 429 responses after rapid end-to-end test bursts.
---

Gemini `gemini-3-flash-preview` can remain rate-limited across several minutes after many live agent runs. The agent uses bounded retries with `Retry-After` support and exponential backoff; it must not switch providers or retry forever.

**Why:** Phase testing generated multiple model and tool-call requests quickly, after which even independent MY_FILES requests returned 429 while direct PostgreSQL retrieval remained healthy.

**How to apply:** Separate live smoke tests with time, treat persistent 429 as an external provider/quota blocker, and report it instead of changing the provider architecture.