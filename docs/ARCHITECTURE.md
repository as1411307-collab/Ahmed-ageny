# Ahmed Agent architecture

## Request flow

```text
Browser / API client
        |
        v
server.py
  |-- owner authentication
  |-- request validation
  |-- persistence lifecycle
  |-- policy and HITL routes
  |-- MCP transport protection
        |
         +--> agent_core.py ------> Gemini / ChatGPT
        |         |
        |         +--------------> skill_tools.py
        |                            |-- Search Fabric / Tavily
        |                            |-- academic_search.py
        |                            +-- github_search.py
        |
        +--> my_files.py --------> embeddings.py (optional)
        |                            |
        |                            +--> persistence.py / PostgreSQL
        |
        +--> doctor.py ----------> provider and storage health checks
```

## Repository map

| Path | Responsibility |
| --- | --- |
| `server.py` | HTTP routes, MCP app wiring, request lifecycle |
| `agent_core.py` | Gemini agent construction, history parsing, retries |
| `skill_tools.py` | Agent tool registration and web-search integration |
| `search_fabric.py` | Provider routing, normalization, fusion, provenance |
| `academic_search.py` | Crossref/DataCite/OpenAlex academic retrieval |
| `github_search.py` | Read-only GitHub REST search |
| `my_files.py` | Upload validation, extraction, chunking, retrieval |
| `embeddings.py` | Lazy optional semantic retrieval provider |
| `persistence.py` | PostgreSQL sessions, messages, runs, checkpoints, actions, audit |
| `run_state.py` | Deterministic run stages and allowed transitions |
| `auth.py` | Single-owner bearer authentication |
| `policy.py` | Tool risk policy and HITL metadata |
| `doctor.py` | Operational health and diagnostic report |
| `web/index.html` | RTL owner console |
| `tests/` | Contract, provider, search, and security regression tests |

## Trust boundaries

1. Browser and API request bodies are untrusted.
2. Uploaded file names and bytes are untrusted.
3. Search-provider responses and model output are untrusted.
4. Only the owner bearer token can access private routes and MCP.
5. Database writes use parameterized queries.
6. Browser output uses DOM text nodes rather than HTML interpolation.

## Deliberate boundaries

- Gemini is the model provider; Tavily/Search Fabric is a separate web-search
  capability.
- GitHub is read-only.
- The current sensitive action is an internal no-side-effect test action.
- FastEmbed is optional; FTS remains the safe fallback.
- Each run records safe state checkpoints (`context_loaded`, `model_running`,
  `response_ready`, `response_persisted`, `completed` or `failed`) in
  PostgreSQL and mirrors them into the tamper-evident audit chain. Checkpoint
  state never includes prompt text or provider secrets.
- Run leases identify the active worker. Expired leases set a separate
  `recovery_status=orphaned` while preserving the execution `status` and
  `stage`. Recovery can complete a persisted response tail, but it never
  replays a model call automatically from `model_running`.
- Sensitive HITL actions use a run-scoped idempotency key so a retry cannot
  create the same pending action twice.
- Runtime observability is exposed as owner-only aggregated metrics with a
  bounded time window; it does not expose prompts, provider payloads, or
  secrets.
- Retention deletes only aged checkpoints or explicitly tagged test-scope
  operational rows. The hash-linked audit event table is preserved; cleanup
  records its own aggregate event instead of deleting audit history.
- Alert evaluation is separate from notification delivery. Persisted rule state
  uses cooldowns and transition events, while the current notifier is
  intentionally unconfigured.
- Evaluation is separate from runtime operations. The baseline harness grades
  tool selection, forbidden tools, citations, schema, and approval boundaries
  deterministically; semantic grading is explicitly disabled until real cases
  and a reviewed rubric are available.
- The registered Node artifact is not imported by the Python runtime.