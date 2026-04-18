#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
TMP_ROOT="${TMP_ROOT:-/tmp/bizrag_mq_e2e}"
QUEUE_NAME="${QUEUE_NAME:-bizrag.rustfs.e2e}"
RABBIT_CONTAINER="${RABBIT_CONTAINER:-bizrag-rabbitmq}"
KEEP_RABBITMQ="${KEEP_RABBITMQ:-0}"
MANAGE_RABBITMQ="${MANAGE_RABBITMQ:-1}"
AMQP_URL="${AMQP_URL:-amqp://guest:guest@127.0.0.1/}"
RABBITMQ_HOST="${RABBITMQ_HOST:-127.0.0.1}"
RABBITMQ_PORT="${RABBITMQ_PORT:-5672}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-60}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "python not found: $PYTHON_BIN" >&2
  exit 1
fi

mkdir -p "$TMP_ROOT"

wait_for_rabbitmq() {
  "$PYTHON_BIN" - <<'PY'
import os
import socket
import time

host = os.environ["RABBITMQ_HOST"]
port = int(os.environ["RABBITMQ_PORT"])
deadline = time.time() + int(os.environ["WAIT_TIMEOUT_SECONDS"])
while time.time() < deadline:
    sock = socket.socket()
    sock.settimeout(1)
    try:
        sock.connect((host, port))
        raise SystemExit(0)
    except OSError:
        time.sleep(1)
    finally:
        sock.close()
raise SystemExit(f"Timed out waiting for RabbitMQ at {host}:{port}")
PY
}

started_container=0
bridge_pid=""
worker_pid=""

cleanup() {
  if [[ -n "$bridge_pid" ]] && kill -0 "$bridge_pid" 2>/dev/null; then
    kill "$bridge_pid" 2>/dev/null || true
    wait "$bridge_pid" 2>/dev/null || true
  fi
  if [[ -n "$worker_pid" ]] && kill -0 "$worker_pid" 2>/dev/null; then
    kill "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
  fi
  if [[ "$started_container" == "1" ]] && [[ "$KEEP_RABBITMQ" != "1" ]]; then
    docker rm -f "$RABBIT_CONTAINER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "$MANAGE_RABBITMQ" == "1" ]]; then
  if ! docker ps --format '{{.Names}}' | grep -qx "$RABBIT_CONTAINER"; then
    if docker ps -a --format '{{.Names}}' | grep -qx "$RABBIT_CONTAINER"; then
      docker start "$RABBIT_CONTAINER" >/dev/null
    else
      docker run -d --rm --name "$RABBIT_CONTAINER" -p "$RABBITMQ_PORT:5672" rabbitmq:3.13-alpine >/dev/null
      started_container=1
    fi
  fi
fi

echo "Waiting for RabbitMQ at $RABBITMQ_HOST:$RABBITMQ_PORT ..."
RABBITMQ_HOST="$RABBITMQ_HOST" RABBITMQ_PORT="$RABBITMQ_PORT" WAIT_TIMEOUT_SECONDS="$WAIT_TIMEOUT_SECONDS" wait_for_rabbitmq

echo "Registering temporary KB..."
"$PYTHON_BIN" -m bizrag.entrypoints.kb_admin_cli \
  --metadata-db "$TMP_ROOT/metadata.db" \
  --workspace-root "$TMP_ROOT/runtime" \
  register-kb \
  --kb-id mq_e2e \
  --retriever-config "$ROOT_DIR/bizrag/servers/retriever/parameter.local.yaml" \
  --collection-name mq_e2e \
  --index-uri "$TMP_ROOT/runtime/mq_e2e/index/milvus_lite.db" >/dev/null

echo "Starting MQ bridge..."
"$PYTHON_BIN" -m bizrag.entrypoints.rustfs_mq_bridge_cli \
  --backend rabbitmq \
  --metadata-db "$TMP_ROOT/metadata.db" \
  --workspace-root "$TMP_ROOT/runtime" \
  --queue "$QUEUE_NAME" \
  --amqp-url "$AMQP_URL" >"$TMP_ROOT/bridge.log" 2>&1 &
bridge_pid=$!

echo "Starting worker..."
"$PYTHON_BIN" -m bizrag.entrypoints.rustfs_worker_cli \
  --metadata-db "$TMP_ROOT/metadata.db" \
  --workspace-root "$TMP_ROOT/runtime" \
  --poll-interval 1 \
  --batch-size 10 >"$TMP_ROOT/worker.log" 2>&1 &
worker_pid=$!

sleep 2

echo "Publishing RabbitMQ test message..."
QUEUE_NAME="$QUEUE_NAME" AMQP_URL="$AMQP_URL" "$PYTHON_BIN" - <<'PY'
import asyncio
import json
import os

import aio_pika

queue_name = os.environ["QUEUE_NAME"]
amqp_url = os.environ["AMQP_URL"]
payload = {
    "event_type": "document.created",
    "kb_id": "mq_e2e",
    "source_uri": "rustfs://mq-e2e/doc-1",
    "file_name": "doc-1.md",
    "payload_text": "# RabbitMQ E2E\n\nBizRAG scripted integration test document.\n\nPrice total is 12345.",
    "content_type": "text/markdown",
}

async def main() -> None:
    conn = await aio_pika.connect_robust(amqp_url)
    channel = await conn.channel()
    queue = await channel.declare_queue(queue_name, durable=True)
    await channel.default_exchange.publish(
        aio_pika.Message(
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=queue.name,
    )
    await channel.close()
    await conn.close()

asyncio.run(main())
PY

echo "Waiting for event success..."
QUEUE_NAME="$QUEUE_NAME" TMP_ROOT="$TMP_ROOT" WAIT_TIMEOUT_SECONDS="$WAIT_TIMEOUT_SECONDS" "$PYTHON_BIN" - <<'PY'
import os
import sqlite3
import time

db_path = os.path.join(os.environ["TMP_ROOT"], "metadata.db")
deadline = time.time() + int(os.environ["WAIT_TIMEOUT_SECONDS"])

while time.time() < deadline:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "select status, source_uri from rustfs_events order by created_at desc limit 1"
    ).fetchone()
    conn.close()
    if row and row[0] == "success":
        print({"status": row[0], "source_uri": row[1]})
        break
    time.sleep(1)
else:
    raise SystemExit("Timed out waiting for rustfs_events success")
PY

echo "Running retrieval verification..."
TMP_ROOT="$TMP_ROOT" "$PYTHON_BIN" - <<'PY'
import asyncio
import os

from bizrag.service.ultrarag.read_service import ReadService

async def main() -> None:
    read_service = ReadService(
        metadata_db=os.path.join(os.environ["TMP_ROOT"], "metadata.db"),
    )
    try:
        items = await read_service.retrieve_items(
            kb_id="mq_e2e",
            query="12345",
            top_k=1,
            query_instruction="",
            filters=None,
        )
        print(items[0].model_dump())
    finally:
        read_service.reset()

asyncio.run(main())
PY

echo "Logs:"
echo "  bridge: $TMP_ROOT/bridge.log"
echo "  worker: $TMP_ROOT/worker.log"
