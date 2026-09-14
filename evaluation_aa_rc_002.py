from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from evaluation_baseline import execute_real_case
from evaluation_source_bindings import (
    load_aa_rc_002_source_pack,
    resolve_aa_rc_002_sources,
)
from my_files import search_my_files
from persistence import (
    close_pool,
    delete_documents_for_source_ids,
    delete_original_source,
)
from source_of_truth import inspect_source_of_truth


NORMALIZED_DATASET = Path("real-cases-validated.json")


def _multipart_body(
    files: list[tuple[str, str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----ahmed-eval-{uuid4().hex}"
    chunks: list[bytes] = []
    for field_name, filename, mime_type, data in files:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {mime_type}\r\n\r\n".encode(),
                data,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _post_upload(
    *,
    base_url: str,
    owner_token: str,
    files: list[tuple[str, str, str, bytes]],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    body, content_type = _multipart_body(files)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/files/upload",
        data=body,
        headers={
            "Authorization": f"Bearer {owner_token}",
            "Content-Type": content_type,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": "HTTP_ERROR"}
        return error.code, parsed


def _load_case() -> dict[str, Any]:
    document = json.loads(NORMALIZED_DATASET.read_text(encoding="utf-8"))
    return next(case for case in document["cases"] if case["id"] == "AA-RC-002")


def _inspect_text(result: dict[str, Any]) -> str:
    facts = result.get("extracted_facts") or {}
    sections = facts.get("extracted_sections") or []
    return "\n".join(
        str(section.get("content", ""))
        for section in sections
        if isinstance(section, dict)
    )


def _compare_inspected_sources(
    inspected: dict[str, dict[str, Any]],
    source_ids_by_hash: dict[str, str],
) -> dict[str, Any]:
    master_hash = next(
        file_hash
        for file_hash in source_ids_by_hash
        if "Recorded incident count: 2" in _inspect_text(inspected[source_ids_by_hash[file_hash]])
    )
    incident_ids = sorted(
        set(
            match.group(1)
            for result in inspected.values()
            for match in re.finditer(r"Incident ID:\s*(INC-\d+)", _inspect_text(result))
        )
    )
    master_text = _inspect_text(inspected[source_ids_by_hash[master_hash]])
    master_count = re.search(r"Recorded incident count:\s*(\d+)", master_text)
    if master_count is None:
        raise AssertionError("Master original did not expose its incident count.")
    if not incident_ids:
        return {
            "comparison_status": "MISSING_EVIDENCE",
            "master_source_id": source_ids_by_hash[master_hash],
            "master_recorded_incident_count": int(master_count.group(1)),
            "confirmed_incident_ids": [],
            "original_incident_count": None,
            "discrepancy_detected": False,
        }
    return {
        "comparison_status": "SOURCE_DISCREPANCY",
        "master_source_id": source_ids_by_hash[master_hash],
        "master_recorded_incident_count": int(master_count.group(1)),
        "confirmed_incident_ids": incident_ids,
        "original_incident_count": len(incident_ids),
        "discrepancy_detected": int(master_count.group(1)) != len(incident_ids),
    }


async def execute_aa_rc_002(
    *,
    base_url: str,
    owner_token: str,
    provider: str = "gemini",
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    source_pack = load_aa_rc_002_source_pack()
    source_members = resolve_aa_rc_002_sources()
    source_bytes_by_hash = {
        member["sha256"]: member["bytes"] for member in source_members
    }
    upload_files = [
        (
            "file",
            Path(member["member_name"]).name,
            "text/markdown",
            member["bytes"],
        )
        for member in source_members
    ]
    status, upload_payload = await asyncio.to_thread(
        _post_upload,
        base_url=base_url,
        owner_token=owner_token,
        files=upload_files,
        timeout_seconds=timeout_seconds,
    )
    if status == 401:
        raise RuntimeError("AUTHENTICATED_EVALUATION_PRINCIPAL_BLOCKED")
    if not 200 <= status < 300:
        raise RuntimeError(f"Fixture upload failed with HTTP {status}.")
    uploaded_files = upload_payload.get("files")
    if not isinstance(uploaded_files, list) or len(uploaded_files) != len(source_members):
        raise RuntimeError("Fixture upload did not return every source.")

    source_ids: list[str] = []
    source_ids_by_hash: dict[str, str] = {}
    for member, uploaded in zip(source_members, uploaded_files, strict=True):
        source_id = uploaded.get("source_id")
        if not isinstance(source_id, str):
            raise RuntimeError("Fixture upload did not return a source_id.")
        if uploaded.get("file_hash") != member["sha256"]:
            raise RuntimeError("Fixture upload returned an unexpected source hash.")
        source_ids.append(source_id)
        source_ids_by_hash[member["sha256"]] = source_id

    try:
        discovered_ids: set[str] = set()
        for query in ("Ahmed Agent", "INC-001", "INC-002", "INC-003"):
            search_result = await search_my_files(query, top_k=10)
            discovered_ids.update(
                str(row["source_id"])
                for row in search_result.get("results", [])
                if row.get("source_id")
            )
        if not set(source_ids).issubset(discovered_ids):
            raise AssertionError("Search did not discover every evaluation source.")

        inspected: dict[str, dict[str, Any]] = {}
        for source_id in source_ids:
            result = await inspect_source_of_truth(
                source_id,
                owner_principal_id="owner",
            )
            if result.get("evidence_status") != "VERIFIED":
                raise AssertionError("An evaluation original was not verified.")
            facts = result.get("extracted_facts") or {}
            if facts.get("source_sha256") not in source_bytes_by_hash:
                raise AssertionError("Inspected source hash is not from the pack.")
            if "storage_object_key" in json.dumps(result):
                raise AssertionError("Storage object key leaked from inspection.")
            if '"data":' in json.dumps(result):
                raise AssertionError("Raw source bytes leaked from inspection.")
            inspected[source_id] = result

        denied = await inspect_source_of_truth(
            source_ids[0],
            owner_principal_id="different-owner",
        )
        if denied.get("evidence_status") != "DENIED":
            raise AssertionError("Cross-owner inspection was not denied.")
        for invalid in ("not-a-uuid", "/tmp/source", "glob/*", "original-source/key"):
            result = await inspect_source_of_truth(
                invalid,
                owner_principal_id="owner",
            )
            if result.get("evidence_status") != "NOT_FOUND":
                raise AssertionError("Invalid source identity was not rejected.")
        unknown = await inspect_source_of_truth(
            str(uuid4()),
            owner_principal_id="owner",
        )
        if unknown.get("evidence_status") != "NOT_FOUND":
            raise AssertionError("Unknown source ID was not hidden.")

        comparison = _compare_inspected_sources(inspected, source_ids_by_hash)
        if comparison["master_recorded_incident_count"] != 2:
            raise AssertionError("Master fixture did not record two incidents.")
        if comparison["confirmed_incident_ids"] != ["INC-001", "INC-002", "INC-003"]:
            raise AssertionError("Incident originals did not contain the expected IDs.")
        if not comparison["discrepancy_detected"]:
            raise AssertionError("The expected 2-vs-3 discrepancy was not detected.")

        case = _load_case()
        started = time.perf_counter()
        trace = await execute_real_case(
            case,
            base_url=base_url,
            owner_token=owner_token,
            provider=provider,
            timeout_seconds=timeout_seconds,
        )
        trace["fixture_preflight_latency_ms"] = int(
            (time.perf_counter() - started) * 1000
        )
        tool_names = [call.get("name") for call in trace.get("tool_calls", [])]
        if trace.get("execution_status") != "EXECUTED":
            raise RuntimeError("AA-RC-002 targeted chat did not execute.")
        if "search_my_files" not in tool_names:
            raise AssertionError("Targeted chat did not search MY_FILES.")
        if "inspect_source_of_truth" not in tool_names:
            raise AssertionError("Targeted chat did not inspect an original source.")
        return {
            "case_id": "AA-RC-002",
            "execution_status": "EXECUTED",
            "source_pack_sha256": source_pack["source_pack_sha256"],
            "source_ids": source_ids,
            "discovered_source_count": len(discovered_ids & set(source_ids)),
            "authorization_verified": True,
            "integrity_verified": True,
            "comparison": comparison,
            "trace": trace,
            "fake_citations": 0,
            "provider_failures": 0,
            "hitl_blocked": 0,
        }
    finally:
        await delete_documents_for_source_ids(source_ids)
        for source_id in source_ids:
            await delete_original_source(source_id=source_id)
        cleanup_statuses = [
            (
                source_id,
                (
                    await inspect_source_of_truth(
                        source_id,
                        owner_principal_id="owner",
                    )
                ).get("evidence_status"),
            )
            for source_id in source_ids
        ]
        if any(status != "NOT_FOUND" for _, status in cleanup_statuses):
            raise RuntimeError("Evaluation cleanup did not remove every source.")


async def _main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--provider", default="gemini")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args()
    owner_token = os.environ.get("AHMED_OWNER_TOKEN")
    if not owner_token:
        raise SystemExit("AUTHENTICATED_EVALUATION_PRINCIPAL_BLOCKED")
    try:
        result = await execute_aa_rc_002(
            base_url=args.base_url,
            owner_token=owner_token,
            provider=args.provider,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await close_pool()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()