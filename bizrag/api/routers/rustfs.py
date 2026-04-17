from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException

from bizrag.api.deps import get_runtime_config, require_admin, run_admin_async
from bizrag.contracts.schemas import RustFSEventBatchRequest, RustFSEventRequest
from bizrag.service.errors import ServiceError
from bizrag.service.rustfs_event_service import (
    enqueue_rustfs_event,
    handle_rustfs_event_request,
    verify_rustfs_headers,
)


router = APIRouter()


@router.post("/api/v1/events/rustfs")
async def handle_rustfs_event(
    req: RustFSEventRequest,
    x_rustfs_token: Optional[str] = Header(default=None),
    x_rustfs_timestamp: Optional[str] = Header(default=None),
    x_rustfs_signature: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    admin = require_admin()
    runtime_config = get_runtime_config()
    try:
        return await handle_rustfs_event_request(
            admin=admin,
            req=req,
            run_admin_async=run_admin_async,
            token=runtime_config.rustfs_token,
            shared_secret=runtime_config.rustfs_shared_secret,
            x_rustfs_token=x_rustfs_token,
            x_rustfs_timestamp=x_rustfs_timestamp,
            x_rustfs_signature=x_rustfs_signature,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/v1/events/rustfs/batch")
async def handle_rustfs_batch(
    req: RustFSEventBatchRequest,
    x_rustfs_token: Optional[str] = Header(default=None),
    x_rustfs_timestamp: Optional[str] = Header(default=None),
    x_rustfs_signature: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    admin = require_admin()
    runtime_config = get_runtime_config()
    try:
        verify_rustfs_headers(
            req,
            token=runtime_config.rustfs_token,
            shared_secret=runtime_config.rustfs_shared_secret,
            x_rustfs_token=x_rustfs_token,
            x_rustfs_timestamp=x_rustfs_timestamp,
            x_rustfs_signature=x_rustfs_signature,
        )
        items: List[Dict[str, Any]] = []
        for event in req.events:
            try:
                result = await handle_rustfs_event_request(
                    admin=admin,
                    req=event,
                    run_admin_async=run_admin_async,
                    token=runtime_config.rustfs_token,
                    shared_secret=runtime_config.rustfs_shared_secret,
                    x_rustfs_token=None,
                    x_rustfs_timestamp=None,
                    x_rustfs_signature=None,
                    verify_headers=False,
                )
                items.append({"status": "success", **result})
            except ServiceError as exc:
                items.append(
                    {
                        "status": "failed",
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "detail": exc.detail,
                    }
                )
            except Exception as exc:
                items.append(
                    {
                        "status": "failed",
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "detail": str(exc),
                    }
                )
        return {"items": items}
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/v1/events/rustfs/queue")
async def queue_rustfs_event(
    req: RustFSEventRequest,
    x_rustfs_token: Optional[str] = Header(default=None),
    x_rustfs_timestamp: Optional[str] = Header(default=None),
    x_rustfs_signature: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    admin = require_admin()
    runtime_config = get_runtime_config()
    try:
        return enqueue_rustfs_event(
            admin=admin,
            req=req,
            token=runtime_config.rustfs_token,
            shared_secret=runtime_config.rustfs_shared_secret,
            x_rustfs_token=x_rustfs_token,
            x_rustfs_timestamp=x_rustfs_timestamp,
            x_rustfs_signature=x_rustfs_signature,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/v1/events/rustfs/queue/batch")
async def queue_rustfs_batch(
    req: RustFSEventBatchRequest,
    x_rustfs_token: Optional[str] = Header(default=None),
    x_rustfs_timestamp: Optional[str] = Header(default=None),
    x_rustfs_signature: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    admin = require_admin()
    runtime_config = get_runtime_config()
    try:
        verify_rustfs_headers(
            req,
            token=runtime_config.rustfs_token,
            shared_secret=runtime_config.rustfs_shared_secret,
            x_rustfs_token=x_rustfs_token,
            x_rustfs_timestamp=x_rustfs_timestamp,
            x_rustfs_signature=x_rustfs_signature,
        )
        items = [
            enqueue_rustfs_event(
                admin=admin,
                req=event,
                token=runtime_config.rustfs_token,
                shared_secret=runtime_config.rustfs_shared_secret,
                x_rustfs_token=None,
                x_rustfs_timestamp=None,
                x_rustfs_signature=None,
            )
            for event in req.events
        ]
        return {"items": items}
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
