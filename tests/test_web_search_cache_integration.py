from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import skill_tools


class _FakeCache:
    def __init__(self, hit: dict[str, object] | None = None) -> None:
        self.hit = hit
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, dict[str, object]]] = []
        self.enabled = True
        self.metrics = {"hits": 0, "misses": 0, "writes": 0, "errors": 0}

    async def get(self, key: str) -> dict[str, object] | None:
        self.get_calls.append(key)
        return dict(self.hit) if self.hit is not None else None

    async def set(self, key: str, payload: dict[str, object]) -> None:
        self.set_calls.append((key, dict(payload)))


class _FakeFabric:
    def __init__(self) -> None:
        self.calls = 0

    async def search(
        self,
        *,
        query: str,
        mode: str,
        max_results: int,
        tavily_legacy_search,
    ) -> dict[str, object]:
        del tavily_legacy_search
        self.calls += 1
        return {
            "ok": True,
            "query": query,
            "mode": mode,
            "max_results": max_results,
            "query_type": "technical",
            "results": [{"title": "fresh", "url": "https://example.test"}],
        }


class WebSearchCacheIntegrationTests(unittest.TestCase):
    def test_stable_cache_hit_skips_search_fabric(self) -> None:
        cache = _FakeCache(
            {
                "ok": True,
                "query": "python docs",
                "mode": "FAST",
                "query_type": "technical",
                "results": [{"title": "cached"}],
            }
        )
        fabric = _FakeFabric()
        with patch("skill_tools._get_search_cache", return_value=cache), patch(
            "skill_tools._get_search_fabric", return_value=fabric
        ):
            result = asyncio.run(
                skill_tools.web_search("python docs", max_results=5, mode="FAST")
            )

        self.assertEqual(fabric.calls, 0)
        self.assertEqual(result["results"][0]["title"], "cached")
        self.assertTrue(result["cache"]["hit"])

    def test_live_query_bypasses_cache(self) -> None:
        cache = _FakeCache({"ok": True, "results": [{"title": "stale"}]})
        fabric = _FakeFabric()
        with patch("skill_tools._get_search_cache", return_value=cache), patch(
            "skill_tools._get_search_fabric", return_value=fabric
        ):
            result = asyncio.run(
                skill_tools.web_search(
                    "latest news today", max_results=5, mode="FAST"
                )
            )

        self.assertEqual(fabric.calls, 1)
        self.assertEqual(cache.get_calls, [])
        self.assertFalse(result["cache"]["eligible"])

    def test_stable_cache_miss_writes_successful_result(self) -> None:
        cache = _FakeCache()
        fabric = _FakeFabric()
        with patch("skill_tools._get_search_cache", return_value=cache), patch(
            "skill_tools._get_search_fabric", return_value=fabric
        ):
            result = asyncio.run(
                skill_tools.web_search(
                    "python documentation api", max_results=5, mode="FAST"
                )
            )

        self.assertEqual(fabric.calls, 1)
        self.assertEqual(len(cache.get_calls), 1)
        self.assertEqual(len(cache.set_calls), 1)
        self.assertFalse(result["cache"]["hit"])
        self.assertTrue(result["cache"]["eligible"])


if __name__ == "__main__":
    unittest.main()
