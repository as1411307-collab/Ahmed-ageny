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

For a persisted run, inspect its owner-only state trace with:

```text
GET /runs/{run_id}/checkpoints
```

The trace identifies whether a failure occurred during context loading, model
execution, response persistence, or completion without returning prompt text.

## Failure diagnosis

- `401`: check the exact `AHMED_OWNER_TOKEN` secret name and bearer header.
- provider failure: check `GEMINI_API_KEY` and `/health/provider`.
- persistence failure: check PostgreSQL availability and `/doctor`.
- an incomplete run: inspect `/runs/{run_id}/checkpoints` before changing model
  or tool code.
- empty search results: distinguish provider no-results from provider failure
  in the returned provenance and doctor report.
- embedding failure: continue with FTS and inspect the embedding health field.