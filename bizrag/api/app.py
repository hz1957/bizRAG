from __future__ import annotations

from fastapi import FastAPI

from bizrag.api.deps import lifespan
from bizrag.api.routers.admin import router as admin_router
from bizrag.api.routers.retrieve import router as retrieve_router
from bizrag.api.routers.rustfs import router as rustfs_router


fastapi_app = FastAPI(title="bizRAG Retrieve Service", lifespan=lifespan)
fastapi_app.include_router(retrieve_router)
fastapi_app.include_router(admin_router)
fastapi_app.include_router(rustfs_router)
