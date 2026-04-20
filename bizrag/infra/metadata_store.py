from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from bizrag.common.time_utils import utc_now


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
                    retriever_config_path TEXT NOT NULL,
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
                retriever_config_path TEXT NOT NULL,
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
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

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
            return dict(row)
        if isinstance(row, sqlite3.Row):
            return dict(row)
        if hasattr(row, "keys"):
            return {key: row[key] for key in row.keys()}
        return dict(row)

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

    def register_kb(
        self,
        *,
        kb_id: str,
        collection_name: str,
        workspace_dir: str,
        retriever_config_path: str,
        display_name: Optional[str] = None,
        source_root: Optional[str] = None,
        index_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = self.get_kb(kb_id)
        now = utc_now()
        if existing is None:
            self._execute(
                """
                INSERT INTO knowledge_bases (
                    kb_id, collection_name, display_name, source_root, workspace_dir,
                    retriever_config_path, index_uri, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kb_id,
                    collection_name,
                    display_name,
                    source_root,
                    workspace_dir,
                    retriever_config_path,
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
                    retriever_config_path = ?,
                    index_uri = ?,
                    updated_at = ?
                WHERE kb_id = ?
                """,
                (
                    collection_name,
                    display_name,
                    source_root,
                    workspace_dir,
                    retriever_config_path,
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

    def list_tasks(self, kb_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        if kb_id:
            cursor = self._execute(
                "SELECT * FROM tasks WHERE kb_id = ? ORDER BY created_at DESC LIMIT ?",
                (kb_id, limit),
            )
        else:
            cursor = self._execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
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

    def create_rustfs_event(
        self,
        *,
        event_id: str,
        kb_id: str,
        event_type: str,
        status: str,
        source_uri: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        self._execute(
            """
            INSERT INTO rustfs_events (
                event_id, kb_id, event_type, source_uri, status,
                payload_json, result_json, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def list_rustfs_events(self, kb_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        if kb_id:
            cursor = self._execute(
                "SELECT * FROM rustfs_events WHERE kb_id = ? ORDER BY created_at DESC LIMIT ?",
                (kb_id, limit),
            )
        else:
            cursor = self._execute(
                "SELECT * FROM rustfs_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
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

    def claim_rustfs_events(self, limit: int = 10) -> List[Dict[str, Any]]:
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
                update_rows = [(now, event_id) for event_id in event_ids]
                cursor = self._executemany(
                    """
                    UPDATE rustfs_events
                    SET status = 'running', updated_at = ?
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
            claimed.append(event)
        return claimed
