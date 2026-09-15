from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            return text
        raise RuntimeError(f"missing patch marker: {label}")
    if count != 1:
        raise RuntimeError(f"ambiguous patch marker {label}: {count}")
    return text.replace(old, new, 1)


def patch_skill_tools() -> None:
    path = Path("skill_tools.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "_search_fabric_instance: object | None = None\n\n\ndef _get_search_fabric() -> object:\n",
        "_search_fabric_instance: object | None = None\n_search_cache_instance: object | None = None\n\n\ndef _get_search_fabric() -> object:\n",
        "skill_tools cache singleton",
    )
    marker = "    return _search_fabric_instance\n\n\nasync def web_search(\n"
    insertion = '''    return _search_fabric_instance\n\n\ndef _get_search_cache() -> object:\n    global _search_cache_instance\n    if _search_cache_instance is None:\n        from acceleration_cache import search_cache_from_env\n\n        _search_cache_instance = search_cache_from_env()\n    return _search_cache_instance\n\n\ndef _cache_bypass_required(query: str, query_type: str) -> bool:\n    if query_type in {\n        "current_news",\n        "finance",\n        "legal_government",\n        "social_community",\n    }:\n        return True\n    lowered = query.casefold()\n    return any(\n        marker in lowered\n        for marker in (\n            "latest",\n            "current",\n            "today",\n            "recent",\n            "breaking",\n            "this week",\n            "اليوم",\n            "أحدث",\n            "آخر",\n            "الحالي",\n            "هذا الأسبوع",\n        )\n    )\n\n\nasync def web_search(\n'''
    text = replace_once(text, marker, insertion, "skill_tools cache factory")
    old_web_search = '''async def web_search(\n    query: str,\n    max_results: int = 5,\n    mode: str = "FAST",\n) -> dict[str, object]:\n    fabric = _get_search_fabric()\n    return await fabric.search(  # type: ignore[union-attr]\n        query=query,\n        mode=mode,\n        max_results=max_results,\n        tavily_legacy_search=_tavily_web_search,\n    )\n'''
    new_web_search = '''async def web_search(\n    query: str,\n    max_results: int = 5,\n    mode: str = "FAST",\n) -> dict[str, object]:\n    from acceleration_cache import build_search_cache_key, should_cache_search\n\n    query_type = _classify_query(query)\n    bypass = _cache_bypass_required(query, query_type)\n    eligible = should_cache_search(\n        query_type=query_type,\n        sensitive=bypass,\n    )\n    cache = _get_search_cache()\n    cache_key: str | None = None\n    if eligible:\n        cache_key = build_search_cache_key(\n            query,\n            mode,\n            max_results,\n            query_type,\n        )\n        cached = await cache.get(cache_key)  # type: ignore[union-attr]\n        if cached is not None:\n            return {\n                **cached,\n                "cache": {\n                    "eligible": True,\n                    "hit": True,\n                    "status": "hit",\n                    "query_type": query_type,\n                },\n            }\n\n    fabric = _get_search_fabric()\n    result = await fabric.search(  # type: ignore[union-attr]\n        query=query,\n        mode=mode,\n        max_results=max_results,\n        tavily_legacy_search=_tavily_web_search,\n    )\n    if eligible and cache_key is not None and result.get("ok") is True:\n        await cache.set(cache_key, result)  # type: ignore[union-attr]\n    return {\n        **result,\n        "cache": {\n            "eligible": eligible,\n            "hit": False,\n            "status": "miss" if eligible else "bypass",\n            "query_type": query_type,\n        },\n    }\n'''
    text = replace_once(text, old_web_search, new_web_search, "skill_tools web_search")
    path.write_text(text, encoding="utf-8")


def patch_policy() -> None:
    path = Path("policy.py")
    text = path.read_text(encoding="utf-8")
    marker = '''    "test_sensitive_action": ToolPolicy(\n'''
    insertion = '''    "n8n_automation": ToolPolicy(\n        tool_name="n8n_automation",\n        risk_level=RiskLevel.SENSITIVE_SIDE_EFFECT,\n        requires_approval=True,\n        reversible=False,\n        external_side_effect=True,\n        data_scope="AUTHORIZED_N8N_AUTOMATION",\n    ),\n    "test_sensitive_action": ToolPolicy(\n'''
    text = replace_once(text, marker, insertion, "policy n8n")
    path.write_text(text, encoding="utf-8")


