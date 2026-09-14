# Ahmed Agent — Main Remaining-Work Plan

- **Date:** 2026-09-14
- **Execution branch:** `agent/blueprint-docs-2026-09-14`
- **Current phase:** Phase 0 complete
- **Reference result:** `26 EXECUTED / 0 Capability Gaps / 0 Provider Failures / 0 HITL_BLOCKED`
- **Current stage:** Security & Dependency Remediation

## Ordered stages

### 1. Security & Dependency Remediation — current stage

- Run the available dependency, SAST, and privacy/security scans.
- Record each dependency finding with package, installed version, direct or
  transitive path, severity, advisory, and available fix.
- Apply the smallest compatible remediation for confirmed findings.
- Use TDD for any behavior or code change; documentation-only reports do not
  require a failing test.
- Preserve MCP, Starlette, OpenAI-compatible, Gemini, and PostgreSQL behavior.
- Re-run the complete test suite, compile check, dependency consistency check,
  and `git diff --check`.
- Write a sanitized remediation report with no secrets.

### 2. Core operational acceptance

- Confirm the owner-authenticated chat and upload journeys with real requests.
- Confirm authenticated MCP clients can complete a handshake.
- Verify persistence, recovery, leases, runtime metrics, and alert evaluation.
- Keep provider credentials and deployment configuration unchanged.

### 3. Model gateway reliability

- Add or finish regression coverage for provider authorization, request limits,
  retries, and fail-closed behavior.
- Do not switch providers or weaken authentication.

### 4. Evidence and answer-quality acceptance

- Import the authorized AA-RC-002 documents when available.
- Connect real cases to execution traces.
- Add a reviewed semantic grading rubric and run semantic grading.
- Measure grounded answers and semantic file search against the existing FTS
  baseline.

### 5. Search and integration follow-through

- Evaluate Google Search grounding as a separate source.
- Catch academic-provider response regressions.
- Automate promoted baseline artifact generation where appropriate.
- Address the remaining owner alerting and SEO tasks.

## Deferred by decision

- Multimodal Perception & Communication Plane
- Voice, Audio, Vision, Image, Video, Generation, Editing, and Composition
- Controlled Self-Improvement execution
- Model Gateway work beyond the dedicated stage above

The deferred Multimodal plane remains blueprint-only. Controlled
Self-Improvement remains proposal-based design only:

```text
Sandbox → Baseline → Proposal → Approval → Deploy → Re-evaluate
```

Policy Gates, the HITL Controller, and the Provenance Verifier remain outside
any self-modifying boundary. Superpowers is an optional external development
aid, not an Ahmed Agent runtime capability.

## Change boundary for this execution

This execution may change dependency manifests, lockfiles, tests, and sanitized
security documentation only when required by a confirmed finding. It must not
change secrets, database schema, runtime architecture, providers, deployment,
Multimodal/Voice, or self-improvement behavior.