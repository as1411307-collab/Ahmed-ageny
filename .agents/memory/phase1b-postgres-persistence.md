---
name: Phase 1B PostgreSQL persistence
description: Python chat persistence stores PydanticAI messages per row and records runs and tool events in PostgreSQL.
---

The Python API persists agent state in PostgreSQL using asyncpg: messages are appended individually from `new_messages_json()`, runs record provider/model status, and tool events store only safe aggregate metadata.

**Why:** Session history must survive restarts without storing one unbounded blob or leaking prompts, raw search responses, or credentials.

**How to apply:** Treat JSONB values returned by asyncpg as JSON text unless a codec is explicitly configured; decode before passing message dictionaries to PydanticAI history validation.

Original uploaded bytes that need source-of-truth verification are stored as
immutable PostgreSQL blobs behind an `OriginalSourceStore` abstraction. Each
source is owner-scoped and addressed by a validated source ID; storage keys
never cross the capability boundary. Legacy document rows without original
bytes remain unverified rather than being reconstructed from chunks.

**Why:** This project had no durable object-storage backend, and reconstructing
an original from extracted chunks would destroy provenance and make hash
verification dishonest.