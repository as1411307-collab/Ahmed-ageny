# Ahmed Agent acceleration layer

## Redis

Redis is an optional, fail-open cache for stable public-web search responses only. PostgreSQL remains the durable source of truth. Live/current news, finance, legal/government, social/community, and explicitly time-sensitive queries bypass the cache.

Configuration:

- `REDIS_CACHE_ENABLED=true`
- `REDIS_URL=<secret>`
- `REDIS_SEARCH_CACHE_TTL_SECONDS=300` (bounded by the adapter)

If Redis is missing or unavailable, search continues without cache.

## n8n

n8n is an external automation adapter, not the agent brain or primary orchestrator. Ahmed Agent may queue only allowlisted workflows. Every n8n side effect must pass the existing owner approval/HITL path before dispatch.

Configuration:

- `N8N_WEBHOOK_BASE_URL=<secret-or-private-endpoint>`
- `N8N_SHARED_SECRET=<secret>`
- `N8N_ALLOWED_WORKFLOWS=email-summary,...`

Outbound requests are signed with HMAC-SHA256 and include an action ID. The receiving n8n webhook must validate the signature and reject unknown or replayed action IDs.

Security baseline:

- Keep credentials outside workflow payloads.
- Protect webhooks and use TLS.
- Keep workflow names allowlisted.
- Run n8n security audits and review risky/community/custom nodes before enabling them.
- Preserve Ahmed Agent's existing approval, idempotency, audit, and provenance controls as the governing layer.

Official reference: https://docs.n8n.io/
