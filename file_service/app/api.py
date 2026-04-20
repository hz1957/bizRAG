from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path as FastPath, Request, UploadFile
from fastapi.responses import FileResponse

from .config import Settings, settings as load_settings
from .db import FileRecord, MetadataStore, VersionRecord
from .events import build_download_url, build_source_uri
from .schemas import FileMetadataResponse, FileUpdateRequest, VersionResponse
from .storage import LocalFileStorage

router = APIRouter(prefix="/api/v1/files")


def get_store(request: Request) -> MetadataStore:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise RuntimeError("metadata store is not initialized")
    return store


def get_storage(request: Request) -> LocalFileStorage:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise RuntimeError("storage is not initialized")
    return storage


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _build_rustfs_event_payload(
    *,
    event_type: str,
    row: FileRecord,
    version: VersionRecord,
    cfg: Settings,
    event_id: str | None = None,
) -> dict:
    payload = {
        "event_id": event_id or str(uuid4()),
        "event_type": event_type,
        "kb_id": row.kb_id,
        "doc_id": row.file_id,
        "source_uri": row.source_uri,
        "new_source_uri": row.source_uri,
        "file_name": row.file_name or version.file_name,
        "content_type": row.content_type or version.content_type,
        "version": version.version,
        "content_hash": version.content_hash,
        "download_url": build_download_url(cfg.download_base_url, row.file_id),
    }
    return payload


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/")
async def create_file(
    kb_id: str = Form("default"),
    tenant_id: str = Form("default"),
    file_name: str | None = Form(None),
    content_type: str | None = Form(None),
    file: UploadFile = File(...),
    store: MetadataStore = Depends(get_store),
    storage: LocalFileStorage = Depends(get_storage),
) -> dict:
    cfg = load_settings()
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty file")

    version = uuid4().hex
    normalized_name = (file_name or file.filename or "file").strip() or "file"
    resolved_type = content_type or file.content_type or "application/octet-stream"
    digest = hashlib.sha256(payload).hexdigest()
    file_id = uuid4().hex
    source_uri = build_source_uri(cfg.source_uri_prefix, tenant_id, file_id)

    storage_key, size_bytes = storage.save_bytes(
        tenant_id=tenant_id,
        file_id=file_id,
        version=version,
        file_name=normalized_name,
        data=payload,
    )

    fake_record = FileRecord(
        file_id=file_id,
        tenant_id=tenant_id,
        kb_id=kb_id,
        source_uri=source_uri,
        current_version=version,
        file_name=normalized_name,
        content_type=resolved_type,
        status="active",
        created_at=_now_iso(),
        updated_at=_now_iso(),
        deleted_at=None,
    )
    fake_version = VersionRecord(
        id=0,
        file_id=file_id,
        version=version,
        storage_key=storage_key,
        size_bytes=size_bytes,
        content_hash=digest,
        file_name=normalized_name,
        content_type=resolved_type,
        created_at=_now_iso(),
    )
    event_payload = _build_rustfs_event_payload(
        event_type="document.created",
        row=fake_record,
        version=fake_version,
        cfg=cfg,
    )

    try:
        store.create_file(
            file_id=file_id,
            tenant_id=tenant_id,
            kb_id=kb_id,
            source_uri=source_uri,
            current_version=version,
            file_name=normalized_name,
            content_type=resolved_type,
            storage_key=storage_key,
            version=version,
            size_bytes=size_bytes,
            content_hash=digest,
            event_id=event_payload["event_id"],
            event_payload=event_payload,
            status="active",
        )
    except Exception as exc:
        storage.delete(storage_key)
        raise HTTPException(status_code=500, detail=f"create failed: {exc}") from exc

    return {
        "file_id": file_id,
        "tenant_id": tenant_id,
        "kb_id": kb_id,
        "source_uri": source_uri,
        "current_version": version,
        "file_name": normalized_name,
        "content_type": resolved_type,
        "status": "active",
        "size_bytes": size_bytes,
        "event": {
            "event_id": event_payload["event_id"],
            "event_type": event_payload["event_type"],
        },
    }


