---
name: Policy and HITL boundary
description: Approval and audit constraints for sensitive Ahmed Agent actions.
---

Sensitive actions must create a PostgreSQL-backed pending action and pass through an authenticated trusted-proxy identity; arbitrary browser headers are not treated as authentication.

**Why:** Approval text in prompts is not a security boundary, and duplicate or post-restart approval must be resolved from persisted state rather than process memory.

**How to apply:** Keep policy metadata outside prompts, transition pending → approved → executing → executed under row locks, record tamper-evident hash-chain events, and return 401 when no trusted identity is present.