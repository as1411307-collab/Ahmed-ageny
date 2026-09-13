from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_core import MAX_MODEL_REQUESTS, MAX_TOOL_CALLS, provider_model_name


DATASET_PATH = (
    Path(__file__).parent
    / "tests"
    / "fixtures"
    / "evaluation_baseline"
    / "cases.json"
)
DATASET_VERSION = "contract-seed-v1"
REQUIRED_CASE_KEYS = {
    "id",
    "category",
    "provenance",
    "input",
    "expected_behavior",
    "expected_sources",
    "forbidden_behavior",
    "required_tools",
    "forbidden_tools",
    "success_criteria",
    "deterministic_checks",
}
SECRET_FIELD_MARKERS = ("secret", "token", "password", "api_key", "apikey")
SEMANTIC_RUBRIC = {
    "grounding": "Every material claim is supported by the cited evidence.",
    "relevance": "The answer directly addresses the case input.",
    "completeness": "All required parts of the task are addressed.",
    "source_correctness": "The cited source actually supports the claim.",
}
TOOL_NAME_MAPPING = {
    "web_search": {
        "actual": "web_search",
        "status": "available",
        "note": "AgentCore tool name matches.",
    },
    "my_files": {
        "actual": "search_my_files",
        "status": "available",
        "note": "Semantic MY_FILES capability maps to the scoped retrieval tool.",
    },
    "file_access": {
        "actual": None,
        "status": "unavailable",
        "note": "No general file-access AgentCore tool exists.",
    },
    "project_file_access": {
        "actual": None,
        "status": "unavailable",
        "note": "Project workspace inspection is not an AgentCore tool.",
    },
    "deploy": {
        "actual": None,
        "status": "boundary_only",
        "note": "Deployment is a platform action, not an AgentCore tool.",
    },
    "publish": {
        "actual": None,
        "status": "boundary_only",
        "note": "Publishing is a platform action, not an AgentCore tool.",
    },
}
REQUIRED_CHECK_KEYS = {
    "citations_required",
    "schema_fields",
    "approval_required",
    "abstention_required",
}


