from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import server
from policy import get_tool_policy


class _FakeN8NAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, object], str, bool]] = []

    async def dispatch(
        self,
        workflow: str,
        payload: dict[str, object],
        *,
        action_id: str,
        approved: bool,
    ) -> dict[str, object]:
        self.calls.append((workflow, payload, action_id, approved))
        if self.fail:
            raise RuntimeError("downstream unavailable")
        return {"status": 200, "body": {"ok": True}}


class N8NActionIntegrationTests(unittest.TestCase):
    def test_policy_requires_approval_for_n8n(self) -> None:
        policy = get_tool_policy("n8n_workflow")
        self.assertTrue(policy.requires_approval)
        self.assertTrue(policy.external_side_effect)

    def test_approved_n8n_action_dispatches_once_and_completes(self) -> None:
        adapter = _FakeN8NAdapter()
        claim = {
            "status": "executing",
            "should_execute": True,
            "tool_name": "n8n_workflow",
            "arguments": {
                "workflow": "email-summary",
                "payload": {"subject": "hello"},
            },
        }
        with patch.object(
            server, "claim_pending_action_execution", new=AsyncMock(return_value=claim)
        ), patch.object(
            server, "complete_pending_action", new=AsyncMock(return_value={"status": "executed"})
        ) as complete, patch.object(
            server, "n8n_adapter_from_env", return_value=adapter
        ):
            result = asyncio.run(
                server._execute_approved_action(action_id="a1", user_id="owner")
            )

        self.assertTrue(result["executed"])
        self.assertEqual(result["status"], "executed")
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(adapter.calls[0][0], "email-summary")
        self.assertTrue(adapter.calls[0][3])
        complete.assert_awaited_once()

    def test_failed_n8n_dispatch_is_marked_failed_not_left_executing(self) -> None:
        adapter = _FakeN8NAdapter(fail=True)
        claim = {
            "status": "executing",
            "should_execute": True,
            "tool_name": "n8n_workflow",
            "arguments": {
                "workflow": "email-summary",
                "payload": {"subject": "hello"},
            },
        }
        with patch.object(
            server, "claim_pending_action_execution", new=AsyncMock(return_value=claim)
        ), patch.object(
            server, "fail_pending_action", new=AsyncMock(return_value={"status": "failed"})
        ) as fail, patch.object(
            server, "n8n_adapter_from_env", return_value=adapter
        ):
            result = asyncio.run(
                server._execute_approved_action(action_id="a2", user_id="owner")
            )

        self.assertFalse(result["executed"])
        self.assertEqual(result["status"], "failed")
        fail.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
