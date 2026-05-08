#!/bin/sh
set -eu

APP_ROOT="${APP_ROOT:-/app}"
PYTHON_BIN="${PYTHON_BIN:-python}"

BIZRAG_METADATA_DB="${BIZRAG_METADATA_DB:-$APP_ROOT/bizrag/state/metadata.db}"
BIZRAG_WORKSPACE_ROOT="${BIZRAG_WORKSPACE_ROOT:-$APP_ROOT/runtime/kbs}"
BIZRAG_HOST="${BIZRAG_HOST:-0.0.0.0}"
BIZRAG_PORT="${BIZRAG_PORT:-64501}"

BIZRAG_RUSTFS_TOKEN="${BIZRAG_RUSTFS_TOKEN:-}"
BIZRAG_RUSTFS_SHARED_SECRET="${BIZRAG_RUSTFS_SHARED_SECRET:-}"
BIZRAG_HOT_RELOAD="${BIZRAG_HOT_RELOAD:-false}"

BIZRAG_RUN_API="${BIZRAG_RUN_API:-true}"
BIZRAG_RUN_WORKER="${BIZRAG_RUN_WORKER:-true}"
BIZRAG_RUN_MQ_BRIDGE="${BIZRAG_RUN_MQ_BRIDGE:-true}"

BIZRAG_MQ_BACKEND="${BIZRAG_MQ_BACKEND:-rabbitmq}"
BIZRAG_RABBITMQ_URL="${BIZRAG_RABBITMQ_URL:-amqp://guest:guest@rabbitmq:5672/}"
BIZRAG_RABBITMQ_QUEUE="${BIZRAG_RABBITMQ_QUEUE:-bizrag.rustfs.events}"
BIZRAG_RABBITMQ_PREFETCH="${BIZRAG_RABBITMQ_PREFETCH:-20}"

BIZRAG_KAFKA_BOOTSTRAP="${BIZRAG_KAFKA_BOOTSTRAP:-kafka:9092}"
BIZRAG_KAFKA_TOPIC="${BIZRAG_KAFKA_TOPIC:-bizrag.rustfs.events}"
BIZRAG_KAFKA_GROUP_ID="${BIZRAG_KAFKA_GROUP_ID:-bizrag-rustfs-bridge}"

BIZRAG_WORKER_POLL_INTERVAL="${BIZRAG_WORKER_POLL_INTERVAL:-2.0}"
BIZRAG_WORKER_BATCH_SIZE="${BIZRAG_WORKER_BATCH_SIZE:-10}"
BIZRAG_WORKER_LEASE_SECONDS="${BIZRAG_WORKER_LEASE_SECONDS:-45.0}"
BIZRAG_WORKER_HEARTBEAT_INTERVAL="${BIZRAG_WORKER_HEARTBEAT_INTERVAL:-15.0}"
BIZRAG_WORKER_MAX_ATTEMPTS="${BIZRAG_WORKER_MAX_ATTEMPTS:-3}"
BIZRAG_TASK_TIMEOUT_SECONDS="${BIZRAG_TASK_TIMEOUT_SECONDS:-120.0}"
BIZRAG_TASK_HEARTBEAT_INTERVAL_SECONDS="${BIZRAG_TASK_HEARTBEAT_INTERVAL_SECONDS:-5.0}"
BIZRAG_MAX_EVENTS_PER_MESSAGE="${BIZRAG_MAX_EVENTS_PER_MESSAGE:-100}"

BIZRAG_WAIT_FOR="${BIZRAG_WAIT_FOR:-mysql:3306,rabbitmq:5672,milvus:19530}"
BIZRAG_WAIT_TIMEOUT="${BIZRAG_WAIT_TIMEOUT:-60}"

