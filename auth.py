from __future__ import annotations

import re
from dataclasses import dataclass

from starlette.requests import Request


_SAFE_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    display_name: str | None = None


def get_authenticated_user(request: Request) -> AuthenticatedUser | None:
    """Read identity injected by the trusted Replit authentication proxy.

    A browser-supplied arbitrary user header is not an authentication mechanism.
    Deployments must place this service behind the configured auth proxy before
    enabling approval operations.
    """

    user_id = (request.headers.get("x-replit-user-id") or "").strip()
    if not user_id or not _SAFE_USER_ID.fullmatch(user_id):
        return None
    display_name = (request.headers.get("x-replit-user-name") or "").strip() or None
    return AuthenticatedUser(user_id=user_id, display_name=display_name)


def auth_health() -> dict[str, object]:
    return {
        "status": "READY",
        "mode": "trusted_replit_proxy_header",
        "safe_error_code": None,
    }