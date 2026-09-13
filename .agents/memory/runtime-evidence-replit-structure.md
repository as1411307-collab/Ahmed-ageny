---
name: Runtime evidence and Replit configuration
description: Runtime commands in .replit may be nested under deployment and must be selected structurally.
---

Runtime evidence inspection must parse `.replit` structurally with `tomllib`. A `run` command under `[deployment]` is the deployment runtime source; a root-level `run` remains a separate candidate and must not be silently merged or treated as active without evidence.

**Why:** The project’s active command is nested under `[deployment]`, so looking only at the TOML root produced a false partial result for the active entrypoint and runtime command.

**How to apply:** Keep deployment/root command candidates visible, prefer the deployment source when it is structurally present, derive the entrypoint from the selected command, and return partial when the selected evidence is malformed or conflicts cannot be resolved.