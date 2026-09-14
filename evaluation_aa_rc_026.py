from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from architecture_evidence import inspect_architecture_evidence
from evaluation_baseline import execute_real_case
from semantic_evaluation import evaluate_case


ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "real-cases-validated.json"
CONTRACT_PATH = ROOT / "semantic-evaluation-contract-v11.json"
EVALUATION_ARTIFACT = ROOT / "aa-rc-026-build-vs-buy-evaluation-2026-09-14.json"
INTEGRITY_ARTIFACT = ROOT / "aa-rc-026-build-vs-buy-integrity-2026-09-14.json"

OPENAI_DOCUMENTS: tuple[dict[str, Any], ...] = (
    {
        "key": "responses_api_tools",
        "url": "https://platform.openai.com/docs/guides/tools",
        "markers": ("Using tools", "Responses API", "Web search", "File search"),
    },
    {
        "key": "agents_sdk",
        "url": "https://platform.openai.com/docs/guides/agents/sdk",
        "markers": ("Agents SDK", "runner", "handoffs", "tracing"),
    },
    {
        "key": "model_capabilities",
        "url": "https://platform.openai.com/docs/models",
        "markers": ("Compare model capabilities", "Context window", "Web search"),
    },
    {
        "key": "pricing",
        "url": "https://platform.openai.com/docs/pricing",
        "markers": ("Pricing information", "Input tokens", "Output tokens", "tool"),
    },
)