def patch_agent_core() -> None:
    path = Path("agent_core.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from my_files import search_my_files as existing_my_files_search\n",
        "from my_files import search_my_files as existing_my_files_search\nfrom n8n_adapter import n8n_adapter_from_env\n",
        "agent_core n8n import",
    )
    instructions_marker = '''Use inspect_source_of_truth for authorized uploaded-source questions. First use\nsearch_my_files to find the requested filename and its source_id, then inspect\neach returned source_id. Never pass a filesystem path, filename, storage key,\nor guessed identifier to inspect_source_of_truth.\n'''
    instructions_new = instructions_marker + '''\nUse n8n_automation only when the user explicitly requests a configured external\nautomation. It can queue only allowlisted workflows and always returns a pending\naction that requires the existing owner approval gate before any side effect.\n'''
    text = replace_once(text, instructions_marker, instructions_new, "agent_core n8n instructions")
    function_marker = '''def configured_provider_names() -> list[str]:\n    return [candidate.name for candidate in _configured_providers()]\n\n\ndef _provider_error_code(error: Exception) -> str | None:\n'''
    function_new = '''def configured_provider_names() -> list[str]:\n    return [candidate.name for candidate in _configured_providers()]\n\n\nasync def queue_n8n_automation_action(\n    *,\n    conversation_id: str,\n    run_id: str,\n    user_id: str,\n    workflow: str,\n    instruction: str,\n) -> dict[str, object]:\n    adapter = n8n_adapter_from_env()\n    if adapter is None:\n        return {\n            "ok": False,\n            "requires_approval": False,\n            "status": "automation_not_configured",\n        }\n    workflow = workflow.strip()\n    instruction = instruction.strip()\n    if not workflow or workflow not in adapter.allowed_workflows:\n        return {\n            "ok": False,\n            "requires_approval": False,\n            "status": "workflow_not_allowed",\n        }\n    if not instruction:\n        return {\n            "ok": False,\n            "requires_approval": False,\n            "status": "invalid_instruction",\n        }\n    policy = get_tool_policy("n8n_automation")\n    action_id = str(uuid4())\n    payload = {"instruction": instruction}\n    canonical_payload = json.dumps(\n        payload,\n        sort_keys=True,\n        separators=(",", ":"),\n        ensure_ascii=False,\n    )\n    idempotency_key = hashlib.sha256(\n        f"{run_id}:n8n_automation:{workflow}:{canonical_payload}".encode("utf-8")\n    ).hexdigest()\n    pending_action = await create_pending_action(\n        action_id=action_id,\n        session_id=conversation_id,\n        run_id=run_id,\n        user_id=user_id,\n        tool_name=policy.tool_name,\n        risk_level=policy.risk_level.value,\n        arguments={"workflow": workflow, "payload": payload},\n        idempotency_key=idempotency_key,\n    )\n    return {\n        "ok": False,\n        "requires_approval": True,\n        "status": "pending_approval",\n        "action_id": str(pending_action["action_id"]),\n        "risk_level": policy.risk_level.value,\n        "workflow": workflow,\n    }\n\n\ndef _provider_error_code(error: Exception) -> str | None:\n'''
    text = replace_once(text, function_marker, function_new, "agent_core queue function")
    tool_marker = '''    async def test_sensitive_action(\n        ctx: RunContext[AgentDeps],\n        reason: Annotated[str, Field(min_length=1, max_length=500)],\n    ) -> dict[str, object]:\n'''
    tool_new = '''    async def n8n_automation(\n        ctx: RunContext[AgentDeps],\n        workflow: Annotated[str, Field(min_length=1, max_length=100)],\n        instruction: Annotated[str, Field(min_length=1, max_length=1000)],\n    ) -> dict[str, object]:\n        """Queue one allowlisted n8n automation behind the existing approval gate."""\n\n        if not ctx.deps.conversation_id or not ctx.deps.run_id:\n            raise RuntimeError("Automation actions require a persisted session and run.")\n        result = await queue_n8n_automation_action(\n            conversation_id=ctx.deps.conversation_id,\n            run_id=ctx.deps.run_id,\n            user_id=ctx.deps.user_id or "unauthenticated",\n            workflow=workflow,\n            instruction=instruction,\n        )\n        if ctx.deps.tool_event_recorder is not None:\n            await ctx.deps.tool_event_recorder(\n                "n8n_automation",\n                "success" if result.get("requires_approval") else "failed",\n                0,\n                {\n                    "policy": tool_metadata("n8n_automation"),\n                    "action_id": result.get("action_id"),\n                    "status": result.get("status"),\n                    "workflow": result.get("workflow"),\n                },\n            )\n        return result\n\n    async def test_sensitive_action(\n        ctx: RunContext[AgentDeps],\n        reason: Annotated[str, Field(min_length=1, max_length=500)],\n    ) -> dict[str, object]:\n'''
    text = replace_once(text, tool_marker, tool_new, "agent_core n8n tool")
    tools_marker = '''            inspect_source_of_truth,\n            test_sensitive_action,\n'''
    tools_new = '''            inspect_source_of_truth,\n            n8n_automation,\n            test_sensitive_action,\n'''
    text = replace_once(text, tools_marker, tools_new, "agent_core tools")
    path.write_text(text, encoding="utf-8")


