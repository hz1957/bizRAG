from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from bizrag.api.deps import require_admin, run_admin_async
from bizrag.contracts.schemas import (
    DeleteDocumentRequest,
    IngestPathRequest,
    RebuildKBRequest,
    RegisterKBRequest,
)
from bizrag.common.errors import ServiceError
from bizrag.service.app.rustfs_events import replay_stored_rustfs_event


router = APIRouter()


@router.post("/api/v1/admin/kbs/register")
async def register_kb(req: RegisterKBRequest, request: Request) -> Dict[str, Any]:
    admin = require_admin(request)
    try:
        return admin.register_kb(
            kb_id=req.kb_id,
            source_parameters_path=req.source_parameters_path,
            collection_name=req.collection_name,
            display_name=req.display_name,
            source_root=req.source_root,
            index_uri=req.index_uri,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/admin/kbs")
async def list_kbs(request: Request) -> Dict[str, Any]:
    admin = require_admin(request)
    return {"items": admin.store.list_kbs()}


@router.delete("/api/v1/admin/kbs/{kb_id}")
async def delete_kb(kb_id: str, request: Request, force: bool = False) -> Dict[str, Any]:
    require_admin(request)
    try:
        return await run_admin_async(
            request,
            "delete_kb",
            kb_id=kb_id,
            force=force,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v1/admin/kbs/ingest")
async def ingest_kb_path(req: IngestPathRequest, request: Request) -> Dict[str, Any]:
    require_admin(request)
    try:
        return await run_admin_async(
            request,
            "ingest_path",
            kb_id=req.kb_id,
            path=req.path,
            sync_deletions=req.sync_deletions,
            force=req.force,
            prefer_mineru=req.prefer_mineru,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/admin/kbs/{kb_id}/documents")
async def list_documents(
    kb_id: str,
    request: Request,
    include_deleted: bool = False,
) -> Dict[str, Any]:
    admin = require_admin(request)
    return {"items": admin.store.list_documents(kb_id, include_deleted=include_deleted)}


@router.post("/api/v1/admin/kbs/delete-document")
async def delete_kb_document(req: DeleteDocumentRequest, request: Request) -> Dict[str, Any]:
    require_admin(request)
    try:
        return await run_admin_async(
            request,
            "delete_document",
            kb_id=req.kb_id,
            source_uri=req.source_uri,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v1/admin/kbs/rebuild")
async def rebuild_kb(req: RebuildKBRequest, request: Request) -> Dict[str, Any]:
    require_admin(request)
    try:
        return await run_admin_async(request, "rebuild_kb", kb_id=req.kb_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/admin/tasks")
async def list_tasks(
    request: Request,
    kb_id: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    admin = require_admin(request)
    return {"items": admin.store.list_tasks(kb_id=kb_id, limit=limit)}


@router.post("/api/v1/admin/tasks/{task_id}/retry")
async def retry_task(task_id: str, request: Request) -> Dict[str, Any]:
    require_admin(request)
    try:
        return await run_admin_async(request, "retry_task", task_id=task_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/admin/events")
async def list_rustfs_events(
    request: Request,
    kb_id: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    admin = require_admin(request)
    return {"items": admin.store.list_rustfs_events(kb_id=kb_id, limit=limit)}


@router.post("/api/v1/admin/events/{event_id}/replay")
async def replay_rustfs_event(event_id: str, request: Request) -> Dict[str, Any]:
    admin = require_admin(request)
    try:
        return await replay_stored_rustfs_event(
            admin=admin,
            event_id=event_id,
            run_admin_async=lambda method_name, **kwargs: run_admin_async(
                request,
                method_name,
                **kwargs,
            ),
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
