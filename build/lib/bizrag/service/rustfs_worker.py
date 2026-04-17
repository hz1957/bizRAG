from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Dict

from bizrag.service.kb_admin import KBAdmin
from bizrag.service.retrieve_api import RustFSEventRequest, _handle_rustfs_event_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BizRAG RustFS event worker")
    parser.add_argument(
        "--metadata-db",
        type=str,
        default="bizrag/state/metadata.db",
        help="SQLite metadata store path",
    )
    parser.add_argument(
        "--kb-registry",
        type=str,
        default="bizrag/config/kb_registry.yaml",
        help="KB registry yaml used by retrieve_api",
    )
    parser.add_argument(
        "--workspace-root",
        type=str,
        default="runtime/kbs",
        help="Workspace root for corpus/chunk/index artifacts",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds to wait when queue is empty",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Maximum queued events to claim per polling cycle",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one claim cycle and exit",
    )
    return parser.parse_args()


async def process_claimed_event(admin: KBAdmin, event: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(event.get("payload_json") or {})
    payload["event_id"] = str(event["event_id"])
    try:
        req = RustFSEventRequest(**payload)
    except Exception as exc:
        admin.store.update_rustfs_event(
            str(event["event_id"]),
            status="failed",
            error_message=f"Invalid queued payload: {exc}",
        )
        raise RuntimeError(f"Invalid queued payload for event {event['event_id']}: {exc}") from exc

    return await _handle_rustfs_event_request(
        admin=admin,
        req=req,
        x_rustfs_token=None,
        x_rustfs_timestamp=None,
        x_rustfs_signature=None,
        verify_headers=False,
    )


async def run_worker(args: argparse.Namespace) -> None:
    admin = KBAdmin(
        metadata_db=args.metadata_db,
        kb_registry_path=args.kb_registry,
        workspace_root=args.workspace_root,
    )
    try:
        while True:
            claimed = admin.store.claim_rustfs_events(limit=max(1, int(args.batch_size)))
            if not claimed:
                if args.once:
                    return
                await asyncio.sleep(max(0.2, float(args.poll_interval)))
                continue

            for event in claimed:
                try:
                    result = await process_claimed_event(admin, event)
                    print(json.dumps({"status": "success", **result}, ensure_ascii=False))
                except Exception as exc:
                    print(
                        json.dumps(
                            {
                                "status": "failed",
                                "event_id": event.get("event_id"),
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        )
                    )

            if args.once:
                return
    finally:
        admin.close()


if __name__ == "__main__":
    asyncio.run(run_worker(parse_args()))
