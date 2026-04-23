from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from bizrag.common.time_utils import utc_now
from bizrag.migrations.knowledge_bases import (
    migrate_knowledge_bases_schema,
    run_knowledge_base_migrations_once,
)
from bizrag.migrations.runtime_lifecycle import migrate_runtime_lifecycle_schema


@dataclass
class MetadataStore:
    db_path: str | Path
    backend_name: str = field(init=False)
    conn: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        target = str(self.db_path)
        if self._is_mysql_dsn(target):
            self.backend_name = "mysql"
            self.conn = self._connect_mysql(target)
        elif "://" in target:
            raise RuntimeError(f"Unsupported metadata store DSN: {target}")
        else:
            self.backend_name = "sqlite"
            sqlite_path = Path(target)
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(sqlite_path))
            self.conn.row_factory = sqlite3.Row
        self._init_schema()
        run_knowledge_base_migrations_once(self)

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def _is_mysql_dsn(target: str) -> bool:
        scheme = urlparse(target).scheme.lower()
        return scheme in {"mysql", "mysql+pymysql"}

    def _connect_mysql(self, dsn: str) -> Any:
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise RuntimeError(
                "MySQL metadata store requires PyMySQL. Install with `pip install PyMySQL`."
            ) from exc

        parsed = urlparse(dsn)
        database = parsed.path.lstrip("/")
        if not parsed.hostname or not database:
            raise RuntimeError(f"Invalid MySQL DSN: {dsn}")

        query = parse_qs(parsed.query)
        charset = query.get("charset", ["utf8mb4"])[0]
        return pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=database,
            charset=charset,
            # Use autocommit for the shared API connection so repeated reads do
            # not get stuck on a stale transaction snapshot. Explicit write
            # transactions still call begin()/commit() where needed.
            autocommit=True,
            cursorclass=DictCursor,
        )

    def _init_schema(self) -> None:
        if self.backend_name == "sqlite":
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    kb_id TEXT PRIMARY KEY,
                    collection_name TEXT NOT NULL,
                    display_name TEXT,
                    source_root TEXT,
                    workspace_dir TEXT NOT NULL,
                    source_parameters_path TEXT NOT NULL,
                    index_uri TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                    kb_id TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    doc_key TEXT NOT NULL,
                    file_name TEXT,
                    source_type TEXT,
                    content_hash TEXT,
                    doc_version TEXT,
                    status TEXT NOT NULL,
                    corpus_path TEXT,
                    chunk_path TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    PRIMARY KEY (kb_id, source_uri)
                );

                CREATE INDEX IF NOT EXISTS idx_documents_kb_status
                ON documents (kb_id, status);

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_uri TEXT,
                    payload_json TEXT,
                    result_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_kb_created
                ON tasks (kb_id, created_at);

                CREATE TABLE IF NOT EXISTS rustfs_events (
                    event_id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source_uri TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT,
                    result_json TEXT,
                    error_message TEXT,
                    worker_id TEXT,
                    claimed_at TEXT,
                    heartbeat_at TEXT,
                    lease_expires_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_rustfs_events_kb_created
                ON rustfs_events (kb_id, created_at);

                CREATE TABLE IF NOT EXISTS operation_spans (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    component TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    kb_id TEXT,
                    task_id TEXT,
                    event_id TEXT,
                    source_uri TEXT,
                    status TEXT NOT NULL,
                    details_json TEXT,
                    error_message TEXT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_ms REAL
                );

                CREATE INDEX IF NOT EXISTS idx_operation_spans_started
                ON operation_spans (started_at);

                CREATE INDEX IF NOT EXISTS idx_operation_spans_component_status
                ON operation_spans (component, status, started_at);
                """
            )
            migrate_knowledge_bases_schema(self)
            migrate_runtime_lifecycle_schema(self)
            self.conn.commit()
            return

        statements = [
            """
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                kb_id VARCHAR(255) PRIMARY KEY,
                collection_name VARCHAR(255) NOT NULL,
                display_name VARCHAR(255) NULL,
                source_root TEXT NULL,
                workspace_dir TEXT NOT NULL,
                source_parameters_path TEXT NOT NULL,
                index_uri TEXT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS documents (
                kb_id VARCHAR(255) NOT NULL,
                source_uri VARCHAR(512) NOT NULL,
                doc_key VARCHAR(128) NOT NULL,
                file_name VARCHAR(255) NULL,
                source_type VARCHAR(64) NULL,
                content_hash VARCHAR(128) NULL,
                doc_version VARCHAR(255) NULL,
                status VARCHAR(64) NOT NULL,
                corpus_path TEXT NULL,
                chunk_path TEXT NULL,
                last_error TEXT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                deleted_at VARCHAR(64) NULL,
                PRIMARY KEY (kb_id, source_uri),
                INDEX idx_documents_kb_status (kb_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id VARCHAR(64) PRIMARY KEY,
                kb_id VARCHAR(255) NOT NULL,
                task_type VARCHAR(128) NOT NULL,
                status VARCHAR(64) NOT NULL,
                source_uri VARCHAR(512) NULL,
                payload_json LONGTEXT NULL,
                result_json LONGTEXT NULL,
                error_message LONGTEXT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                INDEX idx_tasks_kb_created (kb_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rustfs_events (
                event_id VARCHAR(128) PRIMARY KEY,
                kb_id VARCHAR(255) NOT NULL,
                event_type VARCHAR(128) NOT NULL,
                source_uri VARCHAR(512) NULL,
                status VARCHAR(64) NOT NULL,
                payload_json LONGTEXT NULL,
                result_json LONGTEXT NULL,
                error_message LONGTEXT NULL,
                worker_id VARCHAR(128) NULL,
                claimed_at VARCHAR(64) NULL,
                heartbeat_at VARCHAR(64) NULL,
                lease_expires_at VARCHAR(64) NULL,
                attempt_count INT NOT NULL DEFAULT 0,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                INDEX idx_rustfs_events_kb_created (kb_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS operation_spans (
                span_id VARCHAR(64) PRIMARY KEY,
                trace_id VARCHAR(64) NOT NULL,
                parent_span_id VARCHAR(64) NULL,
                component VARCHAR(64) NOT NULL,
                operation VARCHAR(128) NOT NULL,
                kb_id VARCHAR(255) NULL,
                task_id VARCHAR(64) NULL,
                event_id VARCHAR(128) NULL,
                source_uri VARCHAR(512) NULL,
                status VARCHAR(64) NOT NULL,
                details_json LONGTEXT NULL,
                error_message LONGTEXT NULL,
                started_at VARCHAR(64) NOT NULL,
                ended_at VARCHAR(64) NULL,
                duration_ms DOUBLE NULL,
                INDEX idx_operation_spans_started (started_at),
                INDEX idx_operation_spans_component_status (component, status, started_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ]
        try:
            for statement in statements:
                self._execute(statement)
            migrate_knowledge_bases_schema(self)
            migrate_runtime_lifecycle_schema(self)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _knowledge_bases_has_column(self, column_name: str) -> bool:
        if self.backend_name == "sqlite":
            cursor = self._execute("PRAGMA table_info(knowledge_bases)")
            try:
                for row in cursor.fetchall():
                    data = self._row_to_dict(row) or {}
                    if str(data.get("name") or "") == column_name:
                        return True
                return False
            finally:
                cursor.close()

        cursor = self._execute(
            """
            SELECT COUNT(*) AS total
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = ?
              AND column_name = ?
            """,
            ("knowledge_bases", column_name),
        )
        try:
            row = self._row_to_dict(cursor.fetchone()) or {}
            return int(row.get("total") or 0) > 0
        finally:
            cursor.close()

    def _sql(self, sql: str) -> str:
        if self.backend_name == "mysql":
            return sql.replace("?", "%s")
        return sql

    def _execute(self, sql: str, params: Iterable[Any] | None = None) -> Any:
        cursor = self.conn.cursor()
        try:
            cursor.execute(self._sql(sql), tuple(params or ()))
            return cursor
        except Exception:
            cursor.close()
            raise

    def _executemany(self, sql: str, params_seq: Iterable[Iterable[Any]]) -> Any:
        cursor = self.conn.cursor()
        try:
            cursor.executemany(self._sql(sql), [tuple(params) for params in params_seq])
            return cursor
        except Exception:
            cursor.close()
            raise

    @staticmethod
    def _row_to_dict(row: Optional[Any]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        if isinstance(row, dict):
            data = dict(row)
        elif isinstance(row, sqlite3.Row):
            data = dict(row)
        elif hasattr(row, "keys"):
            data = {key: row[key] for key in row.keys()}
        else:
            data = dict(row)

        return data

    @staticmethod
    def _decode_json_fields(data: Optional[Dict[str, Any]], *fields: str) -> Optional[Dict[str, Any]]:
        if data is None:
            return None
        for field in fields:
            value = data.get(field)
            if value:
                data[field] = json.loads(value)
            else:
                data[field] = {}
        return data

    @staticmethod
    def _parse_iso_ts(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _future_utc_iso(seconds: float) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))).isoformat()

    def register_kb(
        self,
        *,
        kb_id: str,
        collection_name: str,
        workspace_dir: str,
        source_parameters_path: Optional[str] = None,
        display_name: Optional[str] = None,
        source_root: Optional[str] = None,
        index_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_source_parameters_path = str(source_parameters_path or "").strip()
        if not resolved_source_parameters_path:
            raise RuntimeError("register_kb requires source_parameters_path")
        existing = self.get_kb(kb_id)
        now = utc_now()
        if existing is None:
            self._execute(
                """
                INSERT INTO knowledge_bases (
                    kb_id, collection_name, display_name, source_root, workspace_dir,
                    source_parameters_path, index_uri, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kb_id,
                    collection_name,
                    display_name,
                    source_root,
                    workspace_dir,
                    resolved_source_parameters_path,
                    index_uri,
                    now,
                    now,
                ),
            )
        else:
            self._execute(
                """
                UPDATE knowledge_bases
                SET collection_name = ?,
                    display_name = ?,
                    source_root = ?,
                    workspace_dir = ?,
                    source_parameters_path = ?,
                    index_uri = ?,
                    updated_at = ?
                WHERE kb_id = ?
                """,
                (
                    collection_name,
                    display_name,
                    source_root,
                    workspace_dir,
                    resolved_source_parameters_path,
                    index_uri,
                    now,
                    kb_id,
                ),
            )
        self.conn.commit()
        kb = self.get_kb(kb_id)
        assert kb is not None
        return kb

    def get_kb(self, kb_id: str) -> Optional[Dict[str, Any]]:
        cursor = self._execute(
            "SELECT * FROM knowledge_bases WHERE kb_id = ?",
            (kb_id,),
        )
        try:
            return self._row_to_dict(cursor.fetchone())
        finally:
            cursor.close()

    def list_kbs(self) -> List[Dict[str, Any]]:
        cursor = self._execute("SELECT * FROM knowledge_bases ORDER BY kb_id")
        try:
            return [self._row_to_dict(row) for row in cursor.fetchall() if row is not None]
        finally:
            cursor.close()

    def count_kbs(self) -> int:
        cursor = self._execute("SELECT COUNT(*) AS total FROM knowledge_bases")
        try:
            row = self._row_to_dict(cursor.fetchone()) or {}
            return int(row.get("total") or 0)
        finally:
            cursor.close()

    def _count_rows(self, table: str, *, where_sql: str, params: Iterable[Any]) -> int:
        cursor = self._execute(
            f"SELECT COUNT(*) AS total FROM {table} WHERE {where_sql}",
            params,
        )
        try:
            row = self._row_to_dict(cursor.fetchone()) or {}
            return int(row.get("total") or 0)
        finally:
            cursor.close()

    def delete_kb(self, kb_id: str) -> Dict[str, int]:
        counts = {
            "documents": self._count_rows("documents", where_sql="kb_id = ?", params=(kb_id,)),
            "tasks": self._count_rows("tasks", where_sql="kb_id = ?", params=(kb_id,)),
            "rustfs_events": self._count_rows("rustfs_events", where_sql="kb_id = ?", params=(kb_id,)),
            "operation_spans": self._count_rows(
                "operation_spans",
                where_sql="kb_id = ?",
                params=(kb_id,),
            ),
            "knowledge_bases": self._count_rows(
                "knowledge_bases",
                where_sql="kb_id = ?",
                params=(kb_id,),
            ),
        }

        if self.backend_name == "sqlite":
            self.conn.execute("BEGIN IMMEDIATE")
        else:
            self.conn.begin()

        try:
            for table in (
                "operation_spans",
                "tasks",
                "rustfs_events",
                "documents",
                "knowledge_bases",
            ):
                cursor = self._execute(f"DELETE FROM {table} WHERE kb_id = ?", (kb_id,))
                cursor.close()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return counts

    def get_document(self, kb_id: str, source_uri: str) -> Optional[Dict[str, Any]]:
        cursor = self._execute(
            "SELECT * FROM documents WHERE kb_id = ? AND source_uri = ?",
            (kb_id, source_uri),
        )
        try:
            return self._row_to_dict(cursor.fetchone())
        finally:
            cursor.close()

    def upsert_document(
        self,
        *,
        kb_id: str,
        source_uri: str,
        doc_key: str,
        file_name: str,
        source_type: str,
        content_hash: str,
        doc_version: str,
        status: str,
        corpus_path: Optional[str],
        chunk_path: Optional[str],
        last_error: Optional[str] = None,
        deleted_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = self.get_document(kb_id, source_uri)
        now = utc_now()
        if existing is None:
            self._execute(
                """
                INSERT INTO documents (
                    kb_id, source_uri, doc_key, file_name, source_type, content_hash,
                    doc_version, status, corpus_path, chunk_path, last_error,
                    created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kb_id,
                    source_uri,
                    doc_key,
                    file_name,
                    source_type,
                    content_hash,
                    doc_version,
                    status,
                    corpus_path,
                    chunk_path,
                    last_error,
                    now,
                    now,
                    deleted_at,
                ),
            )
        else:
            self._execute(
                """
                UPDATE documents
                SET doc_key = ?,
                    file_name = ?,
                    source_type = ?,
                    content_hash = ?,
                    doc_version = ?,
                    status = ?,
                    corpus_path = ?,
                    chunk_path = ?,
                    last_error = ?,
                    updated_at = ?,
                    deleted_at = ?
                WHERE kb_id = ? AND source_uri = ?
                """,
                (
                    doc_key,
                    file_name,
                    source_type,
                    content_hash,
                    doc_version,
                    status,
                    corpus_path,
                    chunk_path,
                    last_error,
                    now,
                    deleted_at,
                    kb_id,
                    source_uri,
                ),
            )
        self.conn.commit()
        doc = self.get_document(kb_id, source_uri)
        assert doc is not None
        return doc

    def mark_document_deleted(self, kb_id: str, source_uri: str) -> Optional[Dict[str, Any]]:
        existing = self.get_document(kb_id, source_uri)
        if existing is None:
            return None
        deleted_at = utc_now()
        return self.upsert_document(
            kb_id=kb_id,
            source_uri=source_uri,
            doc_key=str(existing["doc_key"]),
            file_name=str(existing.get("file_name") or ""),
            source_type=str(existing.get("source_type") or ""),
            content_hash=str(existing.get("content_hash") or ""),
            doc_version=str(existing.get("doc_version") or ""),
            status="deleted",
            corpus_path=existing.get("corpus_path"),
            chunk_path=existing.get("chunk_path"),
            last_error=None,
            deleted_at=deleted_at,
        )

    def list_documents(
        self,
        kb_id: str,
        *,
        include_deleted: bool = False,
        source_prefix: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM documents WHERE kb_id = ?"
        params: List[Any] = [kb_id]
        if not include_deleted:
            sql += " AND status != 'deleted'"
        if source_prefix:
            sql += " AND source_uri LIKE ?"
            params.append(f"{source_prefix}%")
        sql += " ORDER BY updated_at DESC, source_uri ASC"
        cursor = self._execute(sql, params)
        try:
            return [self._row_to_dict(row) for row in cursor.fetchall() if row is not None]
        finally:
            cursor.close()

    def count_documents_by_status(self, kb_id: Optional[str] = None) -> Dict[str, int]:
        sql = "SELECT status, COUNT(*) AS total FROM documents"
        params: List[Any] = []
        if kb_id:
            sql += " WHERE kb_id = ?"
            params.append(kb_id)
        sql += " GROUP BY status"
        cursor = self._execute(sql, params)
        try:
            counts: Dict[str, int] = {}
            for row in cursor.fetchall():
                data = self._row_to_dict(row) or {}
                counts[str(data.get("status") or "unknown")] = int(data.get("total") or 0)
            return counts
        finally:
            cursor.close()

    def create_task(
        self,
        *,
        task_id: str,
        kb_id: str,
        task_type: str,
        status: str,
        source_uri: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        self._execute(
            """
            INSERT INTO tasks (
                task_id, kb_id, task_type, status, source_uri,
                payload_json, result_json, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                kb_id,
                task_type,
                status,
                source_uri,
                json.dumps(payload or {}, ensure_ascii=False),
                None,
                None,
                now,
                now,
            ),
        )
        self.conn.commit()
        task = self.get_task(task_id)
        assert task is not None
        return task

    def update_task(
        self,
        task_id: str,
        *,
        status: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_task(task_id)
        if existing is None:
            return None
        now = utc_now()
        self._execute(
            """
            UPDATE tasks
            SET status = ?,
                result_json = ?,
                error_message = ?,
                updated_at = ?
            WHERE task_id = ?
            """,
            (
                status or existing["status"],
                json.dumps(
                    result if result is not None else existing["result_json"],
                    ensure_ascii=False,
                ),
                error_message,
                now,
                task_id,
            ),
        )
        self.conn.commit()
        return self.get_task(task_id)

    def touch_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        existing = self.get_task(task_id)
        if existing is None:
            return None
        self._execute(
            """
            UPDATE tasks
            SET updated_at = ?
            WHERE task_id = ? AND status = 'running'
            """,
            (utc_now(), task_id),
        )
        self.conn.commit()
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        cursor = self._execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        try:
            return self._decode_json_fields(
                self._row_to_dict(cursor.fetchone()),
                "payload_json",
                "result_json",
            )
        finally:
            cursor.close()

    def list_tasks(
        self,
        kb_id: Optional[str] = None,
        limit: int = 20,
        *,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if kb_id:
            clauses.append("kb_id = ?")
            params.append(kb_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM tasks"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = self._execute(sql, params)
        try:
            tasks: List[Dict[str, Any]] = []
            for row in cursor.fetchall():
                task = self._decode_json_fields(
                    self._row_to_dict(row),
                    "payload_json",
                    "result_json",
                )
                if task is not None:
                    tasks.append(task)
            return tasks
        finally:
            cursor.close()

    def count_tasks_by_status(self, kb_id: Optional[str] = None) -> Dict[str, int]:
        sql = "SELECT status, COUNT(*) AS total FROM tasks"
        params: List[Any] = []
        if kb_id:
            sql += " WHERE kb_id = ?"
            params.append(kb_id)
        sql += " GROUP BY status"
        cursor = self._execute(sql, params)
        try:
            counts: Dict[str, int] = {}
            for row in cursor.fetchall():
                data = self._row_to_dict(row) or {}
                counts[str(data.get("status") or "unknown")] = int(data.get("total") or 0)
            return counts
        finally:
            cursor.close()

    def reconcile_stale_tasks(self, *, timeout_seconds: float, limit: int = 200) -> List[Dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(0.0, float(timeout_seconds)))
        stale: List[Dict[str, Any]] = []
        for task in self.list_tasks(limit=max(1, limit), status="running"):
            updated_at = self._parse_iso_ts(str(task.get("updated_at") or ""))
            if updated_at is None or updated_at > cutoff:
                continue
            stale.append(task)

        if not stale:
            return []

        now = utc_now()
        error_message = "Task heartbeat expired before completion"
        rows = [( "cancelled", error_message, now, str(task["task_id"])) for task in stale]
        cursor = self._executemany(
            """
            UPDATE tasks
            SET status = ?, error_message = ?, updated_at = ?
            WHERE task_id = ? AND status = 'running'
            """,
            rows,
        )
        cursor.close()
        self.conn.commit()
        return stale

    def create_rustfs_event(
        self,
        *,
        event_id: str,
        kb_id: str,
        event_type: str,
        status: str,
        source_uri: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        worker_id: Optional[str] = None,
        claimed_at: Optional[str] = None,
        heartbeat_at: Optional[str] = None,
        lease_expires_at: Optional[str] = None,
        attempt_count: int = 0,
    ) -> Dict[str, Any]:
        now = utc_now()
        self._execute(
            """
            INSERT INTO rustfs_events (
                event_id, kb_id, event_type, source_uri, status,
                payload_json, result_json, error_message,
                worker_id, claimed_at, heartbeat_at, lease_expires_at, attempt_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                kb_id,
                event_type,
                source_uri,
                status,
                json.dumps(payload or {}, ensure_ascii=False),
                None,
                None,
                worker_id,
                claimed_at,
                heartbeat_at,
                lease_expires_at,
                int(attempt_count),
                now,
                now,
            ),
        )
        self.conn.commit()
        event = self.get_rustfs_event(event_id)
        assert event is not None
        return event

    def update_rustfs_event(
        self,
        event_id: str,
        *,
        status: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        worker_id: Optional[str] = None,
        claimed_at: Optional[str] = None,
        heartbeat_at: Optional[str] = None,
        lease_expires_at: Optional[str] = None,
        attempt_count: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_rustfs_event(event_id)
        if existing is None:
            return None
        now = utc_now()
        self._execute(
            """
            UPDATE rustfs_events
            SET status = ?,
                result_json = ?,
                error_message = ?,
                worker_id = ?,
                claimed_at = ?,
                heartbeat_at = ?,
                lease_expires_at = ?,
                attempt_count = ?,
                updated_at = ?
            WHERE event_id = ?
            """,
            (
                status or existing["status"],
                json.dumps(
                    result if result is not None else existing["result_json"],
                    ensure_ascii=False,
                ),
                error_message,
                worker_id if worker_id is not None else existing.get("worker_id"),
                claimed_at if claimed_at is not None else existing.get("claimed_at"),
                heartbeat_at if heartbeat_at is not None else existing.get("heartbeat_at"),
                lease_expires_at if lease_expires_at is not None else existing.get("lease_expires_at"),
                int(attempt_count if attempt_count is not None else existing.get("attempt_count") or 0),
                now,
                event_id,
            ),
        )
        self.conn.commit()
        return self.get_rustfs_event(event_id)

    def get_rustfs_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        cursor = self._execute(
            "SELECT * FROM rustfs_events WHERE event_id = ?",
            (event_id,),
        )
        try:
            return self._decode_json_fields(
                self._row_to_dict(cursor.fetchone()),
                "payload_json",
                "result_json",
            )
        finally:
            cursor.close()

    def list_rustfs_events(
        self,
        kb_id: Optional[str] = None,
        limit: int = 20,
        *,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if kb_id:
            clauses.append("kb_id = ?")
            params.append(kb_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM rustfs_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = self._execute(sql, params)
        try:
            events: List[Dict[str, Any]] = []
            for row in cursor.fetchall():
                event = self._decode_json_fields(
                    self._row_to_dict(row),
                    "payload_json",
                    "result_json",
                )
                if event is not None:
                    events.append(event)
            return events
        finally:
            cursor.close()

    def count_rustfs_events_by_status(self, kb_id: Optional[str] = None) -> Dict[str, int]:
        sql = "SELECT status, COUNT(*) AS total FROM rustfs_events"
        params: List[Any] = []
        if kb_id:
            sql += " WHERE kb_id = ?"
            params.append(kb_id)
        sql += " GROUP BY status"
        cursor = self._execute(sql, params)
        try:
            counts: Dict[str, int] = {}
            for row in cursor.fetchall():
                data = self._row_to_dict(row) or {}
                counts[str(data.get("status") or "unknown")] = int(data.get("total") or 0)
            return counts
        finally:
            cursor.close()

    def touch_rustfs_event_lease(
        self,
        event_id: str,
        *,
        worker_id: str,
        lease_seconds: float,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_rustfs_event(event_id)
        if existing is None:
            return None
        now = utc_now()
        self._execute(
            """
            UPDATE rustfs_events
            SET worker_id = ?,
                heartbeat_at = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE event_id = ? AND status = 'running'
            """,
            (
                worker_id,
                now,
                self._future_utc_iso(lease_seconds),
                now,
                event_id,
            ),
        )
        self.conn.commit()
        return self.get_rustfs_event(event_id)

    def finish_rustfs_event(
        self,
        event_id: str,
        *,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_rustfs_event(event_id)
        if existing is None:
            return None
        now = utc_now()
        self._execute(
            """
            UPDATE rustfs_events
            SET status = ?,
                result_json = ?,
                error_message = ?,
                worker_id = NULL,
                claimed_at = NULL,
                heartbeat_at = NULL,
                lease_expires_at = NULL,
                updated_at = ?
            WHERE event_id = ?
            """,
            (
                status,
                json.dumps(
                    result if result is not None else existing.get("result_json") or {},
                    ensure_ascii=False,
                ),
                error_message,
                now,
                event_id,
            ),
        )
        self.conn.commit()
        return self.get_rustfs_event(event_id)

    def create_operation_span(
        self,
        *,
        span_id: str,
        trace_id: str,
        parent_span_id: Optional[str],
        component: str,
        operation: str,
        kb_id: Optional[str],
        task_id: Optional[str],
        event_id: Optional[str],
        source_uri: Optional[str],
        status: str,
        started_at: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._execute(
            """
            INSERT INTO operation_spans (
                span_id, trace_id, parent_span_id, component, operation,
                kb_id, task_id, event_id, source_uri, status,
                details_json, error_message, started_at, ended_at, duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                span_id,
                trace_id,
                parent_span_id,
                component,
                operation,
                kb_id,
                task_id,
                event_id,
                source_uri,
                status,
                json.dumps(details or {}, ensure_ascii=False),
                None,
                started_at,
                None,
                None,
            ),
        )
        self.conn.commit()
        span = self.get_operation_span(span_id)
        assert span is not None
        return span

    def finish_operation_span(
        self,
        *,
        span_id: str,
        status: str,
        ended_at: str,
        duration_ms: float,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_operation_span(span_id)
        if existing is None:
            return None
        self._execute(
            """
            UPDATE operation_spans
            SET status = ?,
                details_json = ?,
                error_message = ?,
                ended_at = ?,
                duration_ms = ?
            WHERE span_id = ?
            """,
            (
                status,
                json.dumps(details or existing.get("details_json") or {}, ensure_ascii=False),
                error_message,
                ended_at,
                float(duration_ms),
                span_id,
            ),
        )
        self.conn.commit()
        return self.get_operation_span(span_id)

    def update_operation_span(
        self,
        *,
        span_id: str,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_operation_span(span_id)
        if existing is None:
            return None
        self._execute(
            """
            UPDATE operation_spans
            SET details_json = ?,
                error_message = COALESCE(?, error_message)
            WHERE span_id = ?
            """,
            (
                json.dumps(details or existing.get("details_json") or {}, ensure_ascii=False),
                error_message,
                span_id,
            ),
        )
        self.conn.commit()
        return self.get_operation_span(span_id)

    def get_operation_span(self, span_id: str) -> Optional[Dict[str, Any]]:
        cursor = self._execute(
            "SELECT * FROM operation_spans WHERE span_id = ?",
            (span_id,),
        )
        try:
            return self._decode_json_fields(self._row_to_dict(cursor.fetchone()), "details_json")
        finally:
            cursor.close()

    def list_operation_spans(
        self,
        *,
        component: Optional[str] = None,
        kb_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if component:
            clauses.append("component = ?")
            params.append(component)
        if kb_id:
            clauses.append("kb_id = ?")
            params.append(kb_id)
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM operation_spans"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        cursor = self._execute(sql, params)
        try:
            rows: List[Dict[str, Any]] = []
            for row in cursor.fetchall():
                item = self._decode_json_fields(self._row_to_dict(row), "details_json")
                if item is not None:
                    rows.append(item)
            return rows
        finally:
            cursor.close()

    def abandon_operation_spans(
        self,
        *,
        event_ids: Optional[Iterable[str]] = None,
        task_ids: Optional[Iterable[str]] = None,
        reason: str,
        limit: int = 500,
    ) -> List[str]:
        event_id_set = {str(item).strip() for item in (event_ids or []) if str(item).strip()}
        task_id_set = {str(item).strip() for item in (task_ids or []) if str(item).strip()}
        if not event_id_set and not task_id_set:
            return []

        matching_trace_ids: set[str] = set()
        running_rows = self.list_operation_spans(status="running", limit=max(1, limit))
        for row in running_rows:
            event_id = str(row.get("event_id") or "").strip()
            task_id = str(row.get("task_id") or "").strip()
            if event_id in event_id_set or task_id in task_id_set:
                trace_id = str(row.get("trace_id") or "").strip()
                if trace_id:
                    matching_trace_ids.add(trace_id)

        abandoned: List[str] = []
        now = utc_now()
        for row in running_rows:
            event_id = str(row.get("event_id") or "").strip()
            task_id = str(row.get("task_id") or "").strip()
            trace_id = str(row.get("trace_id") or "").strip()
            if (
                event_id not in event_id_set
                and task_id not in task_id_set
                and trace_id not in matching_trace_ids
            ):
                continue
            started_at = self._parse_iso_ts(str(row.get("started_at") or ""))
            ended_at = self._parse_iso_ts(now) or datetime.now(timezone.utc)
            duration_ms = 0.0
            if started_at is not None:
                duration_ms = max(0.0, (ended_at - started_at).total_seconds() * 1000.0)
            details = dict(row.get("details_json") or {})
            details["abandon_reason"] = reason
            self.finish_operation_span(
                span_id=str(row["span_id"]),
                status="abandoned",
                ended_at=now,
                duration_ms=duration_ms,
                details=details,
                error_message=reason,
            )
            abandoned.append(str(row["span_id"]))
        return abandoned

    def reconcile_orphaned_operation_spans(self, *, limit: int = 500) -> List[str]:
        terminal_statuses = {"abandoned", "cancelled", "failed"}
        running_rows = self.list_operation_spans(status="running", limit=max(1, limit))
        if not running_rows:
            return []

        traces: Dict[str, List[Dict[str, Any]]] = {}
        for row in running_rows:
            trace_id = str(row.get("trace_id") or "").strip()
            if not trace_id or trace_id in traces:
                continue
            traces[trace_id] = self.list_operation_spans(trace_id=trace_id, limit=max(20, limit))

        abandoned: List[str] = []
        now = utc_now()
        for row in running_rows:
            trace_id = str(row.get("trace_id") or "").strip()
            trace_rows = traces.get(trace_id, [])
            by_span_id = {str(item.get("span_id") or ""): item for item in trace_rows}
            parent_span_id = str(row.get("parent_span_id") or "").strip()
            should_abandon = False
            while parent_span_id:
                parent = by_span_id.get(parent_span_id)
                if parent is None:
                    break
                if str(parent.get("status") or "") in terminal_statuses:
                    should_abandon = True
                    break
                parent_span_id = str(parent.get("parent_span_id") or "").strip()
            if not should_abandon:
                continue

            started_at = self._parse_iso_ts(str(row.get("started_at") or ""))
            ended_at = self._parse_iso_ts(now) or datetime.now(timezone.utc)
            duration_ms = 0.0
            if started_at is not None:
                duration_ms = max(0.0, (ended_at - started_at).total_seconds() * 1000.0)
            details = dict(row.get("details_json") or {})
            details["abandon_reason"] = "Parent span already reached a terminal state"
            self.finish_operation_span(
                span_id=str(row["span_id"]),
                status="abandoned",
                ended_at=now,
                duration_ms=duration_ms,
                details=details,
                error_message="Parent span already reached a terminal state",
            )
            abandoned.append(str(row["span_id"]))
        return abandoned

    def reconcile_runtime_state(
        self,
        *,
        task_timeout_seconds: float,
        event_lease_seconds: float,
        event_max_attempts: int,
    ) -> Dict[str, List[str]]:
        stale_tasks = self.reconcile_stale_tasks(timeout_seconds=task_timeout_seconds)
        event_result = self.reconcile_expired_rustfs_events(
            lease_seconds=event_lease_seconds,
            max_attempts=event_max_attempts,
        )
        abandoned_spans = self.abandon_operation_spans(
            task_ids=[str(task["task_id"]) for task in stale_tasks],
            event_ids=[*event_result["requeued"], *event_result["failed"]],
            reason="Runtime lease/heartbeat expired before completion",
        )
        abandoned_spans.extend(self.reconcile_orphaned_operation_spans())
        return {
            "cancelled_tasks": [str(task["task_id"]) for task in stale_tasks],
            "requeued_events": event_result["requeued"],
            "failed_events": event_result["failed"],
            "abandoned_spans": abandoned_spans,
        }

    def claim_rustfs_events(
        self,
        *,
        limit: int = 10,
        worker_id: str,
        lease_seconds: float,
    ) -> List[Dict[str, Any]]:
        if self.backend_name == "sqlite":
            self.conn.execute("BEGIN IMMEDIATE")
            lock_clause = ""
        else:
            self.conn.begin()
            lock_clause = " FOR UPDATE"

        try:
            cursor = self._execute(
                f"""
                SELECT * FROM rustfs_events
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?{lock_clause}
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            cursor.close()

            event_ids = [str(row["event_id"]) for row in rows]
            if event_ids:
                now = utc_now()
                lease_expires_at = self._future_utc_iso(lease_seconds)
                update_rows = [
                    (worker_id, now, now, lease_expires_at, now, event_id)
                    for event_id in event_ids
                ]
                cursor = self._executemany(
                    """
                    UPDATE rustfs_events
                    SET status = 'running',
                        error_message = NULL,
                        worker_id = ?,
                        claimed_at = ?,
                        heartbeat_at = ?,
                        lease_expires_at = ?,
                        attempt_count = COALESCE(attempt_count, 0) + 1,
                        updated_at = ?
                    WHERE event_id = ? AND status = 'queued'
                    """,
                    update_rows,
                )
                cursor.close()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        claimed: List[Dict[str, Any]] = []
        for row in rows:
            event = self._decode_json_fields(
                self._row_to_dict(row),
                "payload_json",
                "result_json",
            )
            if event is None:
                continue
            event["status"] = "running"
            event["worker_id"] = worker_id
            event["claimed_at"] = now
            event["heartbeat_at"] = now
            event["lease_expires_at"] = lease_expires_at
            event["attempt_count"] = int(event.get("attempt_count") or 0) + 1
            claimed.append(event)
        return claimed

    def reconcile_expired_rustfs_events(
        self,
        *,
        lease_seconds: float,
        max_attempts: int,
        limit: int = 200,
    ) -> Dict[str, List[str]]:
        now_dt = datetime.now(timezone.utc)
        expired: List[Dict[str, Any]] = []
        for event in self.list_rustfs_events(limit=max(1, limit), status="running"):
            lease_expires = self._parse_iso_ts(str(event.get("lease_expires_at") or ""))
            fallback = self._parse_iso_ts(str(event.get("updated_at") or ""))
            expires_at = lease_expires or (
                fallback + timedelta(seconds=max(0.0, float(lease_seconds))) if fallback else None
            )
            if expires_at is None or expires_at > now_dt:
                continue
            expired.append(event)

        if not expired:
            return {"requeued": [], "failed": []}

        requeued_ids: List[str] = []
        failed_ids: List[str] = []
        now = utc_now()
        for event in expired:
            event_id = str(event["event_id"])
            attempt_count = int(event.get("attempt_count") or 0)
            worker_id = str(event.get("worker_id") or "")
            if attempt_count >= max(1, int(max_attempts)):
                self._execute(
                    """
                    UPDATE rustfs_events
                    SET status = 'failed',
                        error_message = ?,
                        worker_id = NULL,
                        claimed_at = NULL,
                        heartbeat_at = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE event_id = ? AND status = 'running'
                    """,
                    (
                        f"Event lease expired after {attempt_count} attempts (worker={worker_id or 'unknown'})",
                        now,
                        event_id,
                    ),
                )
                failed_ids.append(event_id)
            else:
                self._execute(
                    """
                    UPDATE rustfs_events
                    SET status = 'queued',
                        error_message = ?,
                        worker_id = NULL,
                        claimed_at = NULL,
                        heartbeat_at = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE event_id = ? AND status = 'running'
                    """,
                    (
                        f"Event lease expired; requeued from worker={worker_id or 'unknown'}",
                        now,
                        event_id,
                    ),
                )
                requeued_ids.append(event_id)
        self.conn.commit()
        return {"requeued": requeued_ids, "failed": failed_ids}
