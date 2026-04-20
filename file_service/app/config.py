from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    storage_root: str
    database_path: str
    source_uri_prefix: str
    base_url: str
    download_base_url: str
    rabbitmq_url: str
    rabbitmq_queue: str
    outbox_poll_interval_seconds: float
    outbox_batch_size: int
    max_retry: int
    publisher_backend: str
    http_bridge_url: str | None
    http_bridge_timeout_seconds: float
    cors_origins: str
    watch_enabled: bool
    watch_root: str
    watch_tenant_id: str
    watch_kb_id: str
    watch_recursive: bool
    watch_initial_scan: bool
    watch_debounce_seconds: float
    watch_delete_sync: bool


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _load() -> Settings:
    return Settings(
        host=os.environ.get("FILE_SERVICE_HOST", "0.0.0.0"),
        port=int(os.environ.get("FILE_SERVICE_PORT", "8002")),
        storage_root=os.environ.get("FILE_SERVICE_STORAGE_ROOT", "runtime/file_service/storage"),
        database_path=os.environ.get("FILE_SERVICE_DATABASE", "runtime/file_service/state/metadata.db"),
        source_uri_prefix=os.environ.get("FILE_SERVICE_SOURCE_URI_PREFIX", "filestore"),
        base_url=os.environ.get("FILE_SERVICE_BASE_URL", "http://127.0.0.1:8002"),
        download_base_url=os.environ.get(
            "FILE_SERVICE_DOWNLOAD_BASE_URL",
            os.environ.get("FILE_SERVICE_BASE_URL", "http://127.0.0.1:8002"),
        ),
        rabbitmq_url=os.environ.get(
            "FILE_SERVICE_RABBITMQ_URL",
            os.environ.get("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1/"),
        ),
        rabbitmq_queue=os.environ.get(
            "FILE_SERVICE_RABBITMQ_QUEUE",
            os.environ.get("RABBITMQ_QUEUE", "bizrag.rustfs.events"),
        ),
        outbox_poll_interval_seconds=float(os.environ.get("FILE_SERVICE_POLL_INTERVAL", "2")),
        outbox_batch_size=int(os.environ.get("FILE_SERVICE_BATCH_SIZE", "50")),
        max_retry=int(os.environ.get("FILE_SERVICE_MAX_RETRY", "12")),
        publisher_backend=os.environ.get("FILE_SERVICE_PUBLISHER_BACKEND", "rabbitmq").strip().lower(),
        http_bridge_url=os.environ.get("FILE_SERVICE_HTTP_BRIDGE_URL"),
        http_bridge_timeout_seconds=float(os.environ.get("FILE_SERVICE_HTTP_TIMEOUT", "5")),
        cors_origins=os.environ.get("FILE_SERVICE_CORS", ""),
        watch_enabled=_env_bool("FILE_SERVICE_WATCH_ENABLED", False),
        watch_root=os.environ.get("FILE_SERVICE_WATCH_ROOT", "runtime/file_service/watch"),
        watch_tenant_id=os.environ.get("FILE_SERVICE_WATCH_TENANT_ID", "default"),
        watch_kb_id=os.environ.get("FILE_SERVICE_WATCH_KB_ID", "default"),
        watch_recursive=_env_bool("FILE_SERVICE_WATCH_RECURSIVE", True),
        watch_initial_scan=_env_bool("FILE_SERVICE_WATCH_INITIAL_SCAN", True),
        watch_debounce_seconds=float(os.environ.get("FILE_SERVICE_WATCH_DEBOUNCE_SECONDS", "1.0")),
        watch_delete_sync=_env_bool("FILE_SERVICE_WATCH_DELETE_SYNC", True),
    )


def settings() -> Settings:
    return _load()