def patch_server() -> None:
    path = Path("server.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from skill_tools import register_skill_tools\n",
        "from skill_tools import register_skill_tools\nfrom n8n_adapter import n8n_adapter_from_env\n",
        "server n8n import",
    )
    marker = '''WORKER_ID = default_worker_id()\n\n\nasync def _run_lease_heartbeat(run_id: str) -> None:\n'''
    insertion = '''WORKER_ID = default_worker_id()\n\n\ndef get_n8n_adapter():\n    return n8n_adapter_from_env()\n\n\nasync def _run_lease_heartbeat(run_id: str) -> None:\n'''
    text = replace_once(text, marker, insertion, "server n8n getter")
    old = '''    if claim.get("tool_name") != "test_sensitive_action":\n        return {"status": "unsupported_action", "executed": False}\n    # This internal test action intentionally has no external side effect.\n    completed = await complete_pending_action(\n        action_id=action_id,\n        user_id=user_id,\n    )\n    return {\n        "status": completed.get("status", "ERROR"),\n        "executed": completed.get("status") == "executed",\n        "side_effect": "none",\n    }\n'''
    new = '''    tool_name = claim.get("tool_name")\n    if tool_name == "test_sensitive_action":\n        # This internal test action intentionally has no external side effect.\n        completed = await complete_pending_action(\n            action_id=action_id,\n            user_id=user_id,\n        )\n        return {\n            "status": completed.get("status", "ERROR"),\n            "executed": completed.get("status") == "executed",\n            "side_effect": "none",\n        }\n    if tool_name != "n8n_automation":\n        return {"status": "unsupported_action", "executed": False}\n\n    adapter = get_n8n_adapter()\n    if adapter is None:\n        return {"status": "automation_not_configured", "executed": False}\n    arguments = claim.get("arguments")\n    if not isinstance(arguments, dict):\n        return {"status": "invalid_action", "executed": False}\n    workflow = arguments.get("workflow")\n    payload = arguments.get("payload")\n    if not isinstance(workflow, str) or not isinstance(payload, dict):\n        return {"status": "invalid_action", "executed": False}\n    try:\n        dispatch = await adapter.dispatch(\n            workflow,\n            payload,\n            action_id=action_id,\n            approved=True,\n        )\n    except Exception as error:\n        logger.warning(\n            "n8n automation failed action_id=%s error_type=%s",\n            action_id,\n            type(error).__name__,\n        )\n        return {"status": "automation_failed", "executed": False}\n    dispatch_status = dispatch.get("status") if isinstance(dispatch, dict) else None\n    if not isinstance(dispatch_status, int) or not 200 <= dispatch_status < 300:\n        return {"status": "automation_failed", "executed": False}\n    completed = await complete_pending_action(\n        action_id=action_id,\n        user_id=user_id,\n    )\n    return {\n        "status": completed.get("status", "ERROR"),\n        "executed": completed.get("status") == "executed",\n        "side_effect": "n8n",\n    }\n'''
    text = replace_once(text, old, new, "server approved n8n execution")
    path.write_text(text, encoding="utf-8")


def patch_pyproject() -> None:
    path = Path("pyproject.toml")
    text = path.read_text(encoding="utf-8")
    if '"redis>=' not in text:
        text = replace_once(
            text,
            '    "python-docx>=1.2.0",\n',
            '    "python-docx>=1.2.0",\n    "redis>=5.1.0",\n',
            "pyproject redis dependency",
        )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_skill_tools()
    patch_policy()
    patch_agent_core()
    patch_server()
    patch_pyproject()


if __name__ == "__main__":
    main()