def _read_dataset_document(path: Path) -> tuple[str, list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        version = raw.get("dataset_version")
        raw_cases = raw.get("cases")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Dataset document is missing dataset_version.")
    else:
        version = DATASET_VERSION
        raw_cases = raw
    if not isinstance(raw_cases, list):
        raise ValueError("Evaluation dataset must contain a cases list.")
    return version, raw_cases


def validate_evaluation_cases(
    raw_cases: list[dict[str, Any]],
    *,
    require_baseline_size: bool = False,
) -> list[dict[str, Any]]:
    if require_baseline_size and not 20 <= len(raw_cases) <= 30:
        raise ValueError("Evaluation baseline must contain 20-30 cases.")
    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    for case in raw_cases:
        if not isinstance(case, dict) or not REQUIRED_CASE_KEYS <= case.keys():
            raise ValueError("Evaluation case is missing required fields.")
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("Evaluation case id must be a non-empty string.")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate evaluation case id: {case['id']}")
        seen_ids.add(case_id)
        if not isinstance(case["input"], str) or not case["input"].strip():
            raise ValueError(f"Evaluation case has empty input: {case_id}")
        checks = case["deterministic_checks"]
        if not isinstance(checks, dict) or not REQUIRED_CHECK_KEYS <= checks.keys():
            raise ValueError(f"Invalid deterministic checks: {case_id}")
        if case["provenance"] not in {"contract_seed", "real_case"}:
            raise ValueError(f"Invalid case provenance: {case_id}")
        if case["provenance"] == "real_case":
            source_reference = case.get("source_reference")
            if not isinstance(source_reference, str) or not source_reference.strip():
                raise ValueError(
                    f"real_case requires a documented source_reference: {case_id}"
                )
        required_tools = set(case["required_tools"])
        forbidden_tools = set(case["forbidden_tools"])
        overlap = required_tools & forbidden_tools
        if overlap:
            raise ValueError(
                f"Evaluation case has conflicting tool expectations: "
                f"{case_id}: {sorted(overlap)}"
            )
        if not isinstance(case["expected_sources"], list):
            raise ValueError(f"expected_sources must be a list: {case_id}")
        if (
            checks.get("expected_sources_required", False)
            and not case["expected_sources"]
        ):
            raise ValueError(f"Expected sources are required: {case_id}")
        validated.append(case)
    return validated


def load_evaluation_cases(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    _, raw_cases = _read_dataset_document(path)
    return validate_evaluation_cases(raw_cases, require_baseline_size=True)


def load_case_document(
    path: Path,
    *,
    require_baseline_size: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    version, raw_cases = _read_dataset_document(path)
    if any(
        isinstance(case, dict)
        and case.get("case_type") == "real_case"
        and "id" not in case
        for case in raw_cases
    ):
        raw_cases = [_normalize_real_case(case) for case in raw_cases]
    return version, validate_evaluation_cases(
        raw_cases,
        require_baseline_size=require_baseline_size,
    )


def _reject_secret_fields(case: dict[str, Any]) -> None:
    for key in case:
        lowered = str(key).casefold()
        if any(marker in lowered for marker in SECRET_FIELD_MARKERS):
            raise ValueError(f"real_case contains a prohibited field: {key}")


def _normalize_real_case(raw_case: dict[str, Any]) -> dict[str, Any]:
    _reject_secret_fields(raw_case)
    if raw_case.get("case_type", "real_case") != "real_case":
        raise ValueError("Real-case import requires case_type=real_case.")
    case_id = raw_case.get("case_id", raw_case.get("id"))
    source_reference = raw_case.get("source_reference")
    if source_reference is None:
        provenance_value = raw_case.get("provenance")
        if provenance_value not in {"contract_seed", "real_case"}:
            source_reference = provenance_value
    normalized = {
        "id": case_id,
        "category": raw_case.get("category"),
        "provenance": "real_case",
        "case_type": "real_case",
        "source_reference": source_reference,
        "input": raw_case.get("input"),
        "expected_behavior": raw_case.get("expected_behavior"),
        "expected_sources": raw_case.get("expected_sources", []),
        "forbidden_behavior": raw_case.get("forbidden_behavior", []),
        "required_tools": raw_case.get("required_tools", []),
        "forbidden_tools": raw_case.get("forbidden_tools", []),
        "success_criteria": raw_case.get("success_criteria", []),
        "deterministic_checks": raw_case.get(
            "deterministic_checks",
            {
                "citations_required": bool(raw_case.get("expected_sources")),
                "schema_fields": ["answer"],
                "approval_required": False,
                "abstention_required": False,
            },
        ),
    }
    return normalized


def import_real_cases(source_path: Path, output_path: Path) -> dict[str, Any]:
    dataset_version, raw_cases = _read_dataset_document(source_path)
    normalized = [_normalize_real_case(case) for case in raw_cases]
    validate_evaluation_cases(normalized)
    output = {
        "dataset_version": dataset_version,
        "cases": normalized,
    }
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "output": str(output_path),
        "dataset_version": output["dataset_version"],
        "real_case_count": len(normalized),
    }


def _tool_names(trace: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for call in trace.get("tool_calls", []):
        if isinstance(call, str):
            names.add(call)
        elif isinstance(call, dict) and isinstance(call.get("name"), str):
            names.add(call["name"])
    return names


def resolve_tool_expectation(semantic_name: str) -> dict[str, Any]:
    return TOOL_NAME_MAPPING.get(
        semantic_name,
        {
            "actual": semantic_name,
            "status": "unmapped",
            "note": "No semantic-to-runtime mapping has been declared.",
        },
    )


def case_execution_capability(case: dict[str, Any]) -> dict[str, Any]:
    unavailable_required = [
        tool
        for tool in case["required_tools"]
        if resolve_tool_expectation(tool)["status"] == "unavailable"
    ]
    unmapped_required = [
        tool
        for tool in case["required_tools"]
        if resolve_tool_expectation(tool)["status"] == "unmapped"
    ]
    return {
        "executable_by_current_agent_tools": not (
            unavailable_required or unmapped_required
        ),
        "unavailable_required_tools": unavailable_required,
        "unmapped_required_tools": unmapped_required,
    }


def _observed_sources(trace: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for source in trace.get("sources", []):
        if isinstance(source, str):
            sources.append(source)
        elif isinstance(source, dict):
            for key in ("domain", "url", "citation", "filename"):
                value = source.get(key)
                if isinstance(value, str):
                    sources.append(value)
                    break
    return sources


def deterministic_grade(
    case: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    checks = case["deterministic_checks"]
    tools = _tool_names(trace)
    sources = _observed_sources(trace)
    expected_sources = [str(value) for value in case["expected_sources"]]
    required_tools = set(case["required_tools"])
    forbidden_tools = set(case["forbidden_tools"])
    schema_fields = set(checks["schema_fields"])
    output = trace.get("output")
    output_fields = set(output) if isinstance(output, dict) else set()

    check_results = {
        "required_tools": required_tools <= tools,
        "forbidden_tools": not (forbidden_tools & tools),
        "citations": (
            bool(trace.get("citations") or sources)
            if checks["citations_required"]
            else True
        ),
        "expected_sources": (
            not expected_sources
            or any(
                expected.casefold() in observed.casefold()
                for expected in expected_sources
                for observed in sources
            )
        ),
        "schema": schema_fields <= output_fields,
        "approval_boundary": (
            (
                bool(trace.get("approval_requested"))
                and not bool(trace.get("executed_without_approval"))
            )
            if checks["approval_required"]
            else not bool(trace.get("executed_without_approval"))
        ),
        "abstention": (
            bool(trace.get("abstained"))
            if checks["abstention_required"]
            else True
        ),
    }
    passed = all(check_results.values())
    return {
        "case_id": case["id"],
        "category": case["category"],
        "provenance": case["provenance"],
        "deterministic_status": "PASS" if passed else "FAIL",
        "check_results": check_results,
        "metrics": {
            "task_completion": "PASS" if passed else "FAIL",
            "tool_selection": (
                "PASS"
                if check_results["required_tools"] and check_results["forbidden_tools"]
                else "FAIL"
            ),
            "retrieval_source_correctness": (
                "PASS" if check_results["expected_sources"] else "FAIL"
            ),
            "citation_correctness": (
                "PASS"
                if check_results["citations"] and check_results["expected_sources"]
                else "NOT_DETERMINED"
            ),
            "grounding": "NOT_RUN",
            "instruction_adherence": "NOT_RUN",
            "abstention": (
                "PASS" if check_results["abstention"] else "FAIL"
            ),
            "hitl_boundary": (
                "PASS" if check_results["approval_boundary"] else "FAIL"
            ),
        },
        "semantic_status": "NOT_RUN",
        "latency_ms": trace.get("latency_ms"),
        "tool_calls": len(trace.get("tool_calls", [])),
        "retries": trace.get("retries"),
        "tokens": trace.get("tokens"),
        "cost": trace.get("cost"),
    }


def build_scoreboard(
    cases: list[dict[str, Any]],
    traces: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    results = [
        deterministic_grade(case, traces[case["id"]])
        for case in cases
        if case["id"] in traces
    ]
    missing = [case["id"] for case in cases if case["id"] not in traces]
    passed = sum(result["deterministic_status"] == "PASS" for result in results)
    category_counts = Counter(case["category"] for case in cases)
    provenance_counts = Counter(case["provenance"] for case in cases)
    return {
        "status": "PASS" if results and not missing and passed == len(results) else "INCOMPLETE",
        "quality_eligible": provenance_counts.get("real_case", 0) > 0,
        "case_count": len(cases),
        "traced_case_count": len(results),
        "category_counts": dict(sorted(category_counts.items())),
        "provenance_counts": dict(sorted(provenance_counts.items())),
        "missing_case_ids": missing,
        "deterministic_pass_rate": round(passed / len(results), 4) if results else None,
        "semantic_grading": "NOT_RUN",
        "semantic_rubric": SEMANTIC_RUBRIC,
        "results": results,
    }


def build_quality_scoreboard(
    cases: list[dict[str, Any]],
    traces: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    real_cases = [case for case in cases if case["provenance"] == "real_case"]
    if not real_cases:
        return {
            "status": "REAL_CASE_DATA_REQUIRED",
            "quality_eligible": False,
            "real_case_count": 0,
            "semantic_grading": "NOT_RUN",
        }
    report = build_scoreboard(real_cases, traces)
    report["quality_eligible"] = True
    return report


def compare_scoreboards(
    baseline_a: dict[str, Any],
    baseline_b: dict[str, Any],
) -> dict[str, Any]:
    if not baseline_a.get("quality_eligible") or not baseline_b.get("quality_eligible"):
        return {
            "status": "REAL_CASE_DATA_REQUIRED",
            "per_case": [],
            "per_category": {},
            "semantic_grading": "NOT_RUN",
        }
    results_a = {result["case_id"]: result for result in baseline_a.get("results", [])}
    results_b = {result["case_id"]: result for result in baseline_b.get("results", [])}
    case_ids = sorted(set(results_a) | set(results_b))
    per_case: list[dict[str, Any]] = []
    for case_id in case_ids:
        before = results_a.get(case_id)
        after = results_b.get(case_id)
        before_score = (
            1 if before and before["deterministic_status"] == "PASS" else 0
        )
        after_score = 1 if after and after["deterministic_status"] == "PASS" else 0
        per_case.append(
            {
                "case_id": case_id,
                "category": (after or before).get("category"),
                "baseline_a": before_score,
                "baseline_b": after_score,
                "delta": after_score - before_score,
            }
        )
    categories: dict[str, dict[str, Any]] = {}
    for item in per_case:
        category = item["category"] or "uncategorized"
        bucket = categories.setdefault(category, {"baseline_a": [], "baseline_b": []})
        bucket["baseline_a"].append(item["baseline_a"])
        bucket["baseline_b"].append(item["baseline_b"])
    category_comparison = {
        category: {
            "baseline_a_pass_rate": round(sum(values["baseline_a"]) / len(values["baseline_a"]), 4),
            "baseline_b_pass_rate": round(sum(values["baseline_b"]) / len(values["baseline_b"]), 4),
            "delta": round(
                sum(values["baseline_b"]) / len(values["baseline_b"])
                - sum(values["baseline_a"]) / len(values["baseline_a"]),
                4,
            ),
        }
        for category, values in sorted(categories.items())
    }
    return {
        "status": "COMPARABLE" if per_case else "INCOMPLETE",
        "per_case": per_case,
        "per_category": category_comparison,
        "semantic_grading": "NOT_RUN",
    }


def freeze_baseline_manifest(
    path: Path = DATASET_PATH,
) -> dict[str, Any]:
    dataset_bytes = path.read_bytes()
    dataset_version, cases = load_case_document(path, require_baseline_size=True)
    provenance_counts = Counter(case["provenance"] for case in cases)
    return {
        "baseline_version": "evaluation-baseline-v1",
        "run_id": str(uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset_version,
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "dataset_case_count": len(cases),
        "real_case_count": provenance_counts.get("real_case", 0),
        "contract_seed_count": provenance_counts.get("contract_seed", 0),
        "category_counts": dict(
            sorted(Counter(case["category"] for case in cases).items())
        ),
        "tool_name_mapping": TOOL_NAME_MAPPING,
        "dataset_provenance": (
            "real_case"
            if provenance_counts.get("real_case", 0)
            else "contract_seed_until_real_cases_are_added"
        ),
        "providers": {
            "gemini": {"model": provider_model_name("gemini")},
            "openai": {"model": provider_model_name("openai")},
        },
        "limits": {
            "max_tool_calls": MAX_TOOL_CALLS,
            "max_model_requests": MAX_MODEL_REQUESTS,
        },
        "semantic_grader": "not_configured",
        "deterministic_grading": "READY_FOR_TRACES",
        "live_provider_run": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ahmed Agent evaluation baseline")
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--validate-real", type=Path)
    parser.add_argument("--import-real", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.validate_real:
        version, cases = load_case_document(args.validate_real)
        print(json.dumps({
            "status": "VALID",
            "dataset_version": version,
            "real_case_count": sum(case["provenance"] == "real_case" for case in cases),
        }, ensure_ascii=False, indent=2))
        return
    if args.import_real:
        if args.output is None:
            parser.error("--import-real requires --output")
        print(json.dumps(
            import_real_cases(args.import_real, args.output),
            ensure_ascii=False,
            indent=2,
        ))
        return
    cases = load_evaluation_cases()
    value = freeze_baseline_manifest() if args.manifest else {
        "status": "READY_FOR_TRACES",
        "case_count": len(cases),
        "real_case_count": sum(case["provenance"] == "real_case" for case in cases),
        "contract_seed_count": sum(
            case["provenance"] == "contract_seed" for case in cases
        ),
        "semantic_grading": "NOT_RUN",
    }
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()