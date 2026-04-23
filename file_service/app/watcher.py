from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from watchfiles import Change, awatch

from .config import Settings
from .db import FileRecord, MetadataStore, VersionRecord
from .events import build_deleted_event, build_file_event, build_source_uri
from .kb_registry import KBAutoRegistrar
from .storage import LocalFileStorage


IGNORED_NAMES = {".git", ".venv", "node_modules", "__pycache__"}
IGNORED_SUFFIXES = {".tmp", ".swp", ".swo", ".temp", ".log", ".pid", ".sqlite", ".db"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _WatchTarget:
    kb_id: str
    relative_path: Path


def _should_watch(_: object, raw_path: str) -> bool:
    path = Path(raw_path)
    if path.name in IGNORED_NAMES:
        return False
    if path.name.startswith(".") and path.name != ".":  # ignore dot files in watch root
        return False
    if any(part in IGNORED_NAMES for part in path.parts):
        return False
    if path.is_dir():
        return True
    if any(path.name.endswith(suffix) for suffix in IGNORED_SUFFIXES):
        return False
    if path.name.endswith(".sqlite-journal") or path.name.endswith(".sqlite-wal") or path.name.endswith(".sqlite-shm"):
        return False
    return True


def _compute_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_file_id(tenant_id: str, kb_id: str, rel_path: Path) -> str:
    # 租户 + KB + KB 内相对路径 -> 稳定 file_id，便于重复启动后仍然能匹配同一个文档
    seed = f"{tenant_id}/{kb_id}/{rel_path.as_posix()}".encode("utf-8")
    return uuid.uuid5(uuid.NAMESPACE_URL, seed).hex


def _guess_content_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def _is_watcher_managed_file_id(value: str) -> bool:
    try:
        return uuid.UUID(hex=str(value)).version == 5
    except Exception:
        return False


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
        self._kb_registrar = KBAutoRegistrar(settings)
        self._watch_root = Path(settings.watch_root).resolve()
        self._watch_root.mkdir(parents=True, exist_ok=True)
        self._known_root_kb_ids: set[str] = set()

    async def run(self) -> None:
        reconcile_task: asyncio.Task[None] | None = None
        if self._settings.watch_initial_scan:
            try:
                await self._scan_initial()
            except Exception as exc:
                logger.exception("initial watch scan failed error=%s", exc)
        interval = float(self._settings.watch_reconcile_interval_seconds or 0.0)
        if interval > 0:
            reconcile_task = asyncio.create_task(self._periodic_reconcile(interval))
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
                        if path.is_dir():
                            if change in {Change.added, Change.modified}:
                                self._handle_directory_upsert(path)
                            continue
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
        finally:
            if reconcile_task is not None:
                reconcile_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reconcile_task

    async def _scan_initial(self) -> None:
        if not self._watch_root.exists():
            return
        self._sync_watch_root()

    async def _periodic_reconcile(self, interval_seconds: float) -> None:
        sleep_seconds = max(1.0, float(interval_seconds))
        while True:
            await asyncio.sleep(sleep_seconds)
            try:
                self._sync_watch_root()
            except Exception as exc:
                logger.exception("periodic watch reconcile failed error=%s", exc)

    def _handle_directory_upsert(self, directory: Path) -> None:
        if not directory.exists() or not directory.is_dir():
            return
        kb_id = self._resolve_root_kb_directory(directory)
        if kb_id:
            self._known_root_kb_ids.add(kb_id)
            self._kb_registrar.ensure_registered(kb_id)
        for path in sorted(directory.rglob("*")):
            if path.is_file() and _should_watch(None, str(path)):
                self._handle_upsert(path)

    def _sync_watch_root(self) -> None:
        current_root_kb_ids = self._ensure_root_directories_registered()
        expected_file_ids = self._collect_expected_file_ids_and_upsert()
        self._reconcile_missing_files(expected_file_ids)
        self._cleanup_removed_kb_dirs(current_root_kb_ids)
        self._known_root_kb_ids = set(current_root_kb_ids)

    def _ensure_root_directories_registered(self) -> set[str]:
        current_root_kb_ids: set[str] = set()
        if not self._watch_root.exists():
            return current_root_kb_ids
        for path in sorted(self._watch_root.iterdir()):
            if not path.is_dir() or not _should_watch(None, str(path)):
                continue
            kb_id = self._resolve_root_kb_directory(path)
            if kb_id:
                current_root_kb_ids.add(kb_id)
                try:
                    self._kb_registrar.ensure_registered(kb_id)
                except Exception as exc:
                    logger.exception("root KB auto-register failed kb_id=%s error=%s", kb_id, exc)
        return current_root_kb_ids

    def _collect_expected_file_ids_and_upsert(self) -> set[str]:
        expected: set[str] = set()
        if not self._watch_root.exists():
            return expected
        for path in sorted(self._watch_root.rglob("*")):
            if not path.is_file() or not _should_watch(None, str(path)):
                continue
            try:
                target = self._resolve_watch_target(path)
                if target is None:
                    continue
                expected.add(
                    _build_file_id(
                        self._settings.watch_tenant_id,
                        target.kb_id,
                        target.relative_path,
                    )
                )
                self._handle_upsert(path)
            except Exception as exc:
                logger.exception("watch reconcile upsert failed path=%s error=%s", path, exc)
        return expected

    def _reconcile_missing_files(self, expected_file_ids: set[str]) -> None:
        if not self._settings.watch_delete_sync:
            return
        active_rows = self._store.list_files(status="active")
        for row in active_rows:
            if row.tenant_id != self._settings.watch_tenant_id:
                continue
            if not _is_watcher_managed_file_id(row.file_id):
                continue
            if row.file_id in expected_file_ids:
                continue
            latest = self._store.latest_version(row.file_id)
            if latest is None:
                continue
            payload = _build_event_payload(
                event_type="document.deleted",
                file_record=row,
                version=latest,
                base_url=self._settings.download_base_url,
            )
            logger.info(
                "reconcile missing watch file as deleted kb_id=%s file_id=%s file_name=%s",
                row.kb_id,
                row.file_id,
                row.file_name,
            )
            self._store.mark_deleted(
                file_id=row.file_id,
                event_id=payload["event_id"],
                event_payload=payload,
            )

    def _cleanup_removed_kb_dirs(self, current_root_kb_ids: set[str]) -> None:
        fallback_kb_id = str(self._settings.watch_default_kb_id or "").strip()
        candidate_kb_ids: set[str] = set(self._known_root_kb_ids) - set(current_root_kb_ids)
        for row in self._store.list_files():
            if row.tenant_id != self._settings.watch_tenant_id:
                continue
            if not _is_watcher_managed_file_id(row.file_id):
                continue
            kb_id = str(row.kb_id or "").strip()
            if not kb_id or kb_id in current_root_kb_ids or kb_id == fallback_kb_id:
                continue
            candidate_kb_ids.add(kb_id)

        missing_root_kb_ids = candidate_kb_ids
        if not missing_root_kb_ids:
            return
        for kb_id in sorted(missing_root_kb_ids):
            if not kb_id or kb_id == fallback_kb_id:
                continue
            active_rows = self._store.list_files(kb_id=kb_id, status="active", limit=1)
            if active_rows:
                continue
            try:
                self._kb_registrar.ensure_deleted(kb_id, force=True)
            except Exception as exc:
                logger.warning("root KB auto-delete deferred kb_id=%s error=%s", kb_id, exc)

    def _handle_deleted(self, path: Path) -> None:
        if not self._settings.watch_delete_sync:
            return
        target = self._resolve_watch_target(path)
        if target is None:
            return
        file_id = _build_file_id(
            self._settings.watch_tenant_id,
            target.kb_id,
            target.relative_path,
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
        target = self._resolve_watch_target(path)
        if target is None:
            return
        self._kb_registrar.ensure_registered(target.kb_id)

        data = path.read_bytes()
        if not data:
            return
        digest = _compute_hash(data)
        file_id = _build_file_id(
            self._settings.watch_tenant_id,
            target.kb_id,
            target.relative_path,
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
                    kb_id=target.kb_id,
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
                    kb_id=target.kb_id,
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

    def _resolve_watch_target(self, path: Path) -> _WatchTarget | None:
        rel_path = self._relative_path(path)
        if rel_path is None or not rel_path.parts:
            return None

        # Backward-compatible fallback: files placed directly under watch_root
        # still target the configured default KB.
        if len(rel_path.parts) == 1:
            fallback_kb_id = str(self._settings.watch_default_kb_id or "").strip()
            if not fallback_kb_id:
                return None
            return _WatchTarget(kb_id=fallback_kb_id, relative_path=rel_path)

        kb_id = str(rel_path.parts[0]).strip()
        if not kb_id:
            return None
        return _WatchTarget(
            kb_id=kb_id,
            relative_path=Path(*rel_path.parts[1:]),
        )

    def _resolve_root_kb_directory(self, path: Path) -> str | None:
        if not path.exists() or not path.is_dir():
            return None
        rel_path = self._relative_path(path)
        if rel_path is None or len(rel_path.parts) != 1:
            return None
        kb_id = str(rel_path.parts[0]).strip()
        return kb_id or None
