---
name: Gemini agent provider
description: The live agent uses direct Gemini authentication from the GEMINI_API_KEY secret and PydanticAI's Google model adapter.
---

Gemini is the primary live agent provider. The application passes the `GEMINI_API_KEY` secret directly to PydanticAI's `GoogleProvider`; Replit-managed OpenAI is not part of the active provider list.

**Why:** The Replit-managed OpenAI gateway remained unauthorized, while the user explicitly chose Gemini and the direct Gemini key successfully supported both plain responses and tool calls.

**How to apply:** Keep Tavily and MCP provider-neutral. For live smoke tests use the configured Gemini model, verify a plain MODEL_OK response, then verify a model-originated `web_search` call in the server logs.