from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import FastAPI, HTTPException

from bizrag.service.kb_admin import KBAdmin
from bizrag.service.kb_registry import KBRegistry
from bizrag.service.retrieval_service import RetrievalService


@dataclass
class ApiRuntimeConfig:
    retriever_cfg: Optional[Dict[str, Any]] = None
    kb_registry: Optional[KBRegistry] = None
    metadata_db_path: str = "bizrag/state/metadata.db"
    workspace_root: str = "runtime/kbs"
    rustfs_token: str = ""
    rustfs_shared_secret: str = ""


_runtime_config = ApiRuntimeConfig()
_kb_admin: Optional[KBAdmin] = None
_retrieval_service: Optional[RetrievalService] = None


def configure_api(
    *,
    retriever_cfg: Dict[str, Any],
    kb_registry: KBRegistry,
    metadata_db_path: str,
    workspace_root: str,
    rustfs_token: str = "",
    rustfs_shared_secret: str = "",
) -> None:
    _runtime_config.retriever_cfg = retriever_cfg
    _runtime_config.kb_registry = kb_registry
    _runtime_config.metadata_db_path = metadata_db_path
    _runtime_config.workspace_root = workspace_root
    _runtime_config.rustfs_token = rustfs_token
    _runtime_config.rustfs_shared_secret = rustfs_shared_secret


def get_runtime_config() -> ApiRuntimeConfig:
    return _runtime_config


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _kb_admin, _retrieval_service

    if _runtime_config.retriever_cfg is None:
        raise RuntimeError("retriever_cfg is not set")
    if _runtime_config.kb_registry is None:
        raise RuntimeError("kb_registry is not set")

    _kb_admin = KBAdmin(
        metadata_db=_runtime_config.metadata_db_path,
        kb_registry_path=_runtime_config.kb_registry.path,
        workspace_root=_runtime_config.workspace_root,
    )
    _retrieval_service = RetrievalService(
        retriever_cfg=_runtime_config.retriever_cfg,
        kb_registry=_runtime_config.kb_registry,
    )
    try:
        yield
    finally:
        if _kb_admin is not None:
            _kb_admin.close()
            _kb_admin = None
        if _retrieval_service is not None:
            _retrieval_service.reset()
            _retrieval_service = None


def require_admin() -> KBAdmin:
    if _kb_admin is None:
        raise HTTPException(status_code=503, detail="KB admin is not initialized")
    return _kb_admin


def get_retrieval_service() -> RetrievalService:
    if _retrieval_service is None:
        raise HTTPException(status_code=503, detail="Retriever service is not initialized")
    return _retrieval_service


def _new_admin_instance() -> KBAdmin:
    if _runtime_config.kb_registry is None:
        raise HTTPException(status_code=503, detail="KB registry is not initialized")
    return KBAdmin(
        metadata_db=_runtime_config.metadata_db_path,
        kb_registry_path=_runtime_config.kb_registry.path,
        workspace_root=_runtime_config.workspace_root,
    )


async def run_admin_async(method_name: str, **kwargs: Any) -> Any:
    def _runner() -> Any:
        admin = _new_admin_instance()
        try:
            method = getattr(admin, method_name)
            return asyncio.run(method(**kwargs))
        finally:
            admin.close()

    return await asyncio.to_thread(_runner)
