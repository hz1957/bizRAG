from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Dict

from bizrag.service.app.kb_admin import KBAdmin


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BizRAG knowledge-base admin")
    parser.add_argument(
        "--metadata-db",
        type=str,
        default="bizrag/state/metadata.db",
        help="SQLite metadata DB path or MySQL DSN",
    )
    parser.add_argument(
        "--workspace-root",
        type=str,
        default="runtime/kbs",
        help="Workspace root for corpus/chunk/index artifacts",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register-kb")
    register.add_argument("--kb-id", required=True)
    register.add_argument("--retriever-config", required=True)
    register.add_argument("--collection-name")
    register.add_argument("--display-name")
    register.add_argument("--source-root")
    register.add_argument("--index-uri")

    ingest = subparsers.add_parser("ingest-path")
    ingest.add_argument("--kb-id", required=True)
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--sync-deletions", action="store_true")
    ingest.add_argument("--force", action="store_true")
    ingest.add_argument("--prefer-mineru", action="store_true")
    ingest.add_argument("--chunk-backend", default="sentence")
    ingest.add_argument("--chunk-size", type=int, default=512)
    ingest.add_argument("--chunk-overlap", type=int, default=50)

    delete = subparsers.add_parser("delete-document")
    delete.add_argument("--kb-id", required=True)
    delete.add_argument("--source-uri", required=True)

    rebuild = subparsers.add_parser("rebuild-kb")
    rebuild.add_argument("--kb-id", required=True)

    retry = subparsers.add_parser("retry-task")
    retry.add_argument("--task-id", required=True)

    list_docs = subparsers.add_parser("list-documents")
    list_docs.add_argument("--kb-id", required=True)
    list_docs.add_argument("--include-deleted", action="store_true")

    list_tasks = subparsers.add_parser("list-tasks")
    list_tasks.add_argument("--kb-id")
    list_tasks.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("list-kbs")

    return parser.parse_args()


async def run_command(args: argparse.Namespace) -> Dict[str, Any]:
    admin = KBAdmin(
        metadata_db=args.metadata_db,
        workspace_root=args.workspace_root,
    )
    try:
        if args.command == "register-kb":
            return admin.register_kb(
                kb_id=args.kb_id,
                retriever_config_path=args.retriever_config,
                collection_name=args.collection_name,
                display_name=args.display_name,
                source_root=args.source_root,
                index_uri=args.index_uri,
            )
        if args.command == "ingest-path":
            return await admin.ingest_path(
                kb_id=args.kb_id,
                path=args.path,
                sync_deletions=args.sync_deletions,
                force=args.force,
                prefer_mineru=args.prefer_mineru,
                chunk_backend=args.chunk_backend,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
        if args.command == "delete-document":
            return await admin.delete_document(
                kb_id=args.kb_id,
                source_uri=args.source_uri,
            )
        if args.command == "rebuild-kb":
            return await admin.rebuild_kb(kb_id=args.kb_id)
        if args.command == "retry-task":
            return await admin.retry_task(args.task_id)
        if args.command == "list-documents":
            return {
                "items": admin.store.list_documents(
                    args.kb_id,
                    include_deleted=args.include_deleted,
                )
            }
        if args.command == "list-tasks":
            return {"items": admin.store.list_tasks(kb_id=args.kb_id, limit=args.limit)}
        if args.command == "list-kbs":
            return {"items": admin.store.list_kbs()}
        raise RuntimeError(f"Unsupported command: {args.command}")
    finally:
        admin.close()


def main() -> None:
    args = parse_args()
    result = asyncio.run(run_command(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


__all__ = ["main", "parse_args", "run_command"]


if __name__ == "__main__":
    main()
