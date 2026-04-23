from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from typing import Any, Dict

from bizrag.common.observability import observe_operation
from bizrag.contracts.schemas import RustFSEventRequest
from bizrag.service.app.kb_admin import KBAdmin
from bizrag.service.app.rustfs_events import handle_rustfs_event_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BizRAG RustFS event worker")
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
    parser.add_argument(
        "--worker-id",
        type=str,
        default="",
        help="Stable worker identifier for event leases",
    )
    parser.add_argument(
        "--lease-seconds",
        type=float,
        default=45.0,
        help="RustFS event lease length in seconds",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=15.0,
        help="Heartbeat interval while an event is being processed",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum retries before an expired event is marked failed",
    )
    parser.add_argument(
        "--task-timeout-seconds",
        type=float,
        default=120.0,
        help="Cancel running KB tasks if their heartbeat stops for this long",
    )
    return parser.parse_args()


async def process_claimed_event(
    admin: KBAdmin,
    event: Dict[str, Any],
    *,
    worker_id: str,
    lease_seconds: float,
    heartbeat_interval: float,
) -> Dict[str, Any]:
    payload = dict(event.get("payload_json") or {})
    payload["event_id"] = str(event["event_id"])
    try:
        req = RustFSEventRequest(**payload)
    except Exception as exc:
        admin.store.finish_rustfs_event(
            str(event["event_id"]),
            status="failed",
            error_message=f"Invalid queued payload: {exc}",
        )
        raise RuntimeError(f"Invalid queued payload for event {event['event_id']}: {exc}") from exc

    async def _run_admin_async(method_name: str, **kwargs: Any) -> Any:
        def _runner() -> Any:
            temp_admin = KBAdmin(
                metadata_db=admin.store.db_path,
                workspace_root=admin.workspace_root,
            )
            try:
                method = getattr(temp_admin, method_name)
                return asyncio.run(method(**kwargs))
            finally:
                temp_admin.close()

        return await asyncio.to_thread(_runner)

    async with observe_operation(
        store=admin.store,
        component="worker",
        operation="process_claimed_event",
        kb_id=str(event.get("kb_id") or req.kb_id),
        event_id=str(event.get("event_id") or req.event_id or ""),
        source_uri=str(event.get("source_uri") or req.source_uri or ""),
        details={"event_type": req.event_type},
    ):
        return await handle_rustfs_event_request(
            admin=admin,
            req=req,
            run_admin_async=_run_admin_async,
            x_rustfs_token=None,
            x_rustfs_timestamp=None,
            x_rustfs_signature=None,
            verify_headers=False,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_interval_seconds=heartbeat_interval,
            start_processing=False,
        )


async def run_worker(args: argparse.Namespace) -> None:
    admin = KBAdmin(
        metadata_db=args.metadata_db,
        workspace_root=args.workspace_root,
    )
    worker_id = str(args.worker_id or f"{socket.gethostname()}:{os.getpid()}")
    try:
        while True:
            admin.store.reconcile_runtime_state(
                task_timeout_seconds=max(5.0, float(args.task_timeout_seconds)),
                event_lease_seconds=max(5.0, float(args.lease_seconds)),
                event_max_attempts=max(1, int(args.max_attempts)),
            )
            claimed = admin.store.claim_rustfs_events(
                limit=max(1, int(args.batch_size)),
                worker_id=worker_id,
                lease_seconds=max(5.0, float(args.lease_seconds)),
            )
            if not claimed:
                if args.once:
                    return
                await asyncio.sleep(max(0.2, float(args.poll_interval)))
                continue

            for event in claimed:
                try:
                    result = await process_claimed_event(
                        admin,
                        event,
                        worker_id=worker_id,
                        lease_seconds=max(5.0, float(args.lease_seconds)),
                        heartbeat_interval=max(1.0, float(args.heartbeat_interval)),
                    )
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


def main() -> None:
    asyncio.run(run_worker(parse_args()))


if __name__ == "__main__":
    main()
