from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import settings as load_settings
from .db import MetadataStore
from .publisher import OutboxPublisher
from .storage import LocalFileStorage
from .watcher import DirectoryWatcher

_cfg = load_settings()

app = FastAPI(title="file_service")
app.include_router(router)

origins = [item.strip() for item in _cfg.cors_origins.split(",") if item.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def startup() -> None:
    cfg = _cfg
    store = MetadataStore(cfg)
    storage = LocalFileStorage(cfg)
    app.state.store = store
    app.state.storage = storage

    publisher = OutboxPublisher(cfg, store)
    app.state.publisher = publisher
    app.state.publisher_task = asyncio.create_task(publisher.run())
    if cfg.watch_enabled:
        watcher = DirectoryWatcher(cfg, store, storage)
        app.state.watcher = watcher
        app.state.watcher_task = asyncio.create_task(watcher.run())


@app.on_event("shutdown")
async def shutdown() -> None:
    store = getattr(app.state, "store", None)
    publisher = getattr(app.state, "publisher", None)
    task = getattr(app.state, "publisher_task", None)
    watcher_task = getattr(app.state, "watcher_task", None)
    if publisher is not None:
        publisher.stop()
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    if watcher_task is not None:
        watcher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher_task
    if store is not None:
        store.close()
