# Ahmed Agent operations

## Start and restart

The configured workflow is:

```text
artifacts/api-server: API Server
```

Its command is:

```bash
uv run server.py
```

The server reads `PORT` from the environment and defaults to `8000`.

## Required configuration

Use Replit Secrets for:

```text
AHMED_OWNER_TOKEN
GEMINI_API_KEY
AI_INTEGRATIONS_OPENAI_API_KEY
AI_INTEGRATIONS_OPENAI_BASE_URL
```

Use the exact names above. Do not keep typo aliases such as `GEMNI_API_KEY`;
they are ignored by the application and make incident diagnosis harder.

Optional configuration includes:

```text
TAVILY_API_KEY
GITHUB_TOKEN
BRAVE_SEARCH_API_KEY
MY_FILES_EMBEDDING_MODEL
```

## Verification sequence

Run the fast local checks first:

```bash
python -B -m unittest discover -s tests -p 'test_*.py' -v
python -B -m compileall -q server.py auth.py my_files.py embeddings.py agent_core.py tests
git diff --check
```

Then verify the public health boundary:

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/mcp
```

Expected results:

- `/health` returns `200`.
- `/mcp` without a bearer token returns `401`.

Authenticated provider, chat, upload, doctor, and MCP protocol checks must be
run through an approved client without printing the owner token or provider
secret.

Runtime metrics are available to the owner as aggregated operational metadata:

```text
GET /metrics/runtime?hours=24
```

The response includes total, completed, failed, active, and currently orphaned
runs; average duration; lease expirations; recovery attempts; idempotency hits;
and counts by execution stage. The maximum window is 720 hours, and prompts,
provider payloads, and secrets are not returned.

For a persisted run, inspect its owner-only state trace with:

```text
GET /runs/{run_id}/checkpoints
```

The trace identifies whether a failure occurred during context loading, model
execution, response persistence, or completion without returning prompt text.

Recovery is explicit and owner-only:

```text
GET  /runs/{run_id}/recovery
POST /runs/{run_id}/resume
```

`POST /resume` only completes a response whose messages were already persisted.
Runs interrupted during model execution return a safe retry/manual-review result
instead of invoking the model again.

`orphaned` is a recovery condition, not a replacement for the execution stage:
inspect both `status`/`recovery_status` and `stage` when diagnosing a run.

## Failure diagnosis

- `401`: check the exact `AHMED_OWNER_TOKEN` secret name and bearer header.
- provider failure: check `GEMINI_API_KEY` and `/health/provider`.
- persistence failure: check PostgreSQL availability and `/doctor`.
- an incomplete run: inspect `/runs/{run_id}/checkpoints` before changing model
  or tool code.
- a recovery conflict: inspect `/runs/{run_id}/recovery`; an active lease means
  another worker still owns the run.
- a full crash/restart check: run
  `AHMED_RUN_RECOVERY_E2E=1 python -m unittest tests.test_recovery_fault_injection -v`
  against a development PostgreSQL database only.
- empty search results: distinguish provider no-results from provider failure
  in the returned provenance and doctor report.
- embedding failure: continue with FTS and inspect the embedding health field.