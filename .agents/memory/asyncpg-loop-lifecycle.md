---
name: Asyncpg pool lifecycle
description: Asyncpg pools created in an asyncio run must be closed before that same event loop ends.
---

Asyncpg pools must be closed inside the same asyncio event loop that created and
used them. Calling `close_pool()` through a second `asyncio.run()` after the
first loop has closed can raise `RuntimeError: Event loop is closed`, even when
the database work and cleanup already completed.

**Why:** The AA-RC-002 evaluation runner initially reported a false nonzero exit
after successful source cleanup because its pool was closed from a new loop.