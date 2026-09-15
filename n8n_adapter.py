from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen


Transport = Callable[[str, bytes, dict[str, str]], Awaitable[dict[str, object]]]
_WORKFLOW_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class N8NDispatchError(RuntimeError):
    pass


async def _default_transport(
    url: str,
    body: bytes,
    headers: dict[str, str],
) -> dict[str, object]:
    def send() -> dict[str, object]:
        request = UrlRequest(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                parsed: object = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"text": raw[:1000]}
            return {"status": int(response.status), "body": parsed}

    return await asyncio.to_thread(send)


class N8NAdapter:
    """Approval-gated outbound adapter for allowlisted n8n workflows."""

    def __init__(
        self,
        *,
        base_url: str,
        shared_secret: str,
        allowed_workflows: set[str],
        transport: Transport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("invalid n8n base URL")
        if parsed.username or parsed.password:
            raise ValueError("n8n URL must not contain credentials")
        self.base_url = base_url.rstrip("/") + "/"
        self.shared_secret = shared_secret
        self.allowed_workflows = set(allowed_workflows)
        self.transport = transport or _default_transport

    async def dispatch(
        self,
        workflow: str,
        payload: dict[str, Any],
        *,
        action_id: str,
        approved: bool,
    ) -> dict[str, object]:
        if not approved:
            raise N8NDispatchError("explicit approval is required")
        if workflow not in self.allowed_workflows or not _WORKFLOW_RE.fullmatch(workflow):
            raise N8NDispatchError("workflow is not allowlisted")
        if not self.shared_secret:
            raise N8NDispatchError("n8n shared secret is not configured")

        envelope = {
            "action_id": action_id,
            "workflow": workflow,
            "payload": payload,
        }
        body = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(
            self.shared_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Ahmed-Agent/1.0",
            "X-Ahmed-Signature": signature,
            "X-Ahmed-Action-Id": action_id,
        }
        url = self.base_url + quote(workflow, safe="")
        return await self.transport(url, body, headers)


def n8n_adapter_from_env() -> N8NAdapter | None:
    base_url = os.environ.get("N8N_WEBHOOK_BASE_URL", "").strip()
    shared_secret = os.environ.get("N8N_SHARED_SECRET", "").strip()
    allowed = {
        item.strip()
        for item in os.environ.get("N8N_ALLOWED_WORKFLOWS", "").split(",")
        if item.strip()
    }
    if not base_url or not shared_secret or not allowed:
        return None
    try:
        return N8NAdapter(
            base_url=base_url,
            shared_secret=shared_secret,
            allowed_workflows=allowed,
        )
    except ValueError:
        return None
