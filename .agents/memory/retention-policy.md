---
name: Retention policy
description: Ahmed Agent retention keeps audit history intact while cleaning aged checkpoints and explicit test-scope data.
---

Retention is conservative: succeeded-run checkpoints are eligible after 30 days, failed/orphaned checkpoints after 90 days, and hash-linked audit events are preserved.

**Why:** Deleting audit rows selectively would break the integrity chain and remove evidence needed to investigate recovery incidents. Test artifacts must be removable without touching real user scopes.

**How to apply:** Restrict test cleanup to the explicit `fault_injection` and `probe` scopes, require owner confirmation, append a cleanup audit event, and keep checkpoint cleanup separate from test-data cleanup.