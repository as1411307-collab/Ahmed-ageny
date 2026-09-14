# Core Operational Acceptance Report

- **Date:** 2026-09-14
- **Branch:** `agent/blueprint-docs-2026-09-14`
- **Scope:** authenticated operational paths already present in Ahmed Agent
- **External sends:** none; provider-backed model execution was not invoked
- **Deployment:** not performed
- **Secrets:** used internally by the environment, never printed or persisted

## Result

**PASS for the local operational boundary.** Authenticated HTTP, PostgreSQL
persistence, MCP lifecycle, file validation, recovery controls, idempotency,
audit integrity, and internal runtime alerting were exercised with temporary
test data.

The chat acceptance used a local provider stub because this acceptance run
explicitly forbade external sends. The real provider selection and persistence
path were still exercised by the route; no Gemini or OpenAI request was made.

## Paths accepted

### Authentication

- Unauthenticated protected routes returned `401 AUTHENTICATION_REQUIRED`.
- Authenticated `GET /health/provider?provider=gemini` returned `200` with
  provider status `READY`.
- Authenticated `/doctor`, `/metrics/runtime`, `/alerts/runtime`, and
  `/retention/preview` returned `200`.

### Chat and persistence

- Authenticated `/chat/message` with the local provider stub returned `200`.
- The reply was persisted as a successful run.
- Persisted run state was:
  `succeeded / completed / resolved`.
- Five checkpoints were observed:
  `context_loaded`, `model_running`, `response_ready`,
  `response_persisted`, `completed`.
- One assistant message was persisted.

### MY_FILES

- Safe UTF-8 text upload returned `201`.
- The document was `ready`, had one searchable chunk, and
  `original_available=true`.
- Unsupported `.exe` upload returned `415`.
- Invalid binary content with a `.txt` name returned `415` with
  `invalid_file_content`.

### MCP

- Authenticated Streamable HTTP `initialize` returned `200`.
- An MCP session ID was issued.
- The server returned protocol version `2025-03-26`.

### PostgreSQL, leases, recovery, and idempotency

- Session, run, and checkpoints were created in PostgreSQL.
- Lease renewal returned `true`.
- An expired lease was detected as orphaned.
- Recovery action for a run at `model_running` was `manual_review`.
- `claim_orphaned_run` succeeded.
- Repeating the same pending-action idempotency key returned the same action.
- Recovery endpoint returned `200`; resume correctly returned `409
  MODEL_EXECUTION_NOT_IDEMPOTENT` for the model stage.

### Audit and runtime alerts

- `verify_audit_chain()` returned `verified=true`.
- Runtime metrics exposed orphan, lease-expiration, recovery-failure, and
  idempotency counters.
- `/alerts/runtime` returned `200`; all current alert rules were healthy.
- Recovery health is already observable internally through runtime metrics and
  the `orphan_lease_anomaly` and `recovery_failure` rules. No extra behavior
  was needed.

## Regression fixed

The live MCP initialize request originally returned `500` with
`Task group is not initialized`. `OwnerMCPAuthMiddleware` consumed lifespan
startup without forwarding it to MCP's Streamable HTTP app.

The minimal fix forwards the lifespan messages after performing the existing
orphan scan. A regression test now proves that an authenticated initialize
request succeeds after lifecycle startup.

## Cleanup

All temporary runs, sessions, checkpoints, messages, pending actions, tool
events, and uploaded document records were removed by exact test identifiers.
Verification after cleanup found:

- marked test runs: `0`
- marked test sessions: `0`
- marked test documents: `0`
- marked test pending actions: `0`

Audit events were preserved according to the retention policy.

## Verification

- Targeted operational/security tests: `18 passed, 1 skipped`
- Full suite: `107 passed, 1 skipped`
- Python compile check: passed
- `uv pip check`: passed; 119 packages compatible
- `git diff --check`: passed

## Not started

- Semantic grading
- Model Gateway work
- Multimodal/Voice
- Deployment or publishing