@router.put("/{file_id}/content")
async def update_content(
    file_id: str = FastPath(..., min_length=1),
    file_name: str | None = Form(None),
    content_type: str | None = Form(None),
    file: UploadFile = File(...),
    store: MetadataStore = Depends(get_store),
    storage: LocalFileStorage = Depends(get_storage),
) -> dict:
    cfg = load_settings()
    row = store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    if row.status == "deleted":
        raise HTTPException(status_code=409, detail="file deleted")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty file")

    version = uuid4().hex
    normalized_name = (file_name or row.file_name or file.filename or "file").strip() or "file"
    resolved_type = content_type or file.content_type or row.content_type or "application/octet-stream"
    digest = hashlib.sha256(payload).hexdigest()
    storage_key, size_bytes = storage.save_bytes(
        tenant_id=row.tenant_id,
        file_id=row.file_id,
        version=version,
        file_name=normalized_name,
        data=payload,
    )
    fake_file = FileRecord(
        file_id=row.file_id,
        tenant_id=row.tenant_id,
        kb_id=row.kb_id,
        source_uri=row.source_uri,
        current_version=version,
        file_name=normalized_name,
        content_type=resolved_type,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )
    fake_version = VersionRecord(
        id=0,
        file_id=row.file_id,
        version=version,
        storage_key=storage_key,
        size_bytes=size_bytes,
        content_hash=digest,
        file_name=normalized_name,
        content_type=resolved_type,
        created_at=_now_iso(),
    )
    event_payload = _build_rustfs_event_payload(
        event_type="document.updated",
        row=fake_file,
        version=fake_version,
        cfg=cfg,
    )

    try:
        store.append_version(
            file_id=row.file_id,
            version=version,
            storage_key=storage_key,
            size_bytes=size_bytes,
            content_hash=digest,
            file_name=normalized_name,
            content_type=resolved_type,
            event_id=event_payload["event_id"],
            event_payload=event_payload,
        )
    except Exception as exc:
        storage.delete(storage_key)
        raise HTTPException(status_code=500, detail=f"update failed: {exc}") from exc

    return {
        "file_id": row.file_id,
        "tenant_id": row.tenant_id,
        "kb_id": row.kb_id,
        "source_uri": row.source_uri,
        "current_version": version,
        "file_name": normalized_name,
        "content_type": resolved_type,
        "status": row.status,
        "size_bytes": size_bytes,
        "event": {
            "event_id": event_payload["event_id"],
            "event_type": event_payload["event_type"],
        },
    }


@router.patch("/{file_id}")
async def patch_file(
    request: FileUpdateRequest,
    file_id: str = FastPath(..., min_length=1),
    store: MetadataStore = Depends(get_store),
) -> dict:
    cfg = load_settings()
    row = store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    if row.status == "deleted":
        raise HTTPException(status_code=409, detail="file deleted")
    if request.file_name is None and request.content_type is None:
        return {"file_id": row.file_id, "status": "no_change"}

    store.touch_metadata(
        file_id=file_id,
        file_name=request.file_name,
        content_type=request.content_type,
    )

    updated = store.get_file(file_id)
    latest = store.latest_version(file_id=file_id)
    if updated is None or latest is None:
        raise HTTPException(status_code=500, detail="metadata refresh failed")

    event_payload = _build_rustfs_event_payload(
        event_type="document.updated",
        row=updated,
        version=latest,
        cfg=cfg,
    )
    store.enqueue_event(
        file_id=file_id,
        event_id=event_payload["event_id"],
        event_payload=event_payload,
    )
    return {
        "file_id": row.file_id,
        "event": {
            "event_id": event_payload["event_id"],
            "event_type": event_payload["event_type"],
        },
        "status": "updated",
    }


@router.delete("/{file_id}")
async def delete_file(
    file_id: str = FastPath(..., min_length=1),
    force: bool = False,
    store: MetadataStore = Depends(get_store),
) -> dict:
    row = store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    latest = store.latest_version(file_id=file_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="missing file version")
    if row.status == "deleted" and not force:
        return {"file_id": file_id, "status": "already_deleted"}

    event_payload = _build_rustfs_event_payload(
        event_type="document.deleted",
        row=row,
        version=latest,
        cfg=load_settings(),
        event_id=str(uuid4()),
    )
    try:
        store.mark_deleted(
            file_id=file_id,
            event_id=event_payload["event_id"],
            event_payload=event_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "file_id": file_id,
        "status": "deleted",
        "event": {
            "event_id": event_payload["event_id"],
            "event_type": event_payload["event_type"],
        },
    }


@router.get("/{file_id}")
async def get_file(
    file_id: str = FastPath(..., min_length=1),
    store: MetadataStore = Depends(get_store),
) -> FileMetadataResponse:
    row = store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    latest = store.latest_version(file_id=file_id)
    return FileMetadataResponse(
        file_id=row.file_id,
        tenant_id=row.tenant_id,
        kb_id=row.kb_id,
        source_uri=row.source_uri,
        current_version=row.current_version,
        file_name=row.file_name,
        content_type=row.content_type,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
        latest_version=(latest.version if latest else None),
    )


@router.get("/{file_id}/versions")
async def list_versions(
    file_id: str = FastPath(..., min_length=1),
    store: MetadataStore = Depends(get_store),
) -> list[VersionResponse]:
    row = store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    versions = store.list_file_versions(file_id)
    return [
        VersionResponse(
            id=v.id,
            file_id=v.file_id,
            version=v.version,
            storage_key=v.storage_key,
            size_bytes=v.size_bytes,
            content_hash=v.content_hash,
            file_name=v.file_name,
            content_type=v.content_type,
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.get("/{file_id}/content")
async def download(
    file_id: str = FastPath(..., min_length=1),
    store: MetadataStore = Depends(get_store),
    storage: LocalFileStorage = Depends(get_storage),
) -> FileResponse:
    row = store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    if row.status == "deleted":
        raise HTTPException(status_code=410, detail="file deleted")
    version = store.latest_version(file_id=file_id)
    if version is None:
        raise HTTPException(status_code=404, detail="file version missing")
    path = storage.resolve(version.storage_key)
    if not path.exists():
        raise HTTPException(status_code=410, detail="file blob missing")
    return FileResponse(
        path=str(path),
        media_type=row.content_type or "application/octet-stream",
        filename=version.file_name or row.file_name or "file",
    )
