from __future__ import annotations

import asyncio
import json
import unittest


class _BrokenCacheClient:
    async def get(self, key: str):
        raise RuntimeError("cache down")

    async def setex(self, key: str, ttl: int, value: str):
        raise RuntimeError("cache down")


class _MemoryCacheClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        del ttl
        self.values[key] = value


class AccelerationCacheTests(unittest.TestCase):
    def test_cache_policy_blocks_sensitive_and_live_queries(self) -> None:
        from acceleration_cache import should_cache_search

        self.assertFalse(should_cache_search(query_type="current_news", sensitive=False))
        self.assertFalse(should_cache_search(query_type="finance", sensitive=False))
        self.assertFalse(should_cache_search(query_type="legal_government", sensitive=True))
        self.assertTrue(should_cache_search(query_type="technical", sensitive=False))

    def test_cache_key_changes_with_version_and_parameters(self) -> None:
        from acceleration_cache import build_search_cache_key

        first = build_search_cache_key("redis caching", "FAST", 5, "technical", version="v1")
        same = build_search_cache_key(" redis   caching ", "FAST", 5, "technical", version="v1")
        changed = build_search_cache_key("redis caching", "FAST", 5, "technical", version="v2")

        self.assertEqual(first, same)
        self.assertNotEqual(first, changed)

    def test_cache_fails_open_when_backend_is_unavailable(self) -> None:
        from acceleration_cache import SearchCache

        cache = SearchCache(client=_BrokenCacheClient(), enabled=True, ttl_seconds=300)
        self.assertIsNone(asyncio.run(cache.get("key")))
        asyncio.run(cache.set("key", {"ok": True}))
        self.assertGreaterEqual(cache.metrics["errors"], 2)

    def test_cache_round_trip_preserves_json_payload(self) -> None:
        from acceleration_cache import SearchCache

        cache = SearchCache(client=_MemoryCacheClient(), enabled=True, ttl_seconds=300)
        asyncio.run(cache.set("key", {"ok": True, "results": [{"title": "x"}]}))
        self.assertEqual(
            asyncio.run(cache.get("key")),
            {"ok": True, "results": [{"title": "x"}]},
        )
        self.assertEqual(cache.metrics["hits"], 1)


class N8NAdapterTests(unittest.TestCase):
    def test_disallows_workflow_outside_allowlist(self) -> None:
        from n8n_adapter import N8NAdapter, N8NDispatchError

        adapter = N8NAdapter(
            base_url="https://n8n.example.test/webhook/",
            shared_secret="secret",
            allowed_workflows={"email-summary"},
        )
        with self.assertRaises(N8NDispatchError):
            asyncio.run(adapter.dispatch("dangerous", {"x": 1}, action_id="a1", approved=True))

    def test_sensitive_dispatch_requires_explicit_approval(self) -> None:
        from n8n_adapter import N8NAdapter, N8NDispatchError

        adapter = N8NAdapter(
            base_url="https://n8n.example.test/webhook/",
            shared_secret="secret",
            allowed_workflows={"email-summary"},
        )
        with self.assertRaises(N8NDispatchError):
            asyncio.run(adapter.dispatch("email-summary", {"x": 1}, action_id="a1", approved=False))

    def test_dispatch_signs_payload_and_uses_configured_base_url(self) -> None:
        from n8n_adapter import N8NAdapter

        captured: dict[str, object] = {}

        async def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
            captured.update({"url": url, "body": body, "headers": headers})
            return {"status": 200, "body": {"ok": True}}

        adapter = N8NAdapter(
            base_url="https://n8n.example.test/webhook/",
            shared_secret="secret",
            allowed_workflows={"email-summary"},
            transport=transport,
        )
        result = asyncio.run(
            adapter.dispatch(
                "email-summary",
                {"subject": "hello"},
                action_id="action-123",
                approved=True,
            )
        )

        self.assertEqual(result["status"], 200)
        self.assertEqual(captured["url"], "https://n8n.example.test/webhook/email-summary")
        body = json.loads(captured["body"].decode("utf-8"))
        self.assertEqual(body["action_id"], "action-123")
        self.assertEqual(body["payload"], {"subject": "hello"})
        headers = captured["headers"]
        self.assertIn("X-Ahmed-Signature", headers)
        self.assertNotIn("secret", json.dumps(headers))


if __name__ == "__main__":
    unittest.main()
