---
name: Hybrid RAG embedding
description: Local embedding selection and failure behavior for MY_FILES hybrid retrieval.
---

The preferred `multilingual-e5-small` identifier is not supported by the available fastembed backend. A locally run multilingual MiniLM model is the validated fallback; keep vector indexing optional and preserve FTS when local embedding fails.

**Why:** The environment successfully benchmarked the MiniLM fallback with local ONNX inference, while the preferred E5 model was rejected before loading. Sending file content to a cloud embedding API is outside the privacy boundary.

**How to apply:** Discover and benchmark local models before changing the configured embedding model; isolate vectors by model, dimension, and version so a model change cannot silently mix old and new embeddings.