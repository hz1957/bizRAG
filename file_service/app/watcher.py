from __future__ import annotations

import asyncio
import mimetypes
import hashlib
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from watchfiles import Change, awatch

from .config import Settings
from .db import FileRecord, MetadataStore, VersionRecord
from .events import build_deleted_event, build_file_event, build_source_uri
from .storage import LocalFileStorage


IGNORED_NAMES = {".git", ".venv", "node_modules", "__pycache__"}
IGNORED_SUFFIXES = {".tmp", ".swp", ".swo", ".temp", ".log", ".pid", ".sqlite", ".db"}
logger = logging.getLogger(__name__)


def _should_watch(_: object, raw_path: str) -> bool:
    path = Path(raw_path)
    if path.is_dir():
        return False
    if path.name in IGNORED_NAMES:
        return False
    if path.name.startswith(".") and path.name != ".":  # ignore dot files in watch root
        return False
    if any(part in IGNORED_NAMES for part in path.parts):
        return False
    if any(path.name.endswith(suffix) for suffix in IGNORED_SUFFIXES):
        return False
    if path.name.endswith(".sqlite-journal") or path.name.endswith(".sqlite-wal") or path.name.endswith(".sqlite-shm"):
        return False
    return True


def _compute_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_file_id(tenant_id: str, kb_id: str, rel_path: Path) -> str:
    # 文件路径 -> 稳定 file_id，便于重复启动后仍然能匹配同一个文档
    seed = f"{tenant_id}/{kb_id}/{rel_path.as_posix()}".encode("utf-8")
    return uuid.uuid5(uuid.NAMESPACE_URL, seed).hex


def _guess_content_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _build_event_payload(
    *,
    event_type: str,
    file_record: FileRecord,
    version: VersionRecord,
    base_url: str,
) -> dict[str, Any]:
    if event_type == "document.deleted":
        return build_deleted_event(file_record=file_record, version_record=version)
    return build_file_event(
        event_type=event_type,
        file_record=file_record,
        version_record=version,
        base_url=base_url,
        include_payload=True,
    )


