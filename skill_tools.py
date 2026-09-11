import asyncio
import ipaddress
import json
import logging
import os
import socket
from html.parser import HTMLParser
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen


logger = logging.getLogger("ahmed_agent.web_search")
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
PAGE_FETCH_TIMEOUT_SECONDS = 15
MAX_QUERY_LENGTH = 1000
MAX_RESULTS = 10


class _PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._dates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        lowered_tag = tag.lower()
        if lowered_tag in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth += 1
        if lowered_tag == "title":
            self._in_title = True
        if lowered_tag == "meta":
            key = (
                attributes.get("property")
                or attributes.get("name")
                or attributes.get("itemprop")
                or ""
            ).lower()
            if any(marker in key for marker in ("date", "published", "modified", "created")):
                content = attributes.get("content", "").strip()
                if content:
                    self._dates.append(content)
        if lowered_tag == "time":
            date_value = attributes.get("datetime", "").strip()
            if date_value:
                self._dates.append(date_value)

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()
        if lowered_tag == "title":
            self._in_title = False
        if lowered_tag in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self._title_parts.append(text)
        self._text_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self._title_parts).strip()

    @property
    def text(self) -> str:
        return " ".join(self._text_parts).strip()

    @property
    def date(self) -> str | None:
        return self._dates[0] if self._dates else None


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global


async def _is_safe_public_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or hostname.lower() in {"localhost", "localhost.localdomain"}
        or hostname.lower().endswith(".local")
    ):
        return False
    if _is_public_ip(hostname):
        return True
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            443 if parsed.scheme == "https" else 80,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return False
    return bool(addresses) and all(_is_public_ip(item[4][0]) for item in addresses)


def _fetch_page_sync(url: str) -> tuple[str, str]:
    request = UrlRequest(
        url,
        headers={
            "User-Agent": "Ahmed-Agent/1.0",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    with urlopen(request, timeout=PAGE_FETCH_TIMEOUT_SECONDS) as response:
        content_type = response.headers.get_content_type()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace"), content_type


async def _fetch_page(url: str) -> dict[str, str | None] | None:
    if not await _is_safe_public_url(url):
        logger.error("Skipped unsafe or non-public URL: %s", url)
        return None
    try:
        html, content_type = await asyncio.to_thread(_fetch_page_sync, url)
        parser = _PageTextParser()
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser.feed(html)
            title = parser.title
            text = parser.text
            date = parser.date
        else:
            title = ""
            text = " ".join(html.split())
            date = None
        words = text.split()
        if not words:
            logger.error("Opened page but extracted no text: %s", url)
            return None
        if len(words) < 200:
            logger.error(
                "Skipped page with insufficient extracted text url=%s words=%d",
                url,
                len(words),
            )
            return None
        snippet = " ".join(words[:350])
        logger.info(
            "Opened page url=%s content_type=%s words=%d",
            url,
            content_type,
            len(words),
        )
        return {
            "title": title or urlparse(url).netloc,
            "url": url,
            "date": date,
            "snippet": snippet,
        }
    except Exception as error:
        logger.exception("Failed to fetch page url=%s error=%s", url, error)
        return None


def _tavily_search_sync(
    query: str,
    max_results: int,
    api_key: str,
) -> tuple[str, dict[str, object]]:
    payload = json.dumps(
        {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_answer": False,
            "include_raw_content": False,
        }
    ).encode("utf-8")
    request = UrlRequest(
        TAVILY_SEARCH_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Ahmed-Agent/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=PAGE_FETCH_TIMEOUT_SECONDS) as response:
        raw_response = response.read().decode("utf-8", errors="replace")
    parsed_response = json.loads(raw_response)
    if not isinstance(parsed_response, dict):
        raise ValueError("Tavily returned a non-object response")
    return raw_response, parsed_response


async def web_search(query: str, max_results: int = 5) -> dict[str, object]:
    query = query.strip() if isinstance(query, str) else ""
    if not query or len(query) > MAX_QUERY_LENGTH:
        return {
            "ok": False,
            "error": "يجب أن يكون البحث بين 1 و1000 حرف.",
            "results": [],
        }
    if not isinstance(max_results, int) or not 1 <= max_results <= MAX_RESULTS:
        return {
            "ok": False,
            "error": f"عدد النتائج يجب أن يكون بين 1 و{MAX_RESULTS}.",
            "results": [],
        }

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        logger.error("TAVILY_API_KEY is not configured")
        return {
            "ok": False,
            "error": "البحث غير متاح حاليًا لأن إعداد البحث غير مكتمل.",
            "results": [],
        }

    logger.info("Tavily request sent query=%r max_results=%d", query, max_results)
    try:
        raw_response, tavily_response = await asyncio.to_thread(
            _tavily_search_sync,
            query,
            max_results,
            api_key,
        )
        logger.info("Tavily raw response: %s", raw_response)
    except Exception as error:
        logger.exception("Tavily search failed error=%s", error)
        return {
            "ok": False,
            "error": "تعذر تنفيذ البحث الآن. حاول مرة أخرى لاحقًا.",
            "results": [],
        }

    raw_results = tavily_response.get("results", [])
    if not isinstance(raw_results, list):
        logger.error("Tavily response has invalid results field")
        return {"ok": False, "error": "تعذر قراءة نتائج البحث.", "results": []}

    pages: list[dict[str, str | None]] = []
    for item in raw_results[:max_results]:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            logger.error("Tavily result had no usable URL: %r", item)
            continue
        page = await _fetch_page(url)
        if page is not None:
            pages.append(page)

    if not pages:
        logger.error("Tavily returned no pages that could be read")
        return {
            "ok": False,
            "error": "لم نتمكن من قراءة صفحات نتائج البحث.",
            "results": [],
        }

    logger.info("web_search completed query=%r pages_opened=%d", query, len(pages))
    return {"ok": True, "query": query, "results": pages}


def register_skill_tools(server: MCPServer) -> None:
    server.tool(
        description=(
            "Searches the public web with Tavily, opens each returned page, "
            "and extracts a text snippet with source metadata."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        structured_output=True,
    )(web_search)