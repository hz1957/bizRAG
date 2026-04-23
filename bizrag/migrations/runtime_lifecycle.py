from __future__ import annotations

from typing import Any


def _table_has_column(store: Any, table_name: str, column_name: str) -> bool:
    if store.backend_name == "sqlite":
        cursor = store._execute(f"PRAGMA table_info({table_name})")
        try:
            for row in cursor.fetchall():
                data = store._row_to_dict(row) or {}
                if str(data.get("name") or "") == column_name:
                    return True
            return False
        finally:
            cursor.close()

    cursor = store._execute(
        """
        SELECT COUNT(*) AS total
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = ?
          AND column_name = ?
        """,
        (table_name, column_name),
    )
    try:
        row = store._row_to_dict(cursor.fetchone()) or {}
        return int(row.get("total") or 0) > 0
    finally:
        cursor.close()


def _add_column_if_missing(
    store: Any,
    *,
    table_name: str,
    column_name: str,
    sqlite_sql: str,
    mysql_sql: str,
) -> None:
    if _table_has_column(store, table_name, column_name):
        return
    store._execute(sqlite_sql if store.backend_name == "sqlite" else mysql_sql)


def migrate_runtime_lifecycle_schema(store: Any) -> None:
    _add_column_if_missing(
        store,
        table_name="rustfs_events",
        column_name="worker_id",
        sqlite_sql="ALTER TABLE rustfs_events ADD COLUMN worker_id TEXT",
        mysql_sql="ALTER TABLE rustfs_events ADD COLUMN worker_id VARCHAR(128) NULL",
    )
    _add_column_if_missing(
        store,
        table_name="rustfs_events",
        column_name="claimed_at",
        sqlite_sql="ALTER TABLE rustfs_events ADD COLUMN claimed_at TEXT",
        mysql_sql="ALTER TABLE rustfs_events ADD COLUMN claimed_at VARCHAR(64) NULL",
    )
    _add_column_if_missing(
        store,
        table_name="rustfs_events",
        column_name="heartbeat_at",
        sqlite_sql="ALTER TABLE rustfs_events ADD COLUMN heartbeat_at TEXT",
        mysql_sql="ALTER TABLE rustfs_events ADD COLUMN heartbeat_at VARCHAR(64) NULL",
    )
    _add_column_if_missing(
        store,
        table_name="rustfs_events",
        column_name="lease_expires_at",
        sqlite_sql="ALTER TABLE rustfs_events ADD COLUMN lease_expires_at TEXT",
        mysql_sql="ALTER TABLE rustfs_events ADD COLUMN lease_expires_at VARCHAR(64) NULL",
    )
    _add_column_if_missing(
        store,
        table_name="rustfs_events",
        column_name="attempt_count",
        sqlite_sql="ALTER TABLE rustfs_events ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0",
        mysql_sql="ALTER TABLE rustfs_events ADD COLUMN attempt_count INT NOT NULL DEFAULT 0",
    )

    store._execute(
        """
        UPDATE rustfs_events
        SET attempt_count = 0
        WHERE attempt_count IS NULL
        """
    )
