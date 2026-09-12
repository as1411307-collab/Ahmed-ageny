import os
import logging
import json
import time
from uuid import UUID, uuid4
from pathlib import Path
from typing import TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from agent_core import (
    GEMINI_MODEL,
    PROVIDER_NAME,
    AgentCoreError,
    parse_message_history,
    run_ahmed,
)
from persistence import (
    PersistenceError,
    append_new_messages,
    create_run,
    ensure_session,
    finish_run,
    load_message_history,
    record_tool_event,
)
from skill_tools import register_skill_tools


class PingResult(TypedDict):
    ok: bool
    message: str


server = MCPServer("Ahmed Agent")
WEB_DIR = Path(__file__).parent / "web"
logger = logging.getLogger("ahmed_agent")


def _structured_log(
    *,
    trace_id: str,
    session_id: str,
    run_id: str,
    status: str,
    latency_ms: int,
    error_code: str | None = None,
) -> None:
    logger.info(
        json.dumps(
            {
                "trace_id": trace_id,
                "session_id": session_id,
                "run_id": run_id,
                "provider": PROVIDER_NAME,
                "model": GEMINI_MODEL,
                "status": status,
                "latency_ms": latency_ms,
                **({"error_code": error_code} if error_code else {}),
            },
            separators=(",", ":"),
        )
    )


def _request_uuid(value: object, field_name: str) -> str:
    if value is None:
        return str(uuid4())
    if not isinstance(value, str):
        raise ValueError(f"{field_name} غير صالح.")
    try:
        return str(UUID(value))
    except ValueError as error:
        raise ValueError(f"{field_name} غير صالح.") from error


@server.tool(
    description="Safely echoes a message for connectivity testing.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=True,
)
def ping(message: str) -> PingResult:
    return {"ok": True, "message": message}


register_skill_tools(server)


@server.custom_route("/", methods=["GET"])
async def chat_page(_: Request) -> Response:
    return FileResponse(WEB_DIR / "index.html")


@server.custom_route("/chat/message", methods=["POST"])
async def chat_message(request: Request) -> Response:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "صيغة الطلب غير صالحة."}, status_code=400)

    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str):
        return JSONResponse({"error": "الرسالة مطلوبة."}, status_code=400)

    message = message.strip()
    if not message or len(message) > 2000:
        return JSONResponse(
            {"error": "يجب أن تكون الرسالة بين 1 و2000 حرف."},
            status_code=400,
        )

    raw_history = payload.get("history")
    try:
        message_history = parse_message_history(raw_history)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)

    conversation_id = payload.get("conversation_id", payload.get("session_id"))
    run_id = payload.get("run_id")
    try:
        session_id = _request_uuid(conversation_id, "conversation_id")
        run_uuid = _request_uuid(run_id, "run_id")
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)

    trace_id = str(uuid4())
    started_at = time.perf_counter()
    try:
        await ensure_session(session_id)
        stored_history = await load_message_history(session_id)
        if stored_history:
            message_history = parse_message_history(stored_history)
        else:
            message_history = parse_message_history(raw_history)
        await create_run(
            run_id=run_uuid,
            session_id=session_id,
            user_prompt=message,
            provider_name=PROVIDER_NAME,
            model_name=GEMINI_MODEL,
        )
    except (PersistenceError, ValueError) as error:
        logger.error("Agent persistence setup failed error_type=%s", type(error).__name__)
        return JSONResponse(
            {"error": "تعذر الحصول على رد من الوكيل الآن. حاول مرة أخرى."},
            status_code=502,
        )

    async def save_tool_event(
        tool_name: str,
        status: str,
        duration_ms: int,
        safe_metadata: dict[str, object] | None,
    ) -> None:
        try:
            await record_tool_event(
                run_id=run_uuid,
                tool_name=tool_name,
                status=status,
                duration_ms=duration_ms,
                safe_metadata=safe_metadata,
            )
        except PersistenceError as error:
            logger.error("Tool event persistence failed error_type=%s", type(error).__name__)

    try:
        result = await run_ahmed(
            message,
            message_history=message_history,
            conversation_id=session_id,
            run_id=run_uuid,
            tool_event_recorder=save_tool_event,
        )
    except AgentCoreError as error:
        try:
            await finish_run(
                run_id=run_uuid,
                status="failed",
                error_code=error.provider_code or type(error).__name__,
            )
        except PersistenceError:
            logger.error("Failed to persist agent failure status")
        _structured_log(
            trace_id=trace_id,
            session_id=session_id,
            run_id=run_uuid,
            status="failed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            error_code=error.provider_code or type(error).__name__,
        )
        logger.warning(
            "Agent core failed provider=%s status_code=%s provider_code=%s",
            error.provider,
            error.status_code,
            error.provider_code,
        )
        return JSONResponse(
            {"error": "تعذر الحصول على رد من الوكيل الآن. حاول مرة أخرى."},
            status_code=502,
        )
    except Exception as error:
        try:
            await finish_run(
                run_id=run_uuid,
                status="failed",
                error_code=type(error).__name__,
            )
        except PersistenceError:
            logger.error("Failed to persist agent failure status")
        _structured_log(
            trace_id=trace_id,
            session_id=session_id,
            run_id=run_uuid,
            status="failed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            error_code=type(error).__name__,
        )
        logger.error("Agent core failed exception_type=%s", type(error).__name__)
        return JSONResponse(
            {"error": "تعذر الحصول على رد من الوكيل الآن. حاول مرة أخرى."},
            status_code=502,
        )

    final_text = str(result.output).strip()
    new_messages_json = result.new_messages_json()
    try:
        message_count = await append_new_messages(
            session_id=session_id,
            run_id=run_uuid,
            new_messages_json=new_messages_json,
        )
        await finish_run(run_id=run_uuid, status="succeeded")
    except PersistenceError as error:
        logger.error("Agent result persistence failed error_type=%s", type(error).__name__)
        try:
            await finish_run(
                run_id=run_uuid,
                status="failed",
                error_code=type(error).__name__,
            )
        except PersistenceError:
            logger.error("Failed to persist agent persistence failure status")
        _structured_log(
            trace_id=trace_id,
            session_id=session_id,
            run_id=run_uuid,
            status="failed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            error_code=type(error).__name__,
        )
        return JSONResponse(
            {"error": "تعذر الحصول على رد من الوكيل الآن. حاول مرة أخرى."},
            status_code=502,
        )

    _structured_log(
        trace_id=trace_id,
        session_id=session_id,
        run_id=run_uuid,
        status="succeeded",
        latency_ms=int((time.perf_counter() - started_at) * 1000),
    )
    logger.info(
        "Agent run completed message_bytes=%d persisted_messages=%d",
        len(new_messages_json),
        message_count,
    )
    if not final_text:
        return JSONResponse(
            {"error": "لم يُرجع النموذج ردًا نصيًا."},
            status_code=502,
        )
    return JSONResponse({"reply": final_text})


if __name__ == "__main__":
    server.run(
        "streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        streamable_http_path="/mcp",
    )