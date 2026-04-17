from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Dict, Iterable, List

from bizrag.service.kb_admin import KBAdmin
from bizrag.service.retrieve_api import RustFSEventRequest, enqueue_rustfs_event


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BizRAG RustFS MQ bridge")
    parser.add_argument(
        "--backend",
        choices=("kafka", "rabbitmq"),
        required=True,
        help="MQ backend type",
    )
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
        "--max-events-per-message",
        type=int,
        default=100,
        help="Safety cap when a single MQ message contains a batch of RustFS events",
    )

    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--topic", default="bizrag.rustfs.events")
    parser.add_argument("--group-id", default="bizrag-rustfs-bridge")
    parser.add_argument("--auto-offset-reset", default="earliest")

    parser.add_argument("--amqp-url", default="amqp://guest:guest@127.0.0.1/")
    parser.add_argument("--queue", default="bizrag.rustfs.events")
    parser.add_argument("--prefetch-count", type=int, default=20)

    return parser.parse_args()


def _normalize_message_events(payload: Any, max_events_per_message: int) -> List[RustFSEventRequest]:
    events_payload: Iterable[Any]
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        events_payload = payload["events"]
    elif isinstance(payload, list):
        events_payload = payload
    else:
        events_payload = [payload]

    normalized: List[RustFSEventRequest] = []
    for idx, item in enumerate(events_payload):
        if idx >= max_events_per_message:
            raise RuntimeError(
                f"MQ message contains more than {max_events_per_message} RustFS events"
            )
        if not isinstance(item, dict):
            raise RuntimeError("RustFS MQ message item must be a JSON object")
        normalized.append(RustFSEventRequest(**item))
    return normalized


def enqueue_message(
    *,
    admin: KBAdmin,
    raw_message: bytes,
    max_events_per_message: int,
) -> Dict[str, Any]:
    try:
        payload = json.loads(raw_message.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid MQ message JSON: {exc}") from exc

    events = _normalize_message_events(payload, max_events_per_message)
    results = [
        enqueue_rustfs_event(
            admin=admin,
            req=event,
            x_rustfs_token=None,
            x_rustfs_timestamp=None,
            x_rustfs_signature=None,
        )
        for event in events
    ]
    return {
        "queued": len(results),
        "items": results,
    }


async def run_kafka_bridge(args: argparse.Namespace) -> None:
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError as exc:
        raise RuntimeError(
            "Kafka bridge requires aiokafka. Install with `pip install aiokafka` "
            "or `pip install .[mq]`."
        ) from exc

    admin = KBAdmin(
        metadata_db=args.metadata_db,
        kb_registry_path=args.kb_registry,
        workspace_root=args.workspace_root,
    )
    consumer = AIOKafkaConsumer(
        args.topic,
        bootstrap_servers=args.bootstrap_servers,
        group_id=args.group_id,
        enable_auto_commit=False,
        auto_offset_reset=args.auto_offset_reset,
    )
    await consumer.start()
    try:
        async for message in consumer:
            try:
                result = enqueue_message(
                    admin=admin,
                    raw_message=bytes(message.value),
                    max_events_per_message=max(1, int(args.max_events_per_message)),
                )
                print(json.dumps({"backend": "kafka", **result}, ensure_ascii=False))
                await consumer.commit()
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "backend": "kafka",
                            "status": "failed",
                            "topic": message.topic,
                            "partition": message.partition,
                            "offset": message.offset,
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    )
                )
    finally:
        await consumer.stop()
        admin.close()


async def run_rabbitmq_bridge(args: argparse.Namespace) -> None:
    try:
        import aio_pika
    except ImportError as exc:
        raise RuntimeError(
            "RabbitMQ bridge requires aio-pika. Install with `pip install aio-pika` "
            "or `pip install .[mq]`."
        ) from exc

    admin = KBAdmin(
        metadata_db=args.metadata_db,
        kb_registry_path=args.kb_registry,
        workspace_root=args.workspace_root,
    )
    connection = await aio_pika.connect_robust(args.amqp_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=max(1, int(args.prefetch_count)))
    queue = await channel.declare_queue(args.queue, durable=True)
    try:
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process(requeue=True):
                    result = enqueue_message(
                        admin=admin,
                        raw_message=bytes(message.body),
                        max_events_per_message=max(1, int(args.max_events_per_message)),
                    )
                    print(json.dumps({"backend": "rabbitmq", **result}, ensure_ascii=False))
    finally:
        await channel.close()
        await connection.close()
        admin.close()


async def main() -> None:
    args = parse_args()
    if args.backend == "kafka":
        await run_kafka_bridge(args)
        return
    if args.backend == "rabbitmq":
        await run_rabbitmq_bridge(args)
        return
    raise RuntimeError(f"Unsupported backend: {args.backend}")


if __name__ == "__main__":
    asyncio.run(main())
