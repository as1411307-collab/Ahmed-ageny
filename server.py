import os
from pathlib import Path
from typing import TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from openai import AsyncOpenAI
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from skill_tools import register_skill_tools


class PingResult(TypedDict):
    ok: bool
    message: str


server = MCPServer("Ahmed Agent")
WEB_DIR = Path(__file__).parent / "web"
OPENAI_MODEL = "gpt-5.6-terra"


def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.environ["AI_INTEGRATIONS_OPENAI_API_KEY"],
        base_url=os.environ["AI_INTEGRATIONS_OPENAI_BASE_URL"],
    )


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

    try:
        response = await get_openai_client().responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "You are Ahmed Agent, a helpful and concise assistant. "
                "Reply in the same language as the user."
            ),
            input=message,
        )
    except Exception:
        return JSONResponse(
            {"error": "تعذر الحصول على رد من الوكيل الآن. حاول مرة أخرى."},
            status_code=502,
        )

    reply = response.output_text.strip()
    if not reply:
        return JSONResponse(
            {"error": "لم يُرجع النموذج ردًا نصيًا."},
            status_code=502,
        )

    return JSONResponse({"reply": reply})


if __name__ == "__main__":
    server.run(
        "streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        streamable_http_path="/mcp",
    )