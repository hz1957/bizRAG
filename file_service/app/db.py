from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import Settings


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _safe_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _safe_payload(value: str) -> Dict[str, Any]:
    try:
        return json.loads(value)
    except Exception:
        return {}


@dataclass(frozen=True)
class FileRecord:
    file_id: str
    tenant_id: str
    kb_id: str
    source_uri: str
    current_version: str
    file_name: Optional[str]
    content_type: Optional[str]
    status: str
    created_at: str
    updated_at: str
    deleted_at: Optional[str]


@dataclass(frozen=True)
class VersionRecord:
    id: int
    file_id: str
    version: str
    storage_key: str
    size_bytes: int
    content_hash: str
    file_name: Optional[str]
    content_type: Optional[str]
    created_at: str


@dataclass(frozen=True)
class OutboxRecord:
    event_id: str
    file_id: str
    kb_id: str
    event_type: str
    status: str
    payload: Dict[str, Any]
    retry_count: int
    last_error: Optional[str]
    created_at: str
    updated_at: str


class MetadataStore:
    def __init__(self, settings: Settings) -> None:
        self._path = settings.database_path
        self._lock = threading.Lock()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._conn.close()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    file_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    kb_id TEXT NOT NULL,
                    source_uri TEXT NOT NULL UNIQUE,
                    current_version TEXT NOT NULL,
                    file_name TEXT,
                    content_type TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS file_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    file_name TEXT,
                    content_type TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(file_id, version),
                    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS outbox_events (
                    event_id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    kb_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    published_at TEXT,
                    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_file_versions_file_id
                    ON file_versions(file_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_outbox_status
                    ON outbox_events(status, retry_count, created_at);
                """
            )

    def get_file(self, file_id: str) -> Optional[FileRecord]:
        row = self._conn.execute(
            """
            SELECT file_id, tenant_id, kb_id, source_uri, current_version, file_name,
                   content_type, status, created_at, updated_at, deleted_at
            FROM files
            WHERE file_id = ?
            """,
            (file_id,),
        ).fetchone()
        if not row:
            return None
        return FileRecord(**dict(row))

    def get_file_by_source_uri(self, source_uri: str) -> Optional[FileRecord]:
        row = self._conn.execute(
            """
            SELECT file_id, tenant_id, kb_id, source_uri, current_version, file_name,
                   content_type, status, created_at, updated_at, deleted_at
            FROM files
            WHERE source_uri = ?
            """,
            (source_uri,),
        ).fetchone()
        if not row:
            return None
        return FileRecord(**dict(row))

    def latest_version(self, file_id: str) -> Optional[VersionRecord]:
        row = self._conn.execute(
            """
            SELECT id, file_id, version, storage_key, size_bytes, content_hash,
                   file_name, content_type, created_at
            FROM file_versions
            WHERE file_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (file_id,),
        ).fetchone()
        if not row:
            return None
        return VersionRecord(**dict(row))

    def list_file_versions(self, file_id: str, limit: int = 100) -> list[VersionRecord]:
        rows = self._conn.execute(
            """
            SELECT id, file_id, version, storage_key, size_bytes, content_hash,
                   file_name, content_type, created_at
            FROM file_versions
            WHERE file_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (file_id, limit),
        ).fetchall()
        return [VersionRecord(**dict(row)) for row in rows]

    def claim_outbox_events(
        self,
        limit: int,
        max_retry: int,
    ) -> list[OutboxRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, file_id, kb_id, event_type, status, payload_json, retry_count,
                       last_error, created_at, updated_at
                FROM outbox_events
                WHERE (status = 'pending' OR status = 'failed') AND retry_count < ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (max_retry, limit),
            ).fetchall()
            outbox = [
                OutboxRecord(
                    row["event_id"],
                    row["file_id"],
                    row["kb_id"],
                    row["event_type"],
                    row["status"],
                    _safe_payload(row["payload_json"]),
                    int(row["retry_count"]),
                    row["last_error"],
                    row["created_at"],
                    row["updated_at"],
                )
                for row in rows
            ]
            if not outbox:
                return []
            event_ids = [record.event_id for record in outbox]
            placeholders = ",".join(["?"] * len(event_ids))
            now = _now_iso()
            self._conn.execute(
                f"""
                UPDATE outbox_events
                SET status = 'sending', updated_at = ?
                WHERE event_id IN ({placeholders})
                """,
                (now, *event_ids),
            )
            return outbox

    def mark_outbox_success(self, event_id: str) -> None:
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE outbox_events
                SET status = 'published', published_at = ?, updated_at = ?, last_error = NULL
                WHERE event_id = ?
                """,
                (now, now, event_id),
            )

    def mark_outbox_failed(self, event_id: str, error: str) -> None:
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE outbox_events
                SET status = 'failed', retry_count = retry_count + 1, updated_at = ?, last_error = ?
                WHERE event_id = ?
                """,
                (now, error[:1000], event_id),
            )

    def create_file(
        self,
        *,
        file_id: str,
        tenant_id: str,
        kb_id: str,
        source_uri: str,
        current_version: str,
        file_name: Optional[str],
        content_type: Optional[str],
        storage_key: str,
        version: str,
        size_bytes: int,
        content_hash: str,
        event_id: str,
        event_payload: Dict[str, Any],
        status: str = "active",
    ) -> None:
        now = _now_iso()
        row_status = status if status else "active"
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO files (
                        file_id, tenant_id, kb_id, source_uri, current_version, file_name,
                        content_type, status, created_at, updated_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        file_id,
                        tenant_id,
                        kb_id,
                        source_uri,
                        current_version,
                        file_name,
                        content_type,
                        row_status,
                        now,
                        now,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO file_versions (
                        file_id, version, storage_key, size_bytes, content_hash, file_name, content_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        version,
                        storage_key,
                        size_bytes,
                        content_hash,
                        file_name,
                        content_type,
                        now,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id, file_id, kb_id, event_type, status, payload_json,
                        retry_count, last_error, created_at, updated_at, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, NULL)
                    """,
                    (
                        event_id,
                        file_id,
                        kb_id,
                        event_payload.get("event_type", "document.created"),
                        "pending",
                        _safe_json(event_payload),
                        now,
                        now,
                    ),
                )

    def append_version(
        self,
        *,
        file_id: str,
        version: str,
        storage_key: str,
        size_bytes: int,
        content_hash: str,
        file_name: Optional[str],
        content_type: Optional[str],
        event_id: str,
        event_payload: Dict[str, Any],
    ) -> None:
        if event_payload.get("event_type") not in {"document.updated", "document.created"}:
            raise ValueError("append_version supports update/create events only")
        now = _now_iso()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                UPDATE files
                SET current_version = ?, file_name = COALESCE(?, file_name),
                        content_type = COALESCE(?, content_type), deleted_at = NULL,
                        status = 'active', updated_at = ?
                WHERE file_id = ?
                """,
                (
                    version,
                    file_name,
                    content_type,
                        now,
                        file_id,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO file_versions (
                        file_id, version, storage_key, size_bytes, content_hash, file_name, content_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        version,
                        storage_key,
                        size_bytes,
                        content_hash,
                        file_name,
                        content_type,
                        now,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id, file_id, kb_id, event_type, status, payload_json,
                        retry_count, last_error, created_at, updated_at, published_at
                    )
                    SELECT ?, ?, kb_id, ?, 'pending', ?, 0, NULL, ?, ?, NULL
                    FROM files
                    WHERE file_id = ?
                    """,
                    (
                        event_id,
                        file_id,
                        event_payload.get("event_type", "document.updated"),
                        _safe_json(event_payload),
                        now,
                        now,
                        file_id,
                    ),
                )

    def touch_metadata(
        self,
        file_id: str,
        *,
        file_name: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> None:
        now = _now_iso()
        updates: list[str] = []
        values: list[Any] = []
        if file_name is not None:
            updates.append("file_name = ?")
            values.append(file_name)
        if content_type is not None:
            updates.append("content_type = ?")
            values.append(content_type)
        if not updates:
            return
        updates.append("updated_at = ?")
        values.append(now)
        update_clause = ", ".join(updates)
        sql = f"""
            UPDATE files
            SET {update_clause}
            WHERE file_id = ?
        """
        values.append(file_id)
        with self._lock:
            with self._conn:
                self._conn.execute(sql, tuple(values))

    def mark_deleted(
        self,
        file_id: str,
        event_id: str,
        event_payload: Dict[str, Any],
    ) -> None:
        now = _now_iso()
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    """
                    UPDATE files
                    SET status = 'deleted', deleted_at = ?, updated_at = ?
                    WHERE file_id = ? AND status != 'deleted'
                    """,
                    (now, now, file_id),
                )
                if row.rowcount == 0:
                    raise ValueError("file already deleted or missing")
                self._conn.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id, file_id, kb_id, event_type, status, payload_json,
                        retry_count, last_error, created_at, updated_at, published_at
                    )
                    SELECT ?, ?, kb_id, ?, 'pending', ?, 0, NULL, ?, ?, NULL
                    FROM files
                    WHERE file_id = ?
                    """,
                    (
                        event_id,
                        file_id,
                        event_payload.get("event_type", "document.deleted"),
                        _safe_json(event_payload),
                        now,
                        now,
                        file_id,
                    ),
                )

    def enqueue_event(
        self,
        *,
        file_id: str,
        event_id: str,
        event_payload: Dict[str, Any],
    ) -> None:
        now = _now_iso()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id, file_id, kb_id, event_type, status, payload_json,
                        retry_count, last_error, created_at, updated_at, published_at
                    )
                    SELECT ?, ?, kb_id, ?, 'pending', ?, 0, NULL, ?, ?, NULL
                    FROM files
                    WHERE file_id = ?
                    """,
                    (
                        event_id,
                        file_id,
                        event_payload.get("event_type", "document.updated"),
                        _safe_json(event_payload),
                        now,
                        now,
                        file_id,
                    ),
                )
