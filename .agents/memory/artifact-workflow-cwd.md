---
name: Artifact workflow working directory
description: How managed artifact workflows resolve relative paths when running a root-level service.
---

Managed artifact development commands start from the artifact directory. A command that launches a service stored at the workspace root must change back to the root first.

**Why:** A root-level Python server failed with “No such file or directory” when the managed artifact workflow tried to resolve it from the artifact package.

**How to apply:** For an artifact two levels below the workspace root, prefix the development command with `cd ../.. &&`; keep production paths explicit according to the production runner’s root context.