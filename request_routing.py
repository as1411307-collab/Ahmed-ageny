from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RequestCapability(StrEnum):
    PROJECT_STATE = "project_state"
    RUNTIME_ARCHITECTURE = "runtime_architecture"
    SOURCE_STATUS = "source_status"
    MY_FILES = "my_files"
    EXTERNAL_WEB_RESEARCH = "external_web_research"
    GENERAL = "general"


@dataclass(frozen=True)
class RouteDecision:
    capability: RequestCapability
    required_capabilities: tuple[str, ...]
    abstain_if_evidence_missing: bool


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def classify_request(
    message: str,
    *,
    scope: str = "WEB",
) -> RouteDecision:
    """Classify a request into a bounded evidence or external-search route.

    This is intentionally capability-based rather than case-based. The model
    still writes the final response, but evidence-bearing routes are preflighted
    before model execution so an empty result becomes an explicit abstention
    boundary instead of an invitation to guess.
    """

    normalized = " ".join(message.casefold().split())
    if not normalized:
        return RouteDecision(RequestCapability.GENERAL, (), False)

    source_status_terms = (
        "source status",
        "حالة المصدر",
        "حالة المصادر",
        "search provider",
        "page fetcher",
        "مكونات البحث",
        "جاهز",
        "غير جاهز",
        "needs_setup",
    )
    if _contains_any(normalized, source_status_terms):
        return RouteDecision(
            RequestCapability.SOURCE_STATUS,
            ("inspect_source_status",),
            True,
        )

    external_web_terms = (
        "web search",
        "web research",
        "search the web",
        "ابحث على الويب",
        "بحث على الويب",
        "ابحث في الويب",
        "بحث خارجي",
        "مصادر خارجية",
        "أحدث توثيق",
        "latest documentation",
        "official documentation",
    )
    if _contains_any(normalized, external_web_terms):
        return RouteDecision(
            RequestCapability.EXTERNAL_WEB_RESEARCH,
            ("web_search",),
            True,
        )

    my_files_terms = (
        "my_files",
        "uploaded file",
        "uploaded files",
        "الملف المرفوع",
        "الملفات المرفوعة",
        "الملفات المتاحة",
        "الملف الفعلي",
        "master file",
        "incident evidence",
        "أدلة الحوادث",
        "source of truth",
        "مصدر الحقيقة",
    )
    if scope == "MY_FILES" or _contains_any(normalized, my_files_terms):
        return RouteDecision(
            RequestCapability.MY_FILES,
            ("search_my_files", "inspect_source_of_truth"),
            True,
        )

    runtime_terms = (
        "runtime",
        "وقت التشغيل",
        "المعمارية",
        "architecture",
        "foundation",
        "runnable",
        "entrypoint",
        "deployment boundary",
        "حد النشر",
        "process",
        "processes",
        "worker",
        "workers",
        "deploy",
        "publish",
        "النشر",
    )
    if _contains_any(normalized, runtime_terms):
        return RouteDecision(
            RequestCapability.RUNTIME_ARCHITECTURE,
            ("inspect_runtime_evidence", "inspect_architecture_evidence"),
            True,
        )

    project_terms = (
        "ahmed agent",
        "project",
        "المشروع",
        "حالة المشروع",
        "المحادثات السابقة",
        "previous conversation",
        "what was completed",
        "ما تم إنجازه",
        "الخطوة التالية",
        "الترتيب",
        "sequence",
        "router",
        "الراوتر",
    )
    if _contains_any(normalized, project_terms):
        return RouteDecision(
            RequestCapability.PROJECT_STATE,
            ("inspect_runtime_evidence",),
            True,
        )

    evidence_terms = (
        "verify",
        "check",
        "inspect",
        "تحقق",
        "افحص",
        "تأكد",
        "هل تم",
        "هل توجد",
    )
    if _contains_any(normalized, evidence_terms):
        return RouteDecision(RequestCapability.PROJECT_STATE, ("inspect_runtime_evidence",), True)

    return RouteDecision(RequestCapability.GENERAL, (), False)