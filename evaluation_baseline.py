from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from agent_core import MAX_MODEL_REQUESTS, MAX_TOOL_CALLS, provider_model_name


DATASET_PATH = (
    Path(__file__).parent
    / "tests"
    / "fixtures"
    / "evaluation_baseline"
    / "cases.json"
)
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
REQUIRED_CHECK_KEYS = {
    "citations_required",
    "schema_fields",
    "approval_required",
    "abstention_required",
}


def load_evaluation_cases(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not 20 <= len(raw) <= 30:
        raise ValueError("Evaluation baseline must contain 20-30 cases.")
    seen_ids: set[str] = set()
    for case in raw:
        if not isinstance(case, dict) or not REQUIRED_CASE_KEYS <= case.keys():
            raise ValueError("Evaluation case is missing required fields.")
        if case["id"] in seen_ids:
            raise ValueError(f"Duplicate evaluation case id: {case['id']}")
        seen_ids.add(case["id"])
        checks = case["deterministic_checks"]
        if not isinstance(checks, dict) or not REQUIRED_CHECK_KEYS <= checks.keys():
            raise ValueError(f"Invalid deterministic checks: {case['id']}")
        if case["provenance"] not in {"contract_seed", "real_case"}:
            raise ValueError(f"Invalid case provenance: {case['id']}")
    return raw


def _tool_names(trace: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for call in trace.get("tool_calls", []):
        if isinstance(call, str):
            names.add(call)
        elif isinstance(call, dict) and isinstance(call.get("name"), str):
            names.add(call["name"])
    return names


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
        "provenance": case["provenance"],
        "deterministic_status": "PASS" if passed else "FAIL",
        "check_results": check_results,
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
    return {
        "status": "PASS" if results and not missing and passed == len(results) else "INCOMPLETE",
        "case_count": len(cases),
        "traced_case_count": len(results),
        "missing_case_ids": missing,
        "deterministic_pass_rate": round(passed / len(results), 4) if results else None,
        "semantic_grading": "NOT_RUN",
        "results": results,
    }


def freeze_baseline_manifest(
    path: Path = DATASET_PATH,
) -> dict[str, Any]:
    dataset_bytes = path.read_bytes()
    return {
        "baseline_version": "evaluation-baseline-v1",
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "dataset_case_count": len(load_evaluation_cases(path)),
        "dataset_provenance": "contract_seed_until_real_cases_are_added",
        "providers": {
            "gemini": {"model": provider_model_name("gemini")},
            "openai": {"model": provider_model_name("openai")},
        },
        "limits": {
            "max_tool_calls": MAX_TOOL_CALLS,
            "max_model_requests": MAX_MODEL_REQUESTS,
        },
        "semantic_grader": "not_configured",
        "live_provider_run": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ahmed Agent evaluation baseline")
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()
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