class DirectoryWatcher:
    def __init__(self, settings: Settings, store: MetadataStore, storage: LocalFileStorage) -> None:
        self._settings = settings
        self._store = store
        self._storage = storage
        self._watch_root = Path(settings.watch_root).resolve()
        self._watch_root.mkdir(parents=True, exist_ok=True)

    async def run(self) -> None:
        if self._settings.watch_initial_scan:
            await self._scan_initial()
        try:
            async for changes in awatch(
                self._watch_root,
                recursive=self._settings.watch_recursive,
                watch_filter=_should_watch,
                debounce=int(max(self._settings.watch_debounce_seconds * 1000, 50)),
            ):
                for change, raw_path in changes:
                    path = Path(raw_path)
                    try:
                        if change == Change.deleted:
                            self._handle_deleted(path)
                        elif change in {Change.added, Change.modified}:
                            self._handle_upsert(path)
                    except Exception as exc:
                        logger.exception(
                            "file watch handling failed path=%s change=%s error=%s",
                            path,
                            change,
                            exc,
                        )
        except asyncio.CancelledError:
            return

    async def _scan_initial(self) -> None:
        if not self._watch_root.exists():
            return
        for path in sorted(self._watch_root.rglob("*")):
            if path.is_file() and _should_watch(None, str(path)):
                self._handle_upsert(path)

    def _handle_deleted(self, path: Path) -> None:
        if not self._settings.watch_delete_sync:
            return
        rel_path = self._relative_path(path)
        if rel_path is None:
            return
        file_id = _build_file_id(
            self._settings.watch_tenant_id,
            self._settings.watch_kb_id,
            rel_path,
        )
        row = self._store.get_file(file_id)
        if row is None or row.status == "deleted":
            return
        latest = self._store.latest_version(file_id)
        if latest is None:
            return
        payload = _build_event_payload(
            event_type="document.deleted",
            file_record=row,
            version=latest,
            base_url=self._settings.download_base_url,
        )
        self._store.mark_deleted(
            file_id=file_id,
            event_id=payload["event_id"],
            event_payload=payload,
        )

    def _handle_upsert(self, path: Path) -> None:
        if not path.exists():
            return
        rel_path = self._relative_path(path)
        if rel_path is None:
            return

        data = path.read_bytes()
        if not data:
            return
        digest = _compute_hash(data)
        file_id = _build_file_id(
            self._settings.watch_tenant_id,
            self._settings.watch_kb_id,
            rel_path,
        )
        source_uri = build_source_uri(
            prefix=self._settings.source_uri_prefix,
            tenant_id=self._settings.watch_tenant_id,
            file_id=file_id,
        )
        row = self._store.get_file(file_id)
        existing_version = self._store.latest_version(file_id)
        if existing_version is not None and row is not None and row.status != "deleted":
            if existing_version.content_hash == digest:
                return
        version = uuid.uuid4().hex
        now = _now_iso()
        content_type = _guess_content_type(path)
        storage_key, size_bytes = self._storage.save_bytes(
            tenant_id=self._settings.watch_tenant_id,
            file_id=file_id,
            version=version,
            file_name=path.name,
            data=data,
        )

        try:
            if row is None:
                record = FileRecord(
                    file_id=file_id,
                    tenant_id=self._settings.watch_tenant_id,
                    kb_id=self._settings.watch_kb_id,
                    source_uri=source_uri,
                    current_version=version,
                    file_name=path.name,
                    content_type=content_type,
                    status="active",
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
                version_record = VersionRecord(
                    id=0,
                    file_id=file_id,
                    version=version,
                    storage_key=storage_key,
                    size_bytes=size_bytes,
                    content_hash=digest,
                    file_name=path.name,
                    content_type=content_type,
                    created_at=now,
                )
                payload = _build_event_payload(
                    event_type="document.created",
                    file_record=record,
                    version=version_record,
                    base_url=self._settings.download_base_url,
                )
                self._store.create_file(
                    file_id=file_id,
                    tenant_id=self._settings.watch_tenant_id,
                    kb_id=self._settings.watch_kb_id,
                    source_uri=source_uri,
                    current_version=version,
                    file_name=path.name,
                    content_type=content_type,
                    storage_key=storage_key,
                    version=version,
                    size_bytes=size_bytes,
                    content_hash=digest,
                    event_id=payload["event_id"],
                    event_payload=payload,
                    status="active",
                )
            else:
                event_type = "document.created" if row.status == "deleted" else "document.updated"
                latest = self._store.latest_version(file_id)
                if latest is not None and latest.content_hash == digest:
                    return
                record = FileRecord(
                    file_id=row.file_id,
                    tenant_id=row.tenant_id,
                    kb_id=row.kb_id,
                    source_uri=row.source_uri,
                    current_version=version,
                    file_name=path.name,
                    content_type=content_type,
                    status="active",
                    created_at=row.created_at,
                    updated_at=now,
                    deleted_at=None,
                )
                version_record = VersionRecord(
                    id=0,
                    file_id=file_id,
                    version=version,
                    storage_key=storage_key,
                    size_bytes=size_bytes,
                    content_hash=digest,
                    file_name=path.name,
                    content_type=content_type,
                    created_at=now,
                )
                payload = _build_event_payload(
                    event_type=event_type,
                    file_record=record,
                    version=version_record,
                    base_url=self._settings.download_base_url,
                )
                self._store.append_version(
                    file_id=file_id,
                    version=version,
                    storage_key=storage_key,
                    size_bytes=size_bytes,
                    content_hash=digest,
                    file_name=path.name,
                    content_type=content_type,
                    event_id=payload["event_id"],
                    event_payload=payload,
                )
        except Exception:
            self._storage.delete(storage_key)
            raise

    def _relative_path(self, path: Path) -> Path | None:
        try:
            return path.resolve().relative_to(self._watch_root)
        except ValueError:
            return None
