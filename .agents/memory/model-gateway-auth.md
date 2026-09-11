---
name: Replit model gateway authorization
description: Replit-managed AI environment variables can exist while the model gateway rejects the integration authorization.
---

Treat `oauth.v2.ApiKeyNotApproved` from the Replit model gateway as an authorization-state failure, not as evidence that the model name or Tavily tool is invalid.

**Why:** The runtime can expose the managed integration variables while the gateway still requires an approval or reconnect action in the Replit UI.

**How to apply:** Keep the provider adapter explicit and classify the failure as `UNAUTHORIZED`; do not silently switch providers or ask for a personal key. After UI approval or reconnect, rerun the healthcheck and the real tool-call flow.