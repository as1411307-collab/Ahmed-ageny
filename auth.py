from __future__ import annotations

import asyncio
import importlib
import inspect
import re
from dataclasses import dataclass
from hashlib import sha256

from starlette.requests import Request

from config import AHMED_OWNER_USER_ID
from persistence import record_auth_event

_SAFE_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    display_name: str | None = None


def _user_from_verified_value(value: object) -> AuthenticatedUser | None:
    if isinstance(value, AuthenticatedUser):
        return value
    if isinstance(value, dict):
        user_id = str(
            value.get("user_id")
            or value.get("id")
            or value.get("sub")
            or ""
        ).strip()
        display_name = str(
            value.get("display_name")
            or value.get("name")
            or value.get("username")
            or ""
        ).strip() or None
    else:
        user_id = str(
            getattr(value, "user_id", None)
            or getattr(value, "id", None)
            or getattr(value, "sub", None)
            or ""
        ).strip()
        display_name = str(
            getattr(value, "display_name", None)
            or getattr(value, "name", None)
            or getattr(value, "username", None)
            or ""
        ).strip() or None
    if not user_id or not _SAFE_USER_ID.fullmatch(user_id):
        return None
    return AuthenticatedUser(user_id=user_id, display_name=display_name)


async def get_authenticated_user(request: Request) -> AuthenticatedUser | None:
    """Return only identity verified by an installed authentication middleware.

    Request headers are intentionally ignored. Replit's documentation does not
    treat X-Replit-User-Id as a security-critical identity source.
    """

    verified = _user_from_verified_value(
        getattr(request.state, "authenticated_user", None)
    )
    if verified is not None:
        return verified

    authorization = (request.headers.get("authorization") or "").strip()
    if not authorization.lower().startswith("bearer "):
        return None
    session_token = authorization[7:].strip()
    if not session_token:
        return None
    try:
        auth_module = importlib.import_module("replit.auth")
        verify_session = getattr(auth_module, "verify_session")
        verified_value = await asyncio.to_thread(verify_session, session_token)
        if inspect.isawaitable(verified_value):
            verified_value = await verified_value
        return _user_from_verified_value(verified_value)
    except Exception:
        # Invalid, missing, or unverifiable sessions are all unauthenticated.
        return None


def session_verifier_available() -> bool:
    try:
        auth_module = importlib.import_module("replit.auth")
        return callable(getattr(auth_module, "verify_session", None))
    except (ImportError, AttributeError):
        return False


async def authorize_owner(
    request: Request,
    *,
    endpoint: str,
) -> tuple[AuthenticatedUser | None, int, str | None]:
    user = await get_authenticated_user(request)
    if user is None:
        await _record_auth_attempt(endpoint=endpoint, user=None, result="unauthenticated")
        return None, 401, "AUTHENTICATION_REQUIRED"
    if not AHMED_OWNER_USER_ID:
        await _record_auth_attempt(endpoint=endpoint, user=user, result="owner_not_configured")
        return None, 503, "OWNER_NOT_CONFIGURED"
    if user.user_id != AHMED_OWNER_USER_ID:
        await _record_auth_attempt(endpoint=endpoint, user=user, result="wrong_owner")
        return None, 403, "OWNER_REQUIRED"
    await _record_auth_attempt(endpoint=endpoint, user=user, result="owner_authorized")
    return user, 200, None


async def _record_auth_attempt(
    *,
    endpoint: str,
    user: AuthenticatedUser | None,
    result: str,
) -> None:
    safe_user_hash = (
        sha256(user.user_id.encode("utf-8")).hexdigest()[:16] if user else None
    )
    try:
        await record_auth_event(
            endpoint=endpoint,
            authenticated_owner=result == "owner_authorized",
            safe_user_hash=safe_user_hash,
            result=result,
        )
    except Exception:
        # Authorization must never become dependent on audit availability.
        return


def auth_health() -> dict[str, object]:
    verifier_ready = session_verifier_available()
    return {
        "status": "READY" if AHMED_OWNER_USER_ID and verifier_ready else "NOT_CONFIGURED",
        "mode": "verified_session_token_or_auth_middleware",
        "owner_configured": bool(AHMED_OWNER_USER_ID),
        "session_verifier_available": verifier_ready,
        "safe_error_code": (
            None
            if AHMED_OWNER_USER_ID and verifier_ready
            else "REPLIT_AUTH_VERIFIER_NOT_CONFIGURED"
            if not verifier_ready
            else "OWNER_NOT_CONFIGURED"
        ),
    }