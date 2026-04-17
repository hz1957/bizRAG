from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@dataclass
class MetadataStore:
    db_path: Path

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
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
            """
        )
        self.conn.commit()

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

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
            self.conn.execute(
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
            self.conn.execute(
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
        row = self.conn.execute(
            "SELECT * FROM knowledge_bases WHERE kb_id = ?",
            (kb_id,),
        ).fetchone()
        return self._row_to_dict(row)

    def list_kbs(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM knowledge_bases ORDER BY kb_id"
        ).fetchall()
        return [self._row_to_dict(row) for row in rows if row is not None]

    def get_document(self, kb_id: str, source_uri: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE kb_id = ? AND source_uri = ?",
            (kb_id, source_uri),
        ).fetchone()
        return self._row_to_dict(row)

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
            self.conn.execute(
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
            self.conn.execute(
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
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows if row is not None]

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
        self.conn.execute(
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
        self.conn.execute(
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
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        data = self._row_to_dict(row)
        if data is None:
            return None
        for field in ("payload_json", "result_json"):
            if data.get(field):
                data[field] = json.loads(data[field])
            else:
                data[field] = {}
        return data

    def list_tasks(self, kb_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        if kb_id:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE kb_id = ? ORDER BY created_at DESC LIMIT ?",
                (kb_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        tasks: List[Dict[str, Any]] = []
        for row in rows:
            task = self._row_to_dict(row)
            if task is None:
                continue
            for field in ("payload_json", "result_json"):
                if task.get(field):
                    task[field] = json.loads(task[field])
                else:
                    task[field] = {}
            tasks.append(task)
        return tasks
