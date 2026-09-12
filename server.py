import os
import logging
import json
import time
from uuid import UUID, uuid4
from pathlib import Path
from typing import TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from agent_core import (
    GEMINI_MODEL,
    PROVIDER_NAME,
    AgentCoreError,
    parse_message_history,
    provider_health,
    run_ahmed,
)
from auth import authorize_owner
from doctor import get_doctor_report
from persistence import (
    PersistenceError,
    append_new_messages,
    approve_pending_action,
    claim_pending_action_execution,
    complete_pending_action,
    create_run,
    ensure_session,
    finish_run,
    load_message_history,
    reject_pending_action,
    record_tool_event,
)
from config import MAX_UPLOAD_BYTES
from my_files import SUPPORTED_EXTENSIONS, extension_for, ingest_document
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


@server.custom_route("/health/provider", methods=["GET"])
async def provider_health_route(_: Request) -> Response:
    return JSONResponse(provider_health())


@server.custom_route("/doctor", methods=["GET"])
async def doctor_route(request: Request) -> Response:
    user, status_code, error_code = await authorize_owner(
        request,
        endpoint="/doctor",
    )
    if user is None:
        return JSONResponse(
            {"error": "owner authentication required", "code": error_code},
            status_code=status_code,
        )
    report = await get_doctor_report(
        probe_search=request.query_params.get("probe") == "1"
    )
    return JSONResponse(report)


async def _execute_approved_action(
    *,
    action_id: str,
    user_id: str,
) -> dict[str, object]:
    claim = await claim_pending_action_execution(
        action_id=action_id,
        user_id=user_id,
    )
    status = claim.get("status")
    if status in {"not_found", "forbidden"}:
        return {"status": status, "executed": False}
    if not claim.get("should_execute"):
        return {"status": status, "executed": status == "executed"}
    if claim.get("tool_name") != "test_sensitive_action":
        return {"status": "unsupported_action", "executed": False}
    # This internal test action intentionally has no external side effect.
    completed = await complete_pending_action(
        action_id=action_id,
        user_id=user_id,
    )
    return {
        "status": completed.get("status", "ERROR"),
        "executed": completed.get("status") == "executed",
        "side_effect": "none",
    }


@server.custom_route("/actions/{action_id}/approve", methods=["POST"])
async def approve_action(request: Request) -> Response:
    user, status_code, error_code = await authorize_owner(
        request,
        endpoint="/actions/approve",
    )
    if user is None:
        return JSONResponse(
            {"error": "owner authentication required", "code": error_code},
            status_code=status_code,
        )
    try:
        action_id = str(UUID(request.path_params["action_id"]))
    except (KeyError, ValueError):
        return JSONResponse({"error": "action_id غير صالح."}, status_code=400)
    try:
        approval = await approve_pending_action(
            action_id=action_id,
            user_id=user.user_id,
        )
        if approval["status"] == "not_found":
            return JSONResponse({"error": "الإجراء غير موجود."}, status_code=404)
        if approval["status"] == "forbidden":
            return JSONResponse({"error": "لا تملك هذا الإجراء."}, status_code=403)
        if approval["status"] in {"expired", "rejected"}:
            return JSONResponse(
                {"status": approval["status"], "executed": False},
                status_code=409,
            )
        execution = await _execute_approved_action(
            action_id=action_id,
            user_id=user.user_id,
        )
    except PersistenceError:
        logger.exception("Action approval persistence failed")
        return JSONResponse(
            {"error": "تعذر معالجة الموافقة الآن."},
            status_code=503,
        )
    if execution["status"] == "unsupported_action":
        return JSONResponse(
            {"error": "الأداة غير مدعومة في مسار التنفيذ."},
            status_code=422,
        )
    return JSONResponse(
        {
            "action_id": action_id,
            "status": execution["status"],
            "executed": execution["executed"],
            **(
                {"side_effect": execution["side_effect"]}
                if "side_effect" in execution
                else {}
            ),
        }
    )


@server.custom_route("/actions/{action_id}/reject", methods=["POST"])
async def reject_action(request: Request) -> Response:
    user, status_code, error_code = await authorize_owner(
        request,
        endpoint="/actions/reject",
    )
    if user is None:
        return JSONResponse(
            {"error": "owner authentication required", "code": error_code},
            status_code=status_code,
        )
    try:
        action_id = str(UUID(request.path_params["action_id"]))
    except (KeyError, ValueError):
        return JSONResponse({"error": "action_id غير صالح."}, status_code=400)
    try:
        rejection = await reject_pending_action(
            action_id=action_id,
            user_id=user.user_id,
        )
    except PersistenceError:
        logger.exception("Action rejection persistence failed")
        return JSONResponse(
            {"error": "تعذر معالجة الرفض الآن."},
            status_code=503,
        )
    if rejection["status"] == "not_found":
        return JSONResponse({"error": "الإجراء غير موجود."}, status_code=404)
    if rejection["status"] == "forbidden":
        return JSONResponse({"error": "لا تملك هذا الإجراء."}, status_code=403)
    return JSONResponse(
        {
            "action_id": action_id,
            "status": rejection["status"],
            "executed": False,
        }
    )


