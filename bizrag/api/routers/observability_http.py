from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse

from bizrag.api.deps import get_read_service, require_admin
from bizrag.service.app.file_service_inventory import FileServiceInventoryService
from bizrag.service.app.observability_service import ObservabilityService


router = APIRouter()
OPS_INDEX_HTML = Path(__file__).resolve().parents[1] / "static" / "ops" / "index.html"


def _service(request: Request) -> ObservabilityService:
    admin = require_admin(request)
    return ObservabilityService(store=admin.store)


@router.get("/api/v1/admin/ops/overview")
async def ops_overview(request: Request) -> Dict[str, Any]:
    read_service = get_read_service(request)
    return _service(request).build_overview(read_service_status=read_service.health_status())


@router.get("/api/v1/admin/ops/health")
async def ops_health(request: Request) -> Dict[str, Any]:
    read_service = get_read_service(request)
    return _service(request).build_health_snapshot(
        read_service_status=read_service.health_status()
    )


@router.get("/api/v1/admin/ops/metrics")
async def ops_metrics(request: Request) -> PlainTextResponse:
    read_service = get_read_service(request)
    body = _service(request).build_metrics_text(
        read_service_status=read_service.health_status()
    )
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")


@router.get("/api/v1/admin/ops/spans")
async def ops_spans(
    request: Request,
    component: Optional[str] = None,
    kb_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    admin = require_admin(request)
    return {
        "items": admin.store.list_operation_spans(
            component=component,
            kb_id=kb_id,
            trace_id=trace_id,
            status=status,
            limit=max(1, min(limit, 500)),
        )
    }


@router.get("/api/v1/admin/ops/files")
async def ops_files(
    request: Request,
    kb_id: Optional[str] = None,
    limit: int = 30,
    chunk_preview: int = 12,
) -> Dict[str, Any]:
    admin = require_admin(request)
    service = FileServiceInventoryService(workspace_root=admin.workspace_root)
    return service.build_inventory(
        kb_id=kb_id,
        limit=max(1, min(limit, 200)),
        chunk_preview=max(1, min(chunk_preview, 50)),
    )


@router.get("/ops")
async def ops_dashboard() -> FileResponse:
    return FileResponse(OPS_INDEX_HTML)
