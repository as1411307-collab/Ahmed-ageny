---
name: Run state checkpoints
description: Ahmed Agent uses a deterministic persisted run state instead of open-ended orchestration.
---

Treat each agent execution as a finite state machine with explicit transitions from context loading through completion or failure.

**Why:** The existing PostgreSQL, tool-event, policy, and audit layers already provide the right foundation for recoverable execution; adding an orchestration framework would increase risk without improving the current product boundary.

**How to apply:** Keep checkpoint payloads limited to stage and safe operational metadata. Store them in PostgreSQL and mirror them into the tamper-evident audit chain. Do not store prompts, raw provider responses, or secrets in checkpoints.