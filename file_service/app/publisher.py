from __future__ import annotations

import asyncio
import json
from urllib.request import Request, urlopen

from .config import Settings
from .db import MetadataStore, OutboxRecord


class OutboxPublisher:
    def __init__(self, settings: Settings, store: MetadataStore) -> None:
        self._settings = settings
        self._store = store
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        while not self._stop:
            events = self._store.claim_outbox_events(
                limit=self._settings.outbox_batch_size,
                max_retry=self._settings.max_retry,
            )
            if not events:
                await asyncio.sleep(self._settings.outbox_poll_interval_seconds)
                continue
            if self._settings.publisher_backend == "http":
                await self._run_http(events)
            else:
                await self._run_rabbitmq(events)

    async def _run_http(self, events: list[OutboxRecord]) -> None:
        url = self._settings.http_bridge_url
        if not url:
            for event in events:
                self._store.mark_outbox_failed(event.event_id, "http bridge url not configured")
            return
        payload = {"events": [event.payload for event in events]}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url=url.rstrip("/") + "/api/v1/events/rustfs/queue/batch",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self._settings.http_bridge_timeout_seconds) as response:
                if 200 <= response.getcode() < 300:
                    for event in events:
                        self._store.mark_outbox_success(event.event_id)
                else:
                    body = response.read().decode("utf-8", errors="ignore")
                    raise RuntimeError(f"HTTP {response.getcode()}: {body}")
        except Exception as exc:
            for event in events:
                self._store.mark_outbox_failed(event.event_id, str(exc))

    async def _run_rabbitmq(self, events: list[OutboxRecord]) -> None:
        try:
            import aio_pika  # type: ignore
        except Exception as exc:
            for event in events:
                self._store.mark_outbox_failed(event.event_id, f"missing aio-pika: {exc}")
            await asyncio.sleep(self._settings.outbox_poll_interval_seconds)
            return

        try:
            connection = await aio_pika.connect_robust(self._settings.rabbitmq_url)
            async with connection:
                channel = await connection.channel()
                queue_name = self._settings.rabbitmq_queue
                await channel.declare_queue(queue_name, durable=True)
                for event in events:
                    try:
                        await channel.default_exchange.publish(
                            aio_pika.Message(
                                body=json.dumps(event.payload, ensure_ascii=False).encode("utf-8"),
                                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            ),
                            routing_key=queue_name,
                        )
                        self._store.mark_outbox_success(event.event_id)
                    except Exception as exc:
                        self._store.mark_outbox_failed(event.event_id, str(exc))
        except Exception as exc:
            for event in events:
                self._store.mark_outbox_failed(event.event_id, str(exc))
