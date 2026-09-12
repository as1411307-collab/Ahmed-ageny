---
name: Phase 1B PostgreSQL persistence
description: Python chat persistence stores PydanticAI messages per row and records runs and tool events in PostgreSQL.
---

The Python API persists agent state in PostgreSQL using asyncpg: messages are appended individually from `new_messages_json()`, runs record provider/model status, and tool events store only safe aggregate metadata.

**Why:** Session history must survive restarts without storing one unbounded blob or leaking prompts, raw search responses, or credentials.

**How to apply:** Treat JSONB values returned by asyncpg as JSON text unless a codec is explicitly configured; decode before passing message dictionaries to PydanticAI history validation.