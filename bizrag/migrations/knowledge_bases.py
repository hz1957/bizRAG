from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from bizrag.migrations.source_parameters import (
    candidate_legacy_source_parameter_paths,
    infer_source_parameters_path_from_legacy_runtime,
)

_KNOWLEDGE_BASE_MIGRATED_DBS: set[str] = set()
_KNOWLEDGE_BASE_MIGRATIONS_LOCK = threading.Lock()


def _drop_legacy_retriever_config_path_column(store: Any) -> None:
    if store.backend_name == "sqlite":
        store._execute(
            """
            CREATE TABLE knowledge_bases__new (
                kb_id TEXT PRIMARY KEY,
                collection_name TEXT NOT NULL,
                display_name TEXT,
                source_root TEXT,
                workspace_dir TEXT NOT NULL,
                source_parameters_path TEXT NOT NULL,
                index_uri TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        store._execute(
            """
            INSERT INTO knowledge_bases__new (
                kb_id, collection_name, display_name, source_root, workspace_dir,
                source_parameters_path, index_uri, created_at, updated_at
            )
            SELECT
                kb_id,
                collection_name,
                display_name,
                source_root,
                workspace_dir,
                COALESCE(NULLIF(source_parameters_path, ''), retriever_config_path, ''),
                index_uri,
                created_at,
                updated_at
            FROM knowledge_bases
            """
        )
        store._execute("DROP TABLE knowledge_bases")
        store._execute("ALTER TABLE knowledge_bases__new RENAME TO knowledge_bases")
        return

    store._execute(
        """
        ALTER TABLE knowledge_bases
        DROP COLUMN retriever_config_path
        """
    )


def migrate_knowledge_bases_schema(store: Any) -> None:
    if not store._knowledge_bases_has_column("source_parameters_path"):
        if store.backend_name == "sqlite":
            store._execute(
                "ALTER TABLE knowledge_bases ADD COLUMN source_parameters_path TEXT"
            )
        else:
            store._execute(
                "ALTER TABLE knowledge_bases ADD COLUMN source_parameters_path TEXT NULL"
            )

    if store._knowledge_bases_has_column("retriever_config_path"):
        store._execute(
            """
            UPDATE knowledge_bases
            SET source_parameters_path = retriever_config_path
            WHERE (source_parameters_path IS NULL OR source_parameters_path = '')
              AND retriever_config_path IS NOT NULL
              AND retriever_config_path <> ''
            """
        )
        _drop_legacy_retriever_config_path_column(store)


def _load_knowledge_base_rows(store: Any) -> list[dict[str, Any]]:
    cursor = store._execute(
        """
        SELECT kb_id, collection_name, workspace_dir, source_parameters_path, index_uri
        FROM knowledge_bases
        WHERE source_parameters_path IS NOT NULL
          AND source_parameters_path <> ''
        """
    )
    try:
        return [store._row_to_dict(row) or {} for row in cursor.fetchall()]
    finally:
        cursor.close()


def _reconcile_legacy_source_parameter_paths(store: Any) -> None:
    if not store._knowledge_bases_has_column("source_parameters_path"):
        return

    updates: list[tuple[str, str]] = []
    for row in _load_knowledge_base_rows(store):
        current_path = str(row.get("source_parameters_path") or "").strip()
        inferred = infer_source_parameters_path_from_legacy_runtime(
            kb=row,
            current_source_parameters_path=current_path,
        )
        if inferred is None:
            continue
        inferred_path = str(inferred)
        if inferred_path != current_path:
            updates.append((inferred_path, str(row["kb_id"])))

    if not updates:
        return

    store._executemany(
        """
        UPDATE knowledge_bases
        SET source_parameters_path = ?
        WHERE kb_id = ?
        """,
        updates,
    )
    store.conn.commit()


def _cleanup_redundant_legacy_source_parameter_files(store: Any) -> None:
    for row in _load_knowledge_base_rows(store):
        current_path = Path(str(row.get("source_parameters_path") or "")).resolve()
        for legacy_path in candidate_legacy_source_parameter_paths(row["workspace_dir"]):
            if not legacy_path.is_file():
                continue
            if legacy_path.resolve() == current_path:
                continue
            inferred = infer_source_parameters_path_from_legacy_runtime(
                kb=row,
                current_source_parameters_path=legacy_path,
            )
            if inferred is None or inferred.resolve() != current_path:
                continue
            legacy_path.unlink(missing_ok=True)
            try:
                legacy_path.parent.rmdir()
            except OSError:
                pass


def run_knowledge_base_migrations_once(store: Any) -> None:
    cache_key = f"{store.backend_name}:{store.db_path}"
    with _KNOWLEDGE_BASE_MIGRATIONS_LOCK:
        if cache_key in _KNOWLEDGE_BASE_MIGRATED_DBS:
            return
        _KNOWLEDGE_BASE_MIGRATED_DBS.add(cache_key)
    try:
        _reconcile_legacy_source_parameter_paths(store)
        _cleanup_redundant_legacy_source_parameter_files(store)
    except Exception:
        with _KNOWLEDGE_BASE_MIGRATIONS_LOCK:
            _KNOWLEDGE_BASE_MIGRATED_DBS.discard(cache_key)
        raise
