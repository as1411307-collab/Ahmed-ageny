from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from acceleration_cache import SearchCache


class _MemoryCacheClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        del ttl
        self.values[key] = value


class _FakeFabric:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        return {
            "ok": True,
            "query": kwargs["query"],
            "mode": kwargs["mode"],
            "results": [{"title": "result"}],
        }


class _FakeN8NAdapter:
    def __init__(self) -> None:
        self.allowed_workflows = {"email-summary"}
        self.calls: list[dict[str, object]] = []

    async def dispatch(self, workflow, payload, *, action_id, approved):
        self.calls.append(
            {
                "workflow": workflow,
                "payload": payload,
                "action_id": action_id,
                "approved": approved,
            }
        )
        return {"status": 200, "body": {"ok": True}}


class RedisSearchWiringTests(unittest.TestCase):
    def test_stable_search_uses_cache_on_second_call(self) -> None:
        import skill_tools

        fabric = _FakeFabric()
        cache = SearchCache(client=_MemoryCacheClient(), enabled=True, ttl_seconds=300)
        with patch("skill_tools._get_search_fabric", return_value=fabric), patch(
            "skill_tools._get_search_cache", return_value=cache
        ):
            first = asyncio.run(
                skill_tools.web_search("OpenAI API documentation", max_results=5, mode="FAST")
            )
            second = asyncio.run(
                skill_tools.web_search("OpenAI API documentation", max_results=5, mode="FAST")
            )

        self.assertEqual(fabric.calls, 1)
        self.assertEqual(first["cache"]["status"], "miss")
        self.assertEqual(second["cache"]["status"], "hit")

    def test_live_search_bypasses_cache(self) -> None:
        import skill_tools

        fabric = _FakeFabric()
        cache = SearchCache(client=_MemoryCacheClient(), enabled=True, ttl_seconds=300)
        with patch("skill_tools._get_search_fabric", return_value=fabric), patch(
            "skill_tools._get_search_cache", return_value=cache
        ):
            first = asyncio.run(
                skill_tools.web_search("breaking news today", max_results=5, mode="FAST")
            )
            second = asyncio.run(
                skill_tools.web_search("breaking news today", max_results=5, mode="FAST")
            )

        self.assertEqual(fabric.calls, 2)
        self.assertEqual(first["cache"]["status"], "bypass")
        self.assertEqual(second["cache"]["status"], "bypass")


class N8NWiringTests(unittest.TestCase):
    def test_policy_requires_approval_for_n8n(self) -> None:
        from policy import RiskLevel, get_tool_policy

        policy = get_tool_policy("n8n_automation")
        self.assertEqual(policy.risk_level, RiskLevel.SENSITIVE_SIDE_EFFECT)
        self.assertTrue(policy.requires_approval)
        self.assertTrue(policy.external_side_effect)

    def test_agent_can_queue_allowlisted_n8n_action(self) -> None:
        import agent_core

        adapter = _FakeN8NAdapter()
        action_id = str(uuid4())
        create_pending = AsyncMock(
            return_value={
                "action_id": action_id,
                "status": "pending",
            }
        )
        with patch("agent_core.n8n_adapter_from_env", return_value=adapter), patch(
            "agent_core.create_pending_action", new=create_pending
        ):
            result = asyncio.run(
                agent_core.queue_n8n_automation_action(
                    conversation_id=str(uuid4()),
                    run_id=str(uuid4()),
                    user_id="owner",
                    workflow="email-summary",
                    instruction="Summarize actionable email",
                )
            )

        self.assertTrue(result["requires_approval"])
        self.assertEqual(result["status"], "pending_approval")
        create_pending.assert_awaited_once()

    def test_approved_n8n_action_dispatches_once(self) -> None:
        import server

        adapter = _FakeN8NAdapter()
        action_id = str(uuid4())
        claim = AsyncMock(
            return_value={
                "status": "executing",
                "should_execute": True,
                "tool_name": "n8n_automation",
                "arguments": {
                    "workflow": "email-summary",
                    "payload": {"instruction": "Summarize actionable email"},
                },
            }
        )
        complete = AsyncMock(return_value={"status": "executed"})
        with patch("server.claim_pending_action_execution", new=claim), patch(
            "server.complete_pending_action", new=complete
        ), patch("server.get_n8n_adapter", return_value=adapter):
            result = asyncio.run(
                server._execute_approved_action(action_id=action_id, user_id="owner")
            )

        self.assertTrue(result["executed"])
        self.assertEqual(result["side_effect"], "n8n")
        self.assertEqual(len(adapter.calls), 1)
        self.assertTrue(adapter.calls[0]["approved"])
        complete.assert_awaited_once()

    def test_n8n_action_fails_closed_when_not_configured(self) -> None:
        import server

        action_id = str(uuid4())
        claim = AsyncMock(
            return_value={
                "status": "executing",
                "should_execute": True,
                "tool_name": "n8n_automation",
                "arguments": {
                    "workflow": "email-summary",
                    "payload": {"instruction": "Summarize actionable email"},
                },
            }
        )
        complete = AsyncMock(return_value={"status": "executed"})
        with patch("server.claim_pending_action_execution", new=claim), patch(
            "server.complete_pending_action", new=complete
        ), patch("server.get_n8n_adapter", return_value=None):
            result = asyncio.run(
                server._execute_approved_action(action_id=action_id, user_id="owner")
            )

        self.assertFalse(result["executed"])
        self.assertEqual(result["status"], "automation_not_configured")
        complete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
