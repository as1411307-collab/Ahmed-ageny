---
name: Minimal operational alerting
description: Ahmed Agent evaluates a small persisted alert policy separately from notification delivery.
---

Operational alerts are limited to service health, audit integrity, orphan/lease anomalies, recovery failures, and sustained failure rate.

**Why:** The clean retention baseline supports useful reliability signals, but a large notification system would add noise and infrastructure before evaluation work. Alert transitions need cooldowns and minimum samples.

**How to apply:** Keep rules centralized with `healthy`, `warning`, `critical`, and `recovered` states. Persist state and audit only opens, escalations, recoveries, and cooldown-qualified suppressions; keep delivery unconfigured until a notifier is explicitly chosen.