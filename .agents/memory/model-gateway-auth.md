---
name: Replit model gateway authorization
description: Replit-managed AI environment variables can exist while the model gateway rejects the integration authorization.
---

Treat `oauth.v2.ApiKeyNotApproved` from the Replit model gateway as an authorization-state failure, not as evidence that the model name or Tavily tool is invalid.

**Why:** The runtime can expose the managed integration variables while the gateway still requires an approval or reconnect action in the Replit UI.

**How to apply:** Keep the provider adapter explicit and classify the failure as `UNAUTHORIZED`; do not silently switch providers or ask for a personal key. After UI approval or reconnect, rerun the healthcheck and the real tool-call flow.

The managed AI setup helper can also stop immediately with an account-restriction error even when its environment variables already exist.

**Why:** Setup authorization and runtime secret presence are separate states.

**How to apply:** Preserve a validated, environment-gated provider adapter and report the setup blocker; do not expose secret values or silently substitute another model.

For an explicitly requested independent OpenAI evaluator, a valid `OPENAI_API_KEY` direct endpoint can be a same-provider fallback when the managed gateway is account-restricted.

**Why:** The managed gateway and direct OpenAI authorization are separate paths; the evaluator must remain OpenAI and must not be replaced by the production Gemini provider.

**How to apply:** Use the direct path only for the independent evaluator, keep the producer/reviewer identities distinct, and record the provider/model in the review artifact without exposing credentials.