from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from bizrag.common.time_utils import utc_now


DEFAULT_FILE_SERVICE_DB = "/app/runtime/file_service/state/metadata.db"
DEFAULT_FILE_SERVICE_STORAGE_ROOT = "/app/runtime/file_service/storage"
DEFAULT_WORKSPACE_ROOT = "/app/runtime/kbs"


def _snippet(value: Any, *, limit: int = 180) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class FileServiceInventoryService:
    def __init__(
        self,
        *,
        database_path: str | Path | None = None,
        storage_root: str | Path | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        self._database_path = Path(
            database_path or os.getenv("BIZRAG_FILE_SERVICE_DB", DEFAULT_FILE_SERVICE_DB)
        )
        self._storage_root = Path(
            storage_root
            or os.getenv(
                "BIZRAG_FILE_SERVICE_STORAGE_ROOT", DEFAULT_FILE_SERVICE_STORAGE_ROOT
            )
        )
        self._workspace_root = Path(
            workspace_root or os.getenv("BIZRAG_WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT)
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._database_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _list_files(
        self,
        *,
        kb_id: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        if not self._database_path.exists():
            return []
        query = """
            SELECT
                f.file_id,
                f.tenant_id,
                f.kb_id,
                f.source_uri,
                f.current_version,
                f.file_name,
                f.content_type,
                f.status,
                f.created_at,
                f.updated_at,
                f.deleted_at,
                (
                    SELECT storage_key
                    FROM file_versions fv
                    WHERE fv.file_id = f.file_id
                    ORDER BY fv.id DESC
                    LIMIT 1
                ) AS storage_key,
                (
                    SELECT size_bytes
                    FROM file_versions fv
                    WHERE fv.file_id = f.file_id
                    ORDER BY fv.id DESC
                    LIMIT 1
                ) AS size_bytes,
                (
                    SELECT content_hash
                    FROM file_versions fv
                    WHERE fv.file_id = f.file_id
                    ORDER BY fv.id DESC
                    LIMIT 1
                ) AS content_hash,
                (
                    SELECT created_at
                    FROM file_versions fv
                    WHERE fv.file_id = f.file_id
                    ORDER BY fv.id DESC
                    LIMIT 1
                ) AS version_created_at
            FROM files f
            WHERE (? IS NULL OR f.kb_id = ?)
            ORDER BY
                CASE WHEN f.status = 'active' THEN 0 ELSE 1 END ASC,
                f.updated_at DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(query, (kb_id, kb_id, max(1, limit))).fetchall()
        return [dict(row) for row in rows]

    def _chunk_inventory_for_files(
        self,
        *,
        files: List[Dict[str, Any]],
        chunk_preview: int,
    ) -> Dict[str, Dict[str, Any]]:
        grouped: Dict[str, set[str]] = {}
        for item in files:
            kb_id = str(item.get("kb_id") or "")
            source_uri = str(item.get("source_uri") or "")
            if not kb_id or not source_uri:
                continue
            grouped.setdefault(kb_id, set()).add(source_uri)

        chunks_by_source: Dict[str, Dict[str, Any]] = {}
        for kb_id, source_uris in grouped.items():
            chunks_dir = self._workspace_root / kb_id / "chunks" / "documents"
            if not chunks_dir.exists():
                continue
            for path in sorted(chunks_dir.glob("*.jsonl")):
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        for line in handle:
                            try:
                                row = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            source_uri = str(row.get("source_uri") or "")
                            if source_uri not in source_uris:
                                continue
                            item = chunks_by_source.setdefault(
                                source_uri,
                                {
                                    "chunk_count": 0,
                                    "chunks": [],
                                    "chunk_file": str(path),
                                },
                            )
                            item["chunk_count"] += 1
                            if len(item["chunks"]) >= chunk_preview:
                                continue
                            chunk_id = str(row.get("id") or "")
                            item["chunks"].append(
                                {
                                    "chunk_id": chunk_id,
                                    "vector_id": chunk_id,
                                    "doc_id": row.get("doc_id"),
                                    "title": row.get("title"),
                                    "sheet_name": row.get("sheet_name"),
                                    "row_index": row.get("row_index"),
                                    "snippet": _snippet(row.get("contents")),
                                }
                            )
                except OSError:
                    continue
        return chunks_by_source

    def build_inventory(
        self,
        *,
        kb_id: Optional[str] = None,
        limit: int = 100,
        chunk_preview: int = 12,
    ) -> Dict[str, Any]:
        files = self._list_files(kb_id=kb_id, limit=limit)
        chunks_by_source = self._chunk_inventory_for_files(
            files=files,
            chunk_preview=chunk_preview,
        )
        items: List[Dict[str, Any]] = []
        for item in files:
            storage_key = str(item.get("storage_key") or "")
            chunk_data = chunks_by_source.get(str(item.get("source_uri") or ""), {})
            items.append(
                {
                    **item,
                    "storage_path": str(self._storage_root / storage_key) if storage_key else None,
                    "chunk_count": int(chunk_data.get("chunk_count") or 0),
                    "chunk_file": chunk_data.get("chunk_file"),
                    "chunks": chunk_data.get("chunks") or [],
                }
            )
        return {
            "generated_at": utc_now(),
            "database_path": str(self._database_path),
            "storage_root": str(self._storage_root),
            "workspace_root": str(self._workspace_root),
            "items": items,
        }
