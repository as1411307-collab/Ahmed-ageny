---
name: PydanticAI gateway path
description: PydanticAI OpenAIChatModel uses the OpenAI-compatible chat completions route with the configured provider client.
---

PydanticAI's OpenAIChatModel sends through the provider client's chat-completions endpoint, while the older custom integration used the Responses endpoint. Both still depend on the same Replit-managed authorization.

**Why:** Migrating the agent core changes the SDK request path but does not repair an unauthorized Replit model gateway credential.

**How to apply:** Verify the provider gateway supports chat completions after reconnecting authorization, then run MODEL_OK and the web_search tool-call test; do not interpret a route change as a credential fix.