class _VisibleTextParser:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self._skip_depth = 0

    def feed(self, document: str) -> None:
        for match in re.finditer(
            r"<(script|style|svg)\b[^>]*>.*?</\1\s*>|<[^>]+>|([^<]+)",
            document,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            if match.group(2) is not None:
                self.parts.append(html.unescape(match.group(2)))

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def _extract_title(document: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", document, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()


def _bounded_snippets(text: str, markers: tuple[str, ...]) -> list[str]:
    lowered = text.casefold()
    snippets: list[str] = []
    for marker in markers:
        start = lowered.find(marker.casefold())
        if start < 0:
            continue
        left = max(0, start - 180)
        right = min(len(text), start + len(marker) + 520)
        snippets.append(text[left:right].strip())
    return snippets[:4]


def fetch_openai_external_evidence() -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    retrieved_at = datetime.now(timezone.utc).isoformat()
    for document in OPENAI_DOCUMENTS:
        request = urllib.request.Request(
            document["url"],
            headers={"User-Agent": "Ahmed-Agent-AA-RC-026-Evaluator/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            status = int(response.status)
            content_type = response.headers.get("Content-Type", "")
        if status != 200 or "text/html" not in content_type.casefold():
            raise RuntimeError(
                f"Official OpenAI documentation unavailable: {document['url']}"
            )
        raw = body.decode("utf-8", errors="replace")
        parser = _VisibleTextParser()
        parser.feed(raw)
        text = parser.text()
        snippets = _bounded_snippets(text, document["markers"])
        if not snippets:
            raise RuntimeError(
                f"Official OpenAI documentation did not expose expected content: "
                f"{document['url']}"
            )
        evidence.append(
            {
                "key": document["key"],
                "url": document["url"],
                "title": _extract_title(raw),
                "source_identity": "external_openai_official",
                "verification_status": "UNVERIFIED_EXTERNAL",
                "retrieved_at": retrieved_at,
                "http_status": status,
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "snippets": snippets,
            }
        )
    return evidence


def _architecture_summary(result: dict[str, Any]) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    groups: dict[str, Any] = {}
    for group_name, group in result.get("groups", {}).items():
        group_citations: list[dict[str, Any]] = []
        for evidence_kind in (
            "implementation_evidence",
            "wiring_evidence",
            "test_evidence",
        ):
            for item in group.get(evidence_kind, []):
                if not isinstance(item, dict):
                    continue
                citation = {
                    "group": group_name,
                    "evidence_kind": evidence_kind,
                    "relative_source_path": item.get("relative_source_path"),
                    "line_start": item.get("line_start"),
                    "line_end": item.get("line_end"),
                    "file_sha256": item.get("file_sha256"),
                    "trust_classification": item.get("trust_classification"),
                    "verification_status": item.get("verification_status"),
                }
                group_citations.append(citation)
                citations.append(citation)
        groups[group_name] = {
            "status": group.get("status"),
            "evidence_file_hashes": group.get("evidence_file_hashes", {}),
            "citations": group_citations[:12],
            "architecture_unchanged": group.get("architecture_unchanged"),
        }
    return {
        "status": result.get("status"),
        "architecture_fingerprint": result.get("architecture_fingerprint"),
        "groups": groups,
        "citation_count": len(citations),
        "citations": citations[:48],
        "limitations": result.get("limitations", []),
    }


def build_comparison_matrix() -> list[dict[str, Any]]:
    return [
        {
            "criterion": "current_project_state",
            "build_assessment": "Continue the existing architecture and its evidence/provenance boundaries.",
            "buy_assessment": "Use OpenAI components as an integration target, not as proof that Ahmed Agent should be rebuilt.",
            "evidence_refs": ["project:architecture_fingerprint", "external:responses_api_tools"],
        },
        {
            "criterion": "migration_cost_complexity",
            "build_assessment": "Incremental integration preserves current persistence, policy, and evidence contracts.",
            "buy_assessment": "Adopting Responses API tools or Agents SDK requires mapping the existing runtime, tools, approvals, persistence, and provenance boundaries.",
            "evidence_refs": [
                "project:runtime",
                "project:persistence_state_recovery",
                "project:policy_security",
                "external:responses_api_tools",
                "external:agents_sdk",
            ],
        },
        {
            "criterion": "maintenance_burden",
            "build_assessment": "Retain ownership of the current execution, recovery, policy, and evidence code.",
            "buy_assessment": "OpenAI-managed tool and agent capabilities can reduce custom orchestration, but add dependency on external API behavior and documentation.",
            "evidence_refs": ["project:persistence_state_recovery", "external:agents_sdk"],
        },
        {
            "criterion": "quality_control",
            "build_assessment": "Current evidence, citation, policy, and evaluation layers preserve local control over claims and gates.",
            "buy_assessment": "OpenAI tools and model capabilities add features, but do not replace Ahmed Agent's project-level quality and governance gates.",
            "evidence_refs": [
                "project:evidence_provenance",
                "project:evaluation",
                "external:responses_api_tools",
                "external:model_capabilities",
            ],
        },
        {
            "criterion": "operating_cost",
            "build_assessment": "Cost remains dependent on the providers and models selected by the current runtime; no unsupported exact spend claim is made.",
            "buy_assessment": "OpenAI model and tool usage must be budgeted against the current official pricing page for the selected models and tools.",
            "evidence_refs": ["project:actions_integrations", "external:pricing"],
        },
        {
            "criterion": "features_gained_lost",
            "build_assessment": "Keep existing capabilities and add only justified integrations.",
            "buy_assessment": "Potential gains include OpenAI Responses tools, Agents SDK patterns, and access to the current model catalog; potential losses include local control or portability if adopted as the sole runtime.",
            "evidence_refs": [
                "project:runtime",
                "project:actions_integrations",
                "external:responses_api_tools",
                "external:agents_sdk",
                "external:model_capabilities",
            ],
        },
        {
            "criterion": "provider_independence",
            "build_assessment": "Preserve the provider boundary and treat OpenAI as an option rather than the only execution path.",
            "buy_assessment": "A full replacement increases provider coupling unless the existing provider abstraction and fallback boundary remain intact.",
            "evidence_refs": ["project:actions_integrations", "project:policy_security"],
        },
        {
            "criterion": "local_self_hosted_fallback",
            "build_assessment": "Keep this as an explicit design constraint; the current evidence does not claim that OpenAI supplies a self-hosted fallback.",
            "buy_assessment": "OpenAI official documentation supports hosted APIs/SDK usage in this comparison; it is not evidence of a local or self-hosted OpenAI fallback.",
            "evidence_refs": ["project:actions_integrations", "external:agents_sdk"],
        },
        {
            "criterion": "provenance_governance",
            "build_assessment": "Retain project provenance, source identity, policy, and evaluation gates around any provider.",
            "buy_assessment": "External tool/agent features must remain classified as external evidence and must not replace local governance or source provenance.",
            "evidence_refs": [
                "project:evidence_provenance",
                "project:policy_security",
                "external:responses_api_tools",
                "external:agents_sdk",
            ],
        },
        {
            "criterion": "recommendation",
            "recommendation": "Continue Ahmed Agent incrementally; do not rebuild solely because OpenAI offers newer hosted agent capabilities. Evaluate a bounded OpenAI integration only where it improves a measured gap while preserving provider independence, provenance, governance, and fallback boundaries.",
            "evidence_refs": ["project:architecture_fingerprint", "external:model_capabilities", "external:pricing"],
        },
    ]


def _load_case() -> dict[str, Any]:
    document = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return next(case for case in document["cases"] if case["id"] == "AA-RC-026")


def _load_contract_case() -> dict[str, Any]:
    document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return next(
        case
        for case in document["cases"]
        if case["case_id"] == "AA-RC-026"
    )


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": trace.get("run_id"),
        "execution_status": trace.get("execution_status"),
        "execution_classification": trace.get("execution_classification"),
        "tool_names": sorted(
            {
                call.get("name")
                for call in trace.get("tool_calls", [])
                if isinstance(call, dict) and call.get("name")
            }
        ),
        "citation_count": len(trace.get("citations", [])),
        "project_evidence_citation_count": len(trace.get("evidence_provenance", [])),
        "external_evidence_count": len(trace.get("external_evidence_provenance", [])),
        "evidence_preconditions": trace.get("evidence_preconditions"),
        "runtime_cleanup": trace.get("runtime_cleanup"),
        "raw_trace_saved": False,
        "answer_saved": False,
    }


async def execute_aa_rc_026(
    *,
    base_url: str,
    owner_token: str,
    provider: str = "gemini",
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    architecture = _architecture_summary(inspect_architecture_evidence())
    external = await asyncio.to_thread(fetch_openai_external_evidence)
    case = _load_case()
    case = {
        **case,
        "input": (
            "قارن build-vs-buy لـAhmed Agent باستخدام architecture evidence الحالية "
            "والـcitations. استخدم web_search فقط للوثائق الرسمية الحالية من OpenAI "
            "وللمواضيع التالية: Responses API وأدواته، Agents SDK، قدرات النماذج، "
            "والتسعير. افصل external evidence عن project evidence. غطِّ صراحةً: "
            "current project state، migration cost/complexity، maintenance burden، "
            "quality/control، operating cost، features gained/lost، provider "
            "independence، local/self-hosted fallback، provenance/governance، ثم "
            "recommendation بأسباب قابلة للاستشهاد. لا توصي بإعادة البناء لمجرد "
            "أن الحل أحدث، وامتنع عن أي ادعاء لا يكفيه الدليل."
        ),
    }
    started = time.perf_counter()
    trace = await execute_real_case(
        case,
        base_url=base_url,
        owner_token=owner_token,
        provider=provider,
        timeout_seconds=timeout_seconds,
    )
    trace["targeted_latency_ms"] = int((time.perf_counter() - started) * 1000)
    semantic = evaluate_case(
        contract_case=_load_contract_case(),
        trace=trace,
    )
    report = {
        "schema_version": "aa-rc-026-targeted-evaluation.v1",
        "case_id": "AA-RC-026",
        "evaluation_version": "2026-09-14.build-vs-buy.openai-only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "external_evidence_policy": {
            "allowed_source_identity": "external_openai_official",
            "allowed_domains": [
                "platform.openai.com",
                "developers.openai.com",
                "openai.com",
                "openai.github.io",
            ],
            "verification_status": "UNVERIFIED_EXTERNAL",
            "project_evidence_must_remain_separate": True,
        },
        "project_evidence": architecture,
        "external_evidence": external,
        "comparison_matrix": build_comparison_matrix(),
        "targeted_trace": _trace_summary(trace),
        "semantic_evaluation": {
            "semantic_status": semantic.get("semantic_status"),
            "execution_status": semantic.get("execution_status"),
            "execution_classification": semantic.get("execution_classification"),
            "dimensions": {
                key: value.get("status")
                for key, value in semantic.get("dimensions", {}).items()
                if isinstance(value, dict)
            },
            "independent_review": None,
        },
        "recommendation": {
            "status": (
                "READY"
                if trace.get("evidence_preconditions", {}).get("status") == "READY"
                else "NOT_DETERMINED"
            ),
            "text": (
                "Continue Ahmed Agent incrementally; do not rebuild solely because "
                "OpenAI offers newer hosted agent capabilities."
            ),
        },
    }
    return report


def _integrity_record(report: dict[str, Any]) -> dict[str, Any]:
    EVALUATION_ARTIFACT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    files = []
    for path in (EVALUATION_ARTIFACT, CONTRACT_PATH):
        data = path.read_bytes()
        files.append(
            {
                "file": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
    return {
        "schema_version": "aa-rc-026-integrity.v1",
        "case_id": "AA-RC-026",
        "evaluation_version": report["evaluation_version"],
        "artifact": str(EVALUATION_ARTIFACT.relative_to(ROOT)),
        "files": files,
        "external_evidence_count": len(report["external_evidence"]),
        "project_architecture_fingerprint": report["project_evidence"][
            "architecture_fingerprint"
        ],
        "targeted_execution_status": report["targeted_trace"]["execution_status"],
        "evidence_precondition_status": report["targeted_trace"][
            "evidence_preconditions"
        ]["status"],
        "semantic_status": report["semantic_evaluation"]["semantic_status"],
        "raw_trace_saved": False,
    }


async def _main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--provider", default="gemini")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()
    import os

    owner_token = os.environ.get("AHMED_OWNER_TOKEN")
    if not owner_token:
        raise SystemExit("AUTHENTICATED_EVALUATION_PRINCIPAL_BLOCKED")
    report = await execute_aa_rc_026(
        base_url=args.base_url,
        owner_token=owner_token,
        provider=args.provider,
        timeout_seconds=args.timeout_seconds,
    )
    integrity = _integrity_record(report)
    INTEGRITY_ARTIFACT.write_text(
        json.dumps(integrity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(EVALUATION_ARTIFACT.relative_to(ROOT)),
                "integrity": str(INTEGRITY_ARTIFACT.relative_to(ROOT)),
                "status": report["recommendation"]["status"],
                "semantic_status": report["semantic_evaluation"]["semantic_status"],
                "evidence_preconditions": report["targeted_trace"][
                    "evidence_preconditions"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main_async())