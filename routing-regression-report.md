# Request Routing Regression Report

## Scope

This change covers request classification only. It does not modify semantic
evaluation, provider behavior, persistence, or Multimodal/Voice paths.

## Regression coverage

The routing suite now covers:

- Operational evaluation and comparison intents.
- HITL and approval requirements.
- Official updates and external web research.
- Owner-token, URL, log, and tab security constraints.
- Recovery, `model_running`, and restart behavior.
- Audit chains and audit events.
- Alerting and polling transitions.
- Evaluation provenance, `contract_seed`, and quality-score constraints.
- Architecture decisions involving LangGraph, Multi-Agent, and MCTS.
- ASCII token boundaries so `check` does not match `checkpoint`.
- Template/ready-solution comparisons taking `web_search` precedence over
  broad source-status wording.

## Result

- Targeted routing tests: **9 passed**
- Full test suite: **129 passed, 1 skipped**
- `compileall`: **passed**
- `uv pip check`: **passed**
- `git diff --check`: **passed**

The classifier remains capability-based and does not read case IDs or dataset
`required_tools` at runtime.