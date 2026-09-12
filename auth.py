from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from starlette.requests import Request

from config import AHMED_OWNER_USER_ID
from persistence import record_auth_event

_SAFE_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    display_name: str | None = None


def get_authenticated_user(request: Request) -> AuthenticatedUser | None:
    """Return only identity verified by an installed authentication middleware.

    Request headers are intentionally ignored. Replit's documentation does not
    treat X-Replit-User-Id as a security-critical identity source.
    """

    verified = getattr(request.state, "authenticated_user", None)
    if isinstance(verified, AuthenticatedUser):
        return verified
    if isinstance(verified, dict):
        user_id = str(verified.get("user_id") or "").strip()
        if user_id and _SAFE_USER_ID.fullmatch(user_id):
            display_name = str(verified.get("display_name") or "").strip() or None
            return AuthenticatedUser(user_id=user_id, display_name=display_name)
    return None


async def authorize_owner(
    request: Request,
    *,
    endpoint: str,
) -> tuple[AuthenticatedUser | None, int, str | None]:
    user = get_authenticated_user(request)
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
    return {
        "status": "READY" if AHMED_OWNER_USER_ID else "NOT_CONFIGURED",
        "mode": "verified_auth_middleware_only",
        "owner_configured": bool(AHMED_OWNER_USER_ID),
        "safe_error_code": None if AHMED_OWNER_USER_ID else "OWNER_NOT_CONFIGURED",
    }