import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import time
import uuid
from collections import defaultdict
from html.parser import HTMLParser
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen


logger = logging.getLogger("ahmed_agent.web_search")
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
PAGE_FETCH_TIMEOUT_SECONDS = 15
MAX_QUERY_LENGTH = 1000
MAX_RESULTS = 10
MAX_RESEARCH_QUERIES = 3
MAX_RESEARCH_CANDIDATES = 12
RESEARCH_MODES = {"FAST", "DEEP"}
MAX_DEEP_SOURCES = 6
MAX_CONCURRENT_SEARCHES = 2
MAX_TAVILY_RETRIES = 2
TEMPORARY_TAVILY_STATUSES = {429, 500, 502, 503, 504}
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


class _PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._published_dates: list[str] = []
        self._other_dates: list[str] = []

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
                    if "published" in key or "datepublished" in key:
                        self._published_dates.append(content)
                    else:
                        self._other_dates.append(content)
        if lowered_tag == "time":
            date_value = attributes.get("datetime", "").strip()
            if date_value:
                self._published_dates.append(date_value)

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
    def published_at(self) -> str | None:
        candidate = (
            self._published_dates[0]
            if self._published_dates
            else (self._other_dates[0] if self._other_dates else None)
        )
        return _valid_date_value(candidate)


def _valid_date_value(value: str | None) -> str | None:
    if not value or not re.search(r"\b(?:19|20)\d{2}\b", value):
        return None
    return value


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


async def _fetch_page(
    url: str,
    fallback_published_at: str | None = None,
) -> dict[str, str | None] | None:
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
            published_at = parser.published_at
        else:
            title = ""
            text = " ".join(html.split())
            published_at = None
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
            "date": _valid_date_value(published_at)
            or _valid_date_value(fallback_published_at),
            "published_at": _valid_date_value(published_at)
            or _valid_date_value(fallback_published_at),
            "snippet": snippet,
        }
    except Exception as error:
        logger.exception("Failed to fetch page url=%s error=%s", url, error)
        return None


