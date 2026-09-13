---
name: Run state checkpoints
description: Ahmed Agent uses a deterministic persisted run state instead of open-ended orchestration.
---

Treat each agent execution as a finite state machine with explicit transitions from context loading through completion or failure.

**Why:** The existing PostgreSQL, tool-event, policy, and audit layers already provide the right foundation for recoverable execution; adding an orchestration framework would increase risk without improving the current product boundary.

**How to apply:** Keep checkpoint payloads limited to stage and safe operational metadata. Store them in PostgreSQL and mirror them into the tamper-evident audit chain. Do not store prompts, raw provider responses, or secrets in checkpoints.

Recovery may complete only the persisted response tail. A stale `model_running`
stage must never replay the model automatically; require a new explicit attempt
until each side-effecting step has a durable idempotency key and ownership lease.
Keep `recovery_status=orphaned` separate from the execution status and stage.

**Why:** A crash can occur after a model or tool side effect but before its next checkpoint, so blind replay can duplicate work or sensitive actions.

**How to apply:** Use worker leases and orphan detection to arbitrate ownership. Treat `created`/`context_loaded` as new-run cases, `model_running` as manual review, and `response_ready`/`response_persisted` as safe tail-recovery candidates only when persisted messages prove the response exists. Validate this with a real process-kill/restart test against PostgreSQL.