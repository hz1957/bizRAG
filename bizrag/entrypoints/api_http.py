from __future__ import annotations

import argparse
import copy
import logging
import os

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from bizrag.api.app import fastapi_app
from bizrag.api.deps import configure_api, env_flag


QUIET_ACCESS_PATH_PREFIXES = (
    "/ops",
    "/ops-assets/",
    "/api/v1/admin/ops/",
    "/api/v1/admin/kbs",
    "/healthz",
)


class QuietAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = getattr(record, "args", ())
        if len(args) >= 3:
            path = str(args[2] or "")
            if any(path.startswith(prefix) for prefix in QUIET_ACCESS_PATH_PREFIXES):
                return False
        return True


def _uvicorn_log_config() -> dict:
    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})
    config["filters"]["quiet_access"] = {
        "()": "bizrag.entrypoints.api_http.QuietAccessLogFilter",
    }
    access_handler = config.get("handlers", {}).get("access")
    if isinstance(access_handler, dict):
        filters = list(access_handler.get("filters", []))
        if "quiet_access" not in filters:
            filters.append("quiet_access")
        access_handler["filters"] = filters
    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="bizRAG HTTP API service")
    parser.add_argument(
        "--metadata-db",
        type=str,
        default="bizrag/state/metadata.db",
        help="SQLite metadata DB path or MySQL DSN for admin endpoints",
    )
    parser.add_argument(
        "--workspace-root",
        type=str,
        default="runtime/kbs",
        help="Workspace root for corpus/chunk/index artifacts",
    )
    parser.add_argument(
        "--rustfs-token",
        type=str,
        default="",
        help="Optional shared token for RustFS webhook requests",
    )
    parser.add_argument(
        "--rustfs-shared-secret",
        type=str,
        default="",
        help="Optional HMAC secret for RustFS webhook signature verification",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=64501)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    warmup_kb_ids = [
        item.strip()
        for item in str(os.environ.get("BIZRAG_READ_WARMUP_KB_IDS", "")).split(",")
        if item.strip()
    ]
    configure_api(
        app=fastapi_app,
        metadata_db_path=args.metadata_db,
        workspace_root=args.workspace_root,
        rustfs_token=args.rustfs_token,
        rustfs_shared_secret=args.rustfs_shared_secret,
        read_warmup_enabled=env_flag("BIZRAG_READ_WARMUP", True),
        read_warmup_mode=str(os.environ.get("BIZRAG_READ_WARMUP_MODE", "all") or "all"),
        read_warmup_kb_ids=warmup_kb_ids,
    )
    uvicorn.run(
        fastapi_app,
        host=args.host,
        port=args.port,
        reload=False,
        log_config=_uvicorn_log_config(),
    )


if __name__ == "__main__":
    main()
