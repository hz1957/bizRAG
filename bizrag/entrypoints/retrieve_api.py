from __future__ import annotations

import argparse

import uvicorn

from bizrag.api.app import fastapi_app
from bizrag.api.deps import configure_api
from bizrag.service.io_utils import load_yaml
from bizrag.service.kb_registry import KBRegistry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="bizRAG retrieve service")
    parser.add_argument(
        "--retriever-config",
        type=str,
        default="bizrag/servers/retriever/parameter.yaml",
        help="Path to retriever parameter yaml",
    )
    parser.add_argument(
        "--kb-registry",
        type=str,
        default="bizrag/config/kb_registry.yaml",
        help="Path to kb registry yaml",
    )
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
    configure_api(
        retriever_cfg=load_yaml(args.retriever_config),
        kb_registry=KBRegistry(args.kb_registry),
        metadata_db_path=args.metadata_db,
        workspace_root=args.workspace_root,
        rustfs_token=args.rustfs_token,
        rustfs_shared_secret=args.rustfs_shared_secret,
    )
    uvicorn.run(fastapi_app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
