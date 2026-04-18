from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import FastAPI, HTTPException, Request

from bizrag.service.app.kb_admin import KBAdmin
from bizrag.service.ultrarag.read_service import ReadService


@dataclass
class ApiRuntimeConfig:
    metadata_db_path: str = "bizrag/state/metadata.db"
    workspace_root: str = "runtime/kbs"
    rustfs_token: str = ""
    rustfs_shared_secret: str = ""


@dataclass
class ApiServices:
    admin: Optional[KBAdmin] = None
    read_service: Optional[ReadService] = None


STATE_RUNTIME_CONFIG = "bizrag_runtime_config"
STATE_SERVICES = "bizrag_services"


def configure_api(
    *,
    app: FastAPI,
    metadata_db_path: str,
    workspace_root: str,
    rustfs_token: str = "",
    rustfs_shared_secret: str = "",
) -> None:
    setattr(
        app.state,
        STATE_RUNTIME_CONFIG,
        ApiRuntimeConfig(
            metadata_db_path=metadata_db_path,
            workspace_root=workspace_root,
            rustfs_token=rustfs_token,
            rustfs_shared_secret=rustfs_shared_secret,
        ),
    )


def _get_runtime_config_from_app(app: FastAPI) -> ApiRuntimeConfig:
    config = getattr(app.state, STATE_RUNTIME_CONFIG, None)
    if config is None:
        raise RuntimeError("API runtime config is not set")
    return config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = _get_runtime_config_from_app(app)
    services = ApiServices(
        admin=KBAdmin(
            metadata_db=config.metadata_db_path,
            workspace_root=config.workspace_root,
        ),
        read_service=ReadService(
            metadata_db=config.metadata_db_path,
        ),
    )
    setattr(app.state, STATE_SERVICES, services)
    try:
        yield
    finally:
        if services.admin is not None:
            services.admin.close()
        if services.read_service is not None:
            services.read_service.reset()
        setattr(app.state, STATE_SERVICES, ApiServices())


def _get_services(request: Request) -> ApiServices:
    services = getattr(request.app.state, STATE_SERVICES, None)
    if services is None:
        raise HTTPException(status_code=503, detail="API services are not initialized")
    return services


def get_runtime_config(request: Request) -> ApiRuntimeConfig:
    return _get_runtime_config_from_app(request.app)


def require_admin(request: Request) -> KBAdmin:
    admin = _get_services(request).admin
    if admin is None:
        raise HTTPException(status_code=503, detail="KB admin is not initialized")
    return admin


def get_read_service(request: Request) -> ReadService:
    read_service = _get_services(request).read_service
    if read_service is None:
        raise HTTPException(status_code=503, detail="Read service is not initialized")
    return read_service


def _new_admin_instance(app: FastAPI) -> KBAdmin:
    config = _get_runtime_config_from_app(app)
    return KBAdmin(
        metadata_db=config.metadata_db_path,
        workspace_root=config.workspace_root,
    )


async def run_admin_async(request: Request, method_name: str, **kwargs: Any) -> Any:
    def _runner() -> Any:
        admin = _new_admin_instance(request.app)
        try:
            method = getattr(admin, method_name)
            return asyncio.run(method(**kwargs))
        finally:
            admin.close()

    return await asyncio.to_thread(_runner)
