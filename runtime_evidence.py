from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_EVIDENCE_FILES = ("server.py", "pyproject.toml", ".replit")
MAX_EVIDENCE_FILE_BYTES = 256_000
MAX_EVIDENCE_SNIPPET_LENGTH = 240


class RuntimeEvidenceError(RuntimeError):
    """Raised when the fixed runtime evidence boundary cannot be enforced."""


def _safe_evidence_path(project_root: Path, relative_name: str) -> Path:
    if relative_name not in RUNTIME_EVIDENCE_FILES:
        raise RuntimeEvidenceError("runtime evidence file is not allowlisted")

    root = project_root.resolve(strict=True)
    candidate = root / relative_name
    if candidate.is_symlink():
        raise RuntimeEvidenceError("runtime evidence symlinks are not allowed")
    canonical = candidate.resolve(strict=True)
    if canonical.parent != root or canonical.name != relative_name:
        raise RuntimeEvidenceError("runtime evidence path escaped project root")
    if not canonical.is_file():
        raise RuntimeEvidenceError("runtime evidence path is not a regular file")
    if canonical.stat().st_size > MAX_EVIDENCE_FILE_BYTES:
        raise RuntimeEvidenceError("runtime evidence file is too large")
    return canonical


def _read_allowlisted_files(project_root: Path) -> dict[str, list[str]]:
    contents: dict[str, list[str]] = {}
    for relative_name in RUNTIME_EVIDENCE_FILES:
        try:
            path = _safe_evidence_path(project_root, relative_name)
        except FileNotFoundError:
            contents[relative_name] = []
            continue
        contents[relative_name] = path.read_text(encoding="utf-8").splitlines()
    return contents


def _safe_snippet(line: str) -> str:
    snippet = re.sub(
        r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,]+",
        r"\1=[REDACTED]",
        line,
    ).strip()
    snippet = re.sub(
        r"(?i)(?:os\.)?environ(?:\.get)?\s*\([^)]*\)",
        "environment_access([REDACTED])",
        snippet,
    )
    if len(snippet) > MAX_EVIDENCE_SNIPPET_LENGTH:
        return f"{snippet[:MAX_EVIDENCE_SNIPPET_LENGTH - 1]}…"
    return snippet


def _evidence(
    filename: str,
    lines: list[str],
    predicate: Any,
) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for index, line in enumerate(lines):
        if predicate(line):
            line_number = index + 1
            references.append(
                {
                    "file": filename,
                    "line_start": line_number,
                    "line_end": line_number,
                    "citation": f"[source: {filename}, line {line_number}]",
                    "evidence": _safe_snippet(line),
                }
            )
    return references[:3]


def _claim(
    value: object,
    references: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "value": value,
        "status": "verified" if references else "unverified",
        "evidence": references,
    }


def _parse_toml(lines: list[str], filename: str) -> dict[str, Any]:
    try:
        return tomllib.loads("\n".join(lines))
    except tomllib.TOMLDecodeError as error:
        raise RuntimeEvidenceError(f"{filename} is not valid TOML") from error


def inspect_runtime_evidence(
    *,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Inspect only fixed, project-local runtime evidence files.

    The optional project_root is an internal test seam. The AgentCore tool does
    not expose it to the model or to callers.
    """

    root = project_root or PROJECT_ROOT
    files = _read_allowlisted_files(root)
    server_lines = files["server.py"]
    pyproject_lines = files["pyproject.toml"]
    replit_lines = files[".replit"]

    pyproject = _parse_toml(pyproject_lines, "pyproject.toml")
    replit = _parse_toml(replit_lines, ".replit")

    project_config = pyproject.get("project")
    requires_python = (
        project_config.get("requires-python")
        if isinstance(project_config, dict)
        else None
    )
    language_references = _evidence(
        "pyproject.toml",
        pyproject_lines,
        lambda line: "requires-python" in line,
    )
    language_value = "Python" if requires_python else None
    language_version_value = (
        f"{language_value} ({requires_python})"
        if language_value and isinstance(requires_python, str)
        else None
    )

    run_command = replit.get("run")
    if isinstance(run_command, list) and all(
        isinstance(part, str) for part in run_command
    ):
        run_command_value = " ".join(run_command)
    elif isinstance(run_command, str):
        run_command_value = run_command
    else:
        run_command_value = None

    entrypoint_value = None
    if isinstance(run_command_value, str):
        command_parts = run_command_value.split()
        if command_parts:
            entrypoint_candidate = command_parts[-1]
            if entrypoint_candidate.endswith(".py"):
                entrypoint_value = entrypoint_candidate
    entrypoint_references = _evidence(
        ".replit",
        replit_lines,
        lambda line: re.match(r"^\s*run\s*=", line) is not None,
    )
    if entrypoint_value != "server.py":
        entrypoint_references = []
    server_path_exists = (root / "server.py").is_file()
    if not server_path_exists:
        entrypoint_references = []

    framework_references = _evidence(
        "server.py",
        server_lines,
        lambda line: (
            "from starlette" in line
            or "import starlette" in line
            or "uvicorn.run" in line
        ),
    )
    framework_value = "Starlette + Uvicorn" if framework_references else None

    mcp_references = _evidence(
        "server.py",
        server_lines,
        lambda line: "MCPServer" in line or "mcp.server" in line,
    )
    mcp_value = bool(mcp_references) if mcp_references else None

    command_references = entrypoint_references
    port_references = _evidence(
        ".replit",
        replit_lines,
        lambda line: re.search(r"\b(localPort|externalPort)\s*=", line)
        is not None,
    )
    port_references.extend(
        _evidence(
            "server.py",
            server_lines,
            lambda line: "os.environ.get" in line and "PORT" in line,
        )
    )
    configured_port: object = None
    ports = replit.get("ports")
    if isinstance(ports, list) and ports:
        first_port = ports[0]
        if isinstance(first_port, dict):
            configured_port = first_port.get("localPort")
    if configured_port is None:
        configured_port = None

    runtime_evidence = {
        "language": _claim(language_value, language_references),
        "language_version": _claim(
            language_version_value,
            language_references,
        ),
        "active_entrypoint": _claim(entrypoint_value, entrypoint_references),
        "http_framework": _claim(framework_value, framework_references),
        "mcp_presence": _claim(mcp_value, mcp_references),
        "server_runtime_command": _claim(
            run_command_value,
            command_references,
        ),
        "configured_port": _claim(configured_port, port_references),
    }
    statuses = [
        claim["status"]
        for claim in runtime_evidence.values()
        if isinstance(claim, dict)
    ]
    if statuses and all(status == "verified" for status in statuses):
        overall_status = "verified"
    elif any(status == "verified" for status in statuses):
        overall_status = "partial"
    else:
        overall_status = "unverified"

    evidence_references: list[dict[str, object]] = []
    for claim in runtime_evidence.values():
        if isinstance(claim, dict):
            evidence = claim.get("evidence")
            if isinstance(evidence, list):
                evidence_references.extend(
                    reference
                    for reference in evidence
                    if isinstance(reference, dict)
                )

    return {
        "status": overall_status,
        "runtime_evidence": runtime_evidence,
        "evidence_references": evidence_references,
        "evidence_files": list(RUNTIME_EVIDENCE_FILES),
    }