---
name: Policy and HITL boundary
description: Approval and audit constraints for sensitive Ahmed Agent actions.
---

Sensitive actions must create a PostgreSQL-backed pending action and pass through a verified session or authentication middleware identity; arbitrary browser headers are not treated as authentication.

**Why:** Replit documentation explicitly warns that `X-Replit-User-Id` is not a security-critical identity source. Approval text in prompts is not a security boundary, and duplicate or post-restart approval must be resolved from persisted state rather than process memory.

**How to apply:** Keep policy metadata outside prompts, validate official session tokens or middleware-provided identities, compare against the single owner ID, transition pending → approved → executing → executed under row locks, and return 401 when no verified identity is present.