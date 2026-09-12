from __future__ import annotations

import hashlib
import io
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from pypdf import PdfReader

from config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DEFAULT_TOP_K,
    MAX_QUERY_LENGTH,
    MAX_TOP_K,
)
from persistence import (
    PersistenceError,
    find_document_by_hash,
    search_document_chunks,
    store_document,
)


logger = logging.getLogger("ahmed_agent.my_files")
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


class FileProcessingError(RuntimeError):
    def __init__(self, message: str, *, status: str = "failed") -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int | None
    content: str


@dataclass(frozen=True)
class DocumentChunk:
    chunk_index: int
    page_number: int | None
    content: str
    metadata: dict[str, Any]


def extension_for(filename: str) -> str:
    return Path(filename).suffix.lower()


def _normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\x00", "").splitlines()).strip()


def _extract_text_or_markdown(data: bytes) -> list[ExtractedPage]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise FileProcessingError("The text file must use UTF-8 encoding.", status="invalid_encoding") from error
    return [ExtractedPage(page_number=None, content=_normalize_text(text))]


def _extract_pdf(data: bytes) -> list[ExtractedPage]:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as error:
        raise FileProcessingError("The PDF could not be read.", status="invalid_pdf") from error
    if reader.is_encrypted:
        raise FileProcessingError("Encrypted PDFs are not supported.", status="unsupported_encryption")

    pages: list[ExtractedPage] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = _normalize_text(page.extract_text() or "")
        except Exception as error:
            raise FileProcessingError("The PDF text layer could not be read.", status="invalid_pdf") from error
        if text:
            pages.append(ExtractedPage(page_number=page_number, content=text))
    if not pages:
        raise FileProcessingError(
            "This PDF has no text layer; OCR is required.",
            status="unsupported_ocr_required",
        )
    return pages


def _extract_docx(data: bytes) -> list[ExtractedPage]:
    try:
        document = Document(io.BytesIO(data))
    except Exception as error:
        raise FileProcessingError("The DOCX file could not be read.", status="invalid_docx") from error
    text = _normalize_text("\n".join(paragraph.text for paragraph in document.paragraphs))
    return [ExtractedPage(page_number=None, content=text)]


def extract_document(filename: str, mime_type: str | None, data: bytes) -> list[ExtractedPage]:
    del mime_type
    extension = extension_for(filename)
    if extension in {".txt", ".md"}:
        return _extract_text_or_markdown(data)
    if extension == ".pdf":
        return _extract_pdf(data)
    if extension == ".docx":
        return _extract_docx(data)
    raise FileProcessingError("This file type is not supported.", status="unsupported_extension")


def _chunk_content(content: str) -> list[str]:
    if not content:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = min(len(content), start + CHUNK_SIZE)
        if end < len(content):
            boundary = content.rfind(" ", start, end)
            if boundary > start + (CHUNK_SIZE // 2):
                end = boundary
        chunk = content[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(content):
            break
        next_start = max(end - CHUNK_OVERLAP, start + 1)
        start = next_start
    return chunks


def build_chunks(
    *,
    document_id: str,
    filename: str,
    mime_type: str | None,
    pages: list[ExtractedPage],
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for page in pages:
        for content in _chunk_content(page.content):
            chunks.append(
                DocumentChunk(
                    chunk_index=len(chunks),
                    page_number=page.page_number,
                    content=content,
                    metadata={
                        "document_id": document_id,
                        "filename": filename,
                        "mime_type": mime_type,
                        "page_number": page.page_number,
                    },
                )
            )
    return chunks


async def ingest_document(
    *,
    document_id: str,
    filename: str,
    mime_type: str | None,
    data: bytes,
) -> dict[str, Any]:
    file_hash = hashlib.sha256(data).hexdigest()
    duplicate = await find_document_by_hash(file_hash)
    if duplicate is not None:
        return {
            "duplicate": True,
            "document_id": str(duplicate["document_id"]),
            "filename": duplicate["filename"],
            "status": duplicate["status"],
            "chunk_count": int(duplicate["chunk_count"]),
            "file_hash": file_hash,
        }

    try:
        pages = extract_document(filename, mime_type, data)
        chunks = build_chunks(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type,
            pages=pages,
        )
        if not chunks:
            raise FileProcessingError("The file contains no searchable text.", status="empty")
    except FileProcessingError as error:
        await store_document(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type,
            file_hash=file_hash,
            status=error.status,
            chunks=[],
        )
        logger.info(
            json.dumps(
                {
                    "document_id": document_id,
                    "filename": filename,
                    "mime_type": mime_type,
                    "extraction_status": error.status,
                    "chunk_count": 0,
                },
                separators=(",", ":"),
            )
        )
        return {
            "duplicate": False,
            "document_id": document_id,
            "filename": filename,
            "status": error.status,
            "chunk_count": 0,
            "file_hash": file_hash,
        }

    await store_document(
        document_id=document_id,
        filename=filename,
        mime_type=mime_type,
        file_hash=file_hash,
        status="ready",
        chunks=chunks,
    )
    logger.info(
        json.dumps(
            {
                "document_id": document_id,
                "filename": filename,
                "mime_type": mime_type,
                "extraction_status": "ready",
                "chunk_count": len(chunks),
            },
            separators=(",", ":"),
        )
    )
    return {
        "duplicate": False,
        "document_id": document_id,
        "filename": filename,
        "status": "ready",
        "chunk_count": len(chunks),
        "file_hash": file_hash,
    }


async def search_my_files(query: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if len(normalized_query) > MAX_QUERY_LENGTH:
        raise ValueError("query is too long")
    if not 1 <= top_k <= min(MAX_TOP_K, 20):
        raise ValueError("top_k is out of range")

    started_at = time.perf_counter()
    rows = await search_document_chunks(normalized_query, top_k)
    results: list[dict[str, Any]] = []
    for row in rows:
        page_number = row["page_number"]
        citation = f"[source: {row['filename']}"
        if page_number is not None:
            citation += f", page {page_number}"
        citation += f", chunk {row['chunk_index']}]"
        results.append(
            {
                "content": row["content"],
                "document_id": str(row["document_id"]),
                "filename": row["filename"],
                "chunk_index": row["chunk_index"],
                "page_number": page_number,
                "mime_type": row["mime_type"],
                "citation": citation,
            }
        )
    logger.info(
        json.dumps(
            {
                "retrieval_latency_ms": int((time.perf_counter() - started_at) * 1000),
                "result_count": len(results),
            },
            separators=(",", ":"),
        )
    )
    return {
        "ok": True,
        "scope": "MY_FILES",
        "privacy_mode": "PRIVATE_STANDARD",
        "results": results,
        "message": (
            "No matching information was found in the uploaded files."
            if not results
            else "Use the returned file excerpts and citations only."
        ),
    }