---
name: Non-artifact server routing
description: Replit routing behavior for a standalone server in a workspace that also contains artifacts.
---

Standalone servers configured through a workflow need an explicit `.replit` port mapping from their internal listening port to external port 80 before the development HTTPS domain can route to them.

**Why:** Without the mapping, the server can be healthy on localhost while the shared HTTPS domain returns “Backend Not Configured.”

**How to apply:** When exposing a non-artifact HTTP server, keep its workflow bound to `0.0.0.0`, add the matching `[[ports]]` mapping, and validate the `.replit` update before restarting the workflow.