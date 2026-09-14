---
name: MCP Streamable HTTP lifecycle
description: Owner auth middleware must forward ASGI lifespan events to MCP's Streamable HTTP app.
---

When middleware wraps the MCP Streamable HTTP app, it must preserve the
lifespan startup and shutdown messages after doing any project-specific startup
work. Consuming startup in the wrapper leaves the MCP session manager without
its task group and causes authenticated initialize requests to fail.

**Why:** The MCP SDK initializes its Streamable HTTP session manager inside the
lifespan context. A wrapper that emits its own lifespan completion but does not
delegate startup makes the live endpoint return an internal error even though
the server process is healthy.

**How to apply:** For any middleware around `streamable_http_app`, replay the
first lifespan message to the wrapped app and let the wrapped app consume the
later shutdown message. Keep project startup scans before delegation and keep
the regression test on an allowed local Host header.