@server.custom_route("/files/upload", methods=["POST"])
async def files_upload(request: Request) -> Response:
    owner, status_code, error_code = await authorize_owner(
        request,
        endpoint="/files/upload",
    )
    if owner is None:
        return JSONResponse(
            {"error": "owner authentication required", "code": error_code},
            status_code=status_code,
        )
    try:
        form = await request.form()
    except Exception:
        return JSONResponse({"error": "صيغة رفع الملف غير صالحة."}, status_code=400)

    uploads = [item for item in form.getlist("file") if isinstance(item, UploadFile)]
    if not uploads:
        return JSONResponse({"error": "يجب إرفاق ملف واحد على الأقل باسم file."}, status_code=400)

    prepared: list[tuple[UploadFile, str, str | None, bytes]] = []
    for upload in uploads:
        filename = Path(upload.filename or "").name
        extension = extension_for(filename)
        if not filename or extension not in SUPPORTED_EXTENSIONS:
            return JSONResponse(
                {
                    "error": "نوع الملف غير مدعوم.",
                    "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
                    "filename": filename or None,
                },
                status_code=415,
            )
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                {"error": "حجم الملف أكبر من الحد المسموح.", "filename": filename},
                status_code=413,
            )
        prepared.append((upload, filename, upload.content_type, data))

    results: list[dict[str, object]] = []
    try:
        for _, filename, mime_type, data in prepared:
            result = await ingest_document(
                document_id=str(uuid4()),
                filename=filename,
                mime_type=mime_type,
                data=data,
            )
            results.append(result)
    except PersistenceError as error:
        logger.error("File persistence failed error_type=%s", type(error).__name__)
        return JSONResponse(
            {"error": "تعذر حفظ الملف الآن. حاول مرة أخرى."},
            status_code=503,
        )

    if any(result.get("duplicate") for result in results):
        return JSONResponse({"files": results}, status_code=409)
    if any(
        result.get("status") not in {"ready", "embedding_failed"}
        for result in results
    ):
        return JSONResponse({"files": results}, status_code=422)
    if any(result.get("status") == "embedding_failed" for result in results):
        return JSONResponse({"files": results}, status_code=202)
    return JSONResponse({"files": results}, status_code=201)


@server.custom_route("/chat/message", methods=["POST"])
async def chat_message(request: Request) -> Response:
    authenticated_user, status_code, error_code = await authorize_owner(
        request,
        endpoint="/chat/message",
    )
    if authenticated_user is None:
        return JSONResponse(
            {"error": "owner authentication required", "code": error_code},
            status_code=status_code,
        )
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
    scope = payload.get("scope", "WEB")
    if scope not in {"WEB", "MY_FILES"}:
        return JSONResponse(
            {"error": "scope غير صالح. استخدم WEB أو MY_FILES."},
            status_code=400,
        )
    try:
        session_id = _request_uuid(conversation_id, "conversation_id")
        run_uuid = _request_uuid(run_id, "run_id")
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)

    trace_id = str(uuid4())
    started_at = time.perf_counter()
    try:
        await ensure_session(session_id, scope=scope)
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
            user_id=authenticated_user.user_id if authenticated_user else None,
            scope=scope,
            tool_event_recorder=save_tool_event,
        )
    except AgentCoreError as error:
        provider_status = error.provider_status or error.provider_code or type(error).__name__
        try:
            await finish_run(
                run_id=run_uuid,
                status="failed",
                error_code=provider_status,
            )
        except PersistenceError:
            logger.error("Failed to persist agent failure status")
        _structured_log(
            trace_id=trace_id,
            session_id=session_id,
            run_id=run_uuid,
            status="failed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            error_code=provider_status,
        )
        logger.warning(
            "Agent core failed provider=%s status_code=%s provider_status=%s",
            error.provider,
            error.status_code,
            provider_status,
        )
        return JSONResponse(
            (
                {"error": "الخدمة غير متاحة مؤقتًا. حاول لاحقًا."}
                if provider_status == "RATE_LIMITED"
                else {"error": "تعذر الحصول على رد من الوكيل الآن. حاول مرة أخرى."}
            ),
            status_code=503 if provider_status == "RATE_LIMITED" else 502,
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