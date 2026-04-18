from __future__ import annotations

from fastapi import FastAPI

from bizrag.api.deps import lifespan
from bizrag.api.routers.read_http import router as read_router
from bizrag.api.routers.kb_admin_http import router as kb_admin_router
from bizrag.api.routers.rustfs_http import router as rustfs_router


fastapi_app = FastAPI(title="bizRAG HTTP API", lifespan=lifespan)
fastapi_app.include_router(read_router)
fastapi_app.include_router(kb_admin_router)
fastapi_app.include_router(rustfs_router)
