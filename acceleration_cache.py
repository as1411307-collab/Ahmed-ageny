from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Protocol


class AsyncCacheClient(Protocol):
    async def get(self, key: str) -> object: ...

    async def setex(self, key: str, ttl: int, value: str) -> object: ...


_CACHEABLE_SEARCH_TYPES = frozenset({"official", "technical", "academic", "general_web"})


def should_cache_search(*, query_type: str, sensitive: bool) -> bool:
    """Return True only for stable, non-sensitive search classes."""
    if sensitive:
        return False
    return query_type in _CACHEABLE_SEARCH_TYPES


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip()).casefold()


def build_search_cache_key(
    query: str,
    mode: str,
    max_results: int,
    query_type: str,
    *,
    version: str = "v1",
) -> str:
    payload = {
        "v": version,
        "query": _normalize_query(query),
        "mode": mode.strip().upper(),
        "max_results": int(max_results),
        "query_type": query_type.strip().casefold(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"ahmed:search:{version}:{digest}"


class SearchCache:
    """Small fail-open cache adapter. PostgreSQL remains the durable source of truth."""

    def __init__(
        self,
        *,
        client: AsyncCacheClient | None,
        enabled: bool,
        ttl_seconds: int = 300,
    ) -> None:
        self.client = client
        self.enabled = bool(enabled and client is not None)
        self.ttl_seconds = max(1, min(int(ttl_seconds), 3600))
        self.metrics: dict[str, int] = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "errors": 0,
        }

    async def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled or self.client is None:
            self.metrics["misses"] += 1
            return None
        try:
            raw = await self.client.get(key)
            if raw is None:
                self.metrics["misses"] += 1
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if not isinstance(raw, str):
                raise TypeError("cache payload is not text")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("cache payload is not an object")
            self.metrics["hits"] += 1
            return parsed
        except Exception:
            self.metrics["errors"] += 1
            return None

    async def set(self, key: str, payload: dict[str, Any]) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            await self.client.setex(key, self.ttl_seconds, encoded)
            self.metrics["writes"] += 1
        except Exception:
            self.metrics["errors"] += 1


def search_cache_from_env() -> SearchCache:
    enabled = os.environ.get("REDIS_CACHE_ENABLED", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    redis_url = os.environ.get("REDIS_URL", "").strip()
    try:
        ttl = int(os.environ.get("REDIS_SEARCH_CACHE_TTL_SECONDS", "300"))
    except ValueError:
        ttl = 300
    if not enabled or not redis_url:
        return SearchCache(client=None, enabled=False, ttl_seconds=ttl)
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return SearchCache(client=None, enabled=False, ttl_seconds=ttl)
    return SearchCache(client=client, enabled=True, ttl_seconds=ttl)
