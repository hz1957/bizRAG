from __future__ import annotations

import uuid
from typing import Any, Dict

from .db import FileRecord, VersionRecord


def _short(v: str | None, fallback: str) -> str:
    return v or fallback


def build_download_url(base_url: str, file_id: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/api/v1/files/{file_id}/content"


def build_source_uri(prefix: str, tenant_id: str, file_id: str) -> str:
    return f"{prefix}://{tenant_id}/{file_id}"


def build_event_id() -> str:
    return str(uuid.uuid4())


def build_file_event(
    *,
    event_type: str,
    file_record: FileRecord,
    version_record: VersionRecord,
    base_url: str,
    include_payload: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_id": build_event_id(),
        "event_type": event_type,
        "kb_id": file_record.kb_id,
        "doc_id": file_record.file_id,
        "source_uri": file_record.source_uri,
        "file_name": _short(file_record.file_name, version_record.file_name or ""),
        "content_type": _short(
            file_record.content_type,
            version_record.content_type or "application/octet-stream",
        ),
        "version": version_record.version,
        "content_hash": version_record.content_hash,
    }
    if include_payload:
        payload["download_url"] = build_download_url(base_url, file_record.file_id)
    payload["new_source_uri"] = payload["source_uri"]
    return payload


def build_deleted_event(
    *,
    file_record: FileRecord,
    version_record: VersionRecord,
) -> Dict[str, Any]:
    payload = {
        "event_id": build_event_id(),
        "event_type": "document.deleted",
        "kb_id": file_record.kb_id,
        "doc_id": file_record.file_id,
        "source_uri": file_record.source_uri,
        "old_source_uri": file_record.source_uri,
        "new_source_uri": file_record.source_uri,
        "file_name": file_record.file_name,
        "content_type": file_record.content_type,
        "version": version_record.version,
        "content_hash": version_record.content_hash,
    }
    return payload
