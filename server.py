import os
import logging
from pathlib import Path
from typing import TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from agent_core import AgentCoreError, parse_message_history, run_ahmed
from skill_tools import register_skill_tools


class PingResult(TypedDict):
    ok: bool
    message: str


server = MCPServer("Ahmed Agent")
WEB_DIR = Path(__file__).parent / "web"
logger = logging.getLogger("ahmed_agent")


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
    for field_name, field_value in (
        ("conversation_id", conversation_id),
        ("run_id", run_id),
    ):
        if field_value is not None and (
            not isinstance(field_value, str) or not 1 <= len(field_value) <= 200
        ):
            return JSONResponse(
                {"error": f"{field_name} غير صالح."},
                status_code=400,
            )

    try:
        result = await run_ahmed(
            message,
            message_history=message_history,
            conversation_id=conversation_id,
            run_id=run_id,
        )
    except AgentCoreError as error:
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
        logger.error("Agent core failed exception_type=%s", type(error).__name__)
        return JSONResponse(
            {"error": "تعذر الحصول على رد من الوكيل الآن. حاول مرة أخرى."},
            status_code=502,
        )

    final_text = str(result.output).strip()
    new_messages_json = result.new_messages_json()
    logger.info(
        "Agent run completed message_bytes=%d",
        len(new_messages_json),
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