def _tavily_search_sync(
    query: str,
    max_results: int,
    api_key: str,
    search_depth: str = "advanced",
) -> tuple[str, dict[str, object]]:
    payload = json.dumps(
        {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
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


def _valid_query(query: str) -> str:
    return query.strip() if isinstance(query, str) else ""


def _domain_for_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname.removeprefix("www.")


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}{path}"


def _classify_query(query: str) -> str:
    lowered = query.casefold()
    if any(
        marker in lowered
        for marker in (
            "official",
            "primary source",
            "رسمي",
            "المصدر الأصلي",
            "توثيق رسمي",
        )
    ):
        return "official"
    if any(
        marker in lowered
        for marker in (
            "latest",
            "breaking news",
            "current news",
            "أخبار",
            "خبر",
            "آخر المستجدات",
            "اليوم",
        )
    ):
        return "current_news"
    if any(
        marker in lowered
        for marker in (
            "academic",
            "scientific",
            "research paper",
            "study",
            "arxiv",
            "evidence",
            "consensus",
            "disputed",
            "controversial",
            "بحث علمي",
            "دراسة",
            "أكاديمي",
        )
    ):
        return "academic"
    if any(
        marker in lowered
        for marker in (
            "law",
            "legal",
            "regulation",
            "government",
            "قانون",
            "قانوني",
            "حكومي",
            "لائحة",
        )
    ):
        return "legal_government"
    if any(
        marker in lowered
        for marker in (
            "github",
            "documentation",
            "docs",
            "api",
            "sdk",
            "python",
            "javascript",
            "technical",
            "توثيق",
            "برمجة",
            "تقني",
        )
    ):
        return "technical"
    if any(
        marker in lowered
        for marker in ("reddit", "forum", "community", "social", "مجتمع", "منتدى")
    ):
        return "social_community"
    return "general_web"


def _research_queries(query: str, query_type: str, mode: str) -> list[str]:
    queries = [query]
    if mode == "FAST":
        return queries

    suffixes = {
        "official": (
            "official primary documentation",
            "official repository or organization source",
        ),
        "current_news": (
            "latest official statement news",
            "international English coverage independent sources",
        ),
        "academic": (
            "research paper study primary academic source",
            "site:edu OR site:ac.uk academic evidence",
        ),
        "technical": (
            "official documentation repository",
            "implementation guide independent technical source",
        ),
        "legal_government": (
            "official government primary source",
            "regulation text government or court source",
        ),
        "social_community": (
            "community discussion independent sources",
            "English and international community sources",
        ),
        "general_web": (
            "English international sources",
            "independent analysis and primary sources",
        ),
    }[query_type]
    for suffix in suffixes:
        candidate = f"{query} {suffix}"
        if candidate not in queries:
            queries.append(candidate)
    return queries[:MAX_RESEARCH_QUERIES]


def _source_type(domain: str, url: str, title: str, query_type: str) -> tuple[str, bool]:
    lowered_domain = domain.casefold()
    lowered_url = url.casefold()
    official_documentation_domains = (
        "modelcontextprotocol.io",
        "python.org",
        "openai.com",
        "docs.anthropic.com",
        "docs.github.com",
    )
    academic_domains = (
        "arxiv.org",
        "frontiersin.org",
        "nature.com",
        "sciencedirect.com",
        "springer.com",
        "pmc.ncbi.nlm.nih.gov",
        "pubmed.ncbi.nlm.nih.gov",
    )
    if any(
        lowered_domain == host or lowered_domain.endswith(f".{host}")
        for host in official_documentation_domains
    ):
        return "official_documentation", True
    if lowered_domain.endswith("europa.eu") or lowered_domain.endswith(".int"):
        return "government", True
    if any(
        lowered_domain == host or lowered_domain.endswith(f".{host}")
        for host in academic_domains
    ):
        return "academic", False
    if lowered_domain.endswith(".gov") or ".gov." in lowered_domain:
        return "government", True
    if lowered_domain.endswith(".edu") or ".ac." in lowered_domain:
        return "academic", True
    if lowered_domain == "github.com" or lowered_domain.endswith(".github.io"):
        if any(
            marker in lowered_url
            for marker in ("modelcontextprotocol", "openai", "python", "official")
        ):
            return "official_repository", True
        return "repository", False
    if any(marker in lowered_domain for marker in ("wikipedia.org", "reddit.com", "x.com")):
        return "social_community", False
    if any(
        marker in lowered_domain
        for marker in ("news", "reuters.com", "apnews.com", "bbc.com")
    ):
        return "news", False
    if query_type == "social_community":
        return "social_community", False
    return "general_web", False


def _enrich_source(
    page: dict[str, str | None],
    tavily_item: dict[str, object],
    query: str,
    query_type: str,
) -> dict[str, object]:
    url = str(page.get("url") or "")
    title = str(page.get("title") or "")
    domain = _domain_for_url(url)
    source_type, is_primary = _source_type(domain, url, title, query_type)
    published_at = page.get("published_at") or tavily_item.get("published_date")
    score_value = tavily_item.get("score")
    try:
        tavily_score = float(score_value) if score_value is not None else 0.0
    except (TypeError, ValueError):
        tavily_score = 0.0
    priority = 100 if is_primary else 0
    if source_type in {"official_documentation", "official_repository", "government", "academic"}:
        priority += 25
    priority += round(tavily_score * 20, 4)
    if published_at:
        priority += 2
    return {
        "title": title,
        "url": url,
        "domain": domain,
        "published_at": str(published_at) if published_at else None,
        "date": str(published_at) if published_at else None,
        "source_type": source_type,
        "primary_or_secondary": "primary" if is_primary else "secondary",
        "snippet": page.get("snippet") or "",
        "query": query,
        "tavily_score": tavily_score,
        "_priority": priority,
    }


async def _run_tavily_query(
    query: str,
    max_results: int,
    api_key: str,
) -> list[dict[str, object]] | None:
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
        logger.exception("Tavily search failed query=%r error=%s", query, error)
        return None

    raw_results = tavily_response.get("results", [])
    if not isinstance(raw_results, list):
        logger.error("Tavily response has invalid results field query=%r", query)
        return None

    pages: list[dict[str, object]] = []
    for item in raw_results[:max_results]:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            logger.error("Tavily result had no usable URL: %r", item)
            continue
        fallback_date = item.get("published_date")
        page = await _fetch_page(
            url,
            fallback_date if isinstance(fallback_date, str) else None,
        )
        if page is not None:
            pages.append({**page, "_tavily_item": item, "_query": query})
    return pages


def _rank_and_deduplicate(
    candidates: list[dict[str, object]],
    query_type: str,
    mode: str,
) -> tuple[list[dict[str, object]], int]:
    best_by_url: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        url = str(candidate.get("url") or "")
        normalized = _normalized_url(url)
        if not normalized:
            continue
        existing = best_by_url.get(normalized)
        if existing is None or candidate.get("_priority", 0) > existing.get("_priority", 0):
            best_by_url[normalized] = candidate

    ordered = sorted(
        best_by_url.values(),
        key=lambda item: float(item.get("_priority", 0)),
        reverse=True,
    )
    selected: list[dict[str, object]] = []
    domains_used: dict[str, int] = defaultdict(int)
    limit = 5 if mode == "FAST" else MAX_RESEARCH_CANDIDATES
    for item in ordered:
        domain = str(item.get("domain") or "")
        if domains_used[domain] >= 2:
            continue
        domains_used[domain] += 1
        item = {
            key: value
            for key, value in item.items()
            if not key.startswith("_")
        }
        selected.append(item)
        if len(selected) >= limit:
            break
    logger.info(
        "Research ranking completed mode=%s query_type=%s candidates=%d selected=%d "
        "independent_domains=%d",
        mode,
        query_type,
        len(candidates),
        len(selected),
        len({item.get("domain") for item in selected}),
    )
    return selected, len(candidates)


async def web_search(query: str, max_results: int = 5) -> dict[str, object]:
    query = _valid_query(query)
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

    pages = await _run_tavily_query(query, max_results, api_key)
    if pages is None:
        return {
            "ok": False,
            "error": "تعذر تنفيذ البحث الآن. حاول مرة أخرى لاحقًا.",
            "results": [],
        }

    if not pages:
        logger.error("Tavily returned no pages that could be read")
        return {
            "ok": False,
            "error": "لم نتمكن من قراءة صفحات نتائج البحث.",
            "results": [],
        }

    logger.info("web_search completed query=%r pages_opened=%d", query, len(pages))
    results = [
        _enrich_source(
            page,
            page.get("_tavily_item")
            if isinstance(page.get("_tavily_item"), dict)
            else {},
            query,
            "general_web",
        )
        for page in pages
    ]
    return {"ok": True, "query": query, "results": results}


async def research_search(query: str, mode: str = "FAST") -> dict[str, object]:
    query = _valid_query(query)
    mode = mode.upper().strip() if isinstance(mode, str) else ""
    if not query or len(query) > MAX_QUERY_LENGTH:
        return {
            "ok": False,
            "error": "يجب أن يكون البحث بين 1 و1000 حرف.",
            "results": [],
        }
    if mode not in RESEARCH_MODES:
        return {
            "ok": False,
            "error": "وضع البحث يجب أن يكون FAST أو DEEP.",
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

    query_type = _classify_query(query)
    queries = _research_queries(query, query_type, mode)
    logger.info(
        "research_search started mode=%s query_type=%s query_count=%d",
        mode,
        query_type,
        len(queries),
    )
    candidates: list[dict[str, object]] = []
    for related_query in queries:
        pages = await _run_tavily_query(related_query, 5, api_key)
        if not pages:
            logger.warning("research_search query returned no readable pages: %r", related_query)
            continue
        for page in pages:
            item = page.get("_tavily_item")
            if not isinstance(item, dict):
                continue
            candidates.append(
                _enrich_source(
                    page,
                    item,
                    str(page.get("_query") or related_query),
                    query_type,
                )
            )

    results, candidate_count = _rank_and_deduplicate(candidates, query_type, mode)
    if not results:
        return {
            "ok": False,
            "error": "لم نتمكن من العثور على مصادر قابلة للقراءة.",
            "results": [],
            "query_type": query_type,
            "mode": mode,
            "tavily_requests": len(queries),
        }

    logger.info(
        "research_search completed mode=%s query_type=%s tavily_requests=%d "
        "candidates=%d selected=%d",
        mode,
        query_type,
        len(queries),
        candidate_count,
        len(results),
    )
    return {
        "ok": True,
        "query": query,
        "mode": mode,
        "query_type": query_type,
        "queries": queries,
        "tavily_requests": len(queries),
        "candidate_count": candidate_count,
        "independent_domains": len({item.get("domain") for item in results}),
        "results": results,
    }


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
    server.tool(
        description=(
            "Performs FAST or DEEP multi-query web research with Tavily. "
            "Classifies the request, prioritizes primary sources, opens pages, "
            "deduplicates domains, and returns ranked source metadata."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        structured_output=True,
    )(research_search)