wait_for_targets() {
  if [ -z "$BIZRAG_WAIT_FOR" ]; then
    return 0
  fi
  TARGETS="$BIZRAG_WAIT_FOR" WAIT_TIMEOUT="$BIZRAG_WAIT_TIMEOUT" "$PYTHON_BIN" -c '
import os, socket, sys, time
targets = [item.strip() for item in os.environ["TARGETS"].split(",") if item.strip()]
timeout = float(os.environ.get("WAIT_TIMEOUT", "60"))
deadline = time.time() + timeout
for target in targets:
    host, port = target.split(":", 1)
    port = int(port)
    while True:
        try:
            with socket.create_connection((host, port), timeout=2):
                break
        except OSError:
            if time.time() >= deadline:
                raise SystemExit(f"Timed out waiting for {host}:{port}")
            time.sleep(1)
'
}

mkdir -p "$BIZRAG_WORKSPACE_ROOT"
case "$BIZRAG_METADATA_DB" in
  *://*)
    ;;
  *)
    mkdir -p "$(dirname "$BIZRAG_METADATA_DB")"
    ;;
esac

"$PYTHON_BIN" "$APP_ROOT/docker/bootstrap_runtime.py"

wait_for_targets

if [ "$BIZRAG_HOT_RELOAD" = "true" ]; then
  exec "$PYTHON_BIN" "$APP_ROOT/docker/dev_hot_reload.py"
fi

pids=""

cleanup() {
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
  wait || true
}

trap cleanup INT TERM EXIT

if [ "$BIZRAG_RUN_MQ_BRIDGE" = "true" ] && [ "$BIZRAG_MQ_BACKEND" != "none" ]; then
  if [ "$BIZRAG_MQ_BACKEND" = "rabbitmq" ]; then
    "$PYTHON_BIN" -m bizrag.entrypoints.rustfs_mq_bridge_cli \
      --backend rabbitmq \
      --metadata-db "$BIZRAG_METADATA_DB" \
      --workspace-root "$BIZRAG_WORKSPACE_ROOT" \
      --amqp-url "$BIZRAG_RABBITMQ_URL" \
      --queue "$BIZRAG_RABBITMQ_QUEUE" \
      --prefetch-count "$BIZRAG_RABBITMQ_PREFETCH" \
      --max-events-per-message "$BIZRAG_MAX_EVENTS_PER_MESSAGE" &
  else
    "$PYTHON_BIN" -m bizrag.entrypoints.rustfs_mq_bridge_cli \
      --backend kafka \
      --metadata-db "$BIZRAG_METADATA_DB" \
      --workspace-root "$BIZRAG_WORKSPACE_ROOT" \
      --bootstrap-servers "$BIZRAG_KAFKA_BOOTSTRAP" \
      --topic "$BIZRAG_KAFKA_TOPIC" \
      --group-id "$BIZRAG_KAFKA_GROUP_ID" \
      --max-events-per-message "$BIZRAG_MAX_EVENTS_PER_MESSAGE" &
  fi
  pids="$pids $!"
fi

if [ "$BIZRAG_RUN_WORKER" = "true" ]; then
  "$PYTHON_BIN" -m bizrag.entrypoints.rustfs_worker_cli \
    --metadata-db "$BIZRAG_METADATA_DB" \
    --workspace-root "$BIZRAG_WORKSPACE_ROOT" \
    --poll-interval "$BIZRAG_WORKER_POLL_INTERVAL" \
    --batch-size "$BIZRAG_WORKER_BATCH_SIZE" \
    --lease-seconds "$BIZRAG_WORKER_LEASE_SECONDS" \
    --heartbeat-interval "$BIZRAG_WORKER_HEARTBEAT_INTERVAL" \
    --max-attempts "$BIZRAG_WORKER_MAX_ATTEMPTS" \
    --task-timeout-seconds "$BIZRAG_TASK_TIMEOUT_SECONDS" &
  pids="$pids $!"
fi

if [ "$BIZRAG_RUN_API" = "true" ]; then
  exec "$PYTHON_BIN" -m bizrag.entrypoints.api_http \
    --metadata-db "$BIZRAG_METADATA_DB" \
    --workspace-root "$BIZRAG_WORKSPACE_ROOT" \
    --rustfs-token "$BIZRAG_RUSTFS_TOKEN" \
    --rustfs-shared-secret "$BIZRAG_RUSTFS_SHARED_SECRET" \
    --host "$BIZRAG_HOST" \
    --port "$BIZRAG_PORT"
fi

wait
