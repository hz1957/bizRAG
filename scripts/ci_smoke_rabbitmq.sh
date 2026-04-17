#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
TMP_ROOT="${TMP_ROOT:-/tmp/bizrag_ci_smoke}"
QUEUE_NAME="${QUEUE_NAME:-bizrag.rustfs.ci}"
AMQP_URL="${AMQP_URL:-amqp://guest:guest@127.0.0.1/}"
RABBITMQ_HOST="${RABBITMQ_HOST:-127.0.0.1}"
RABBITMQ_PORT="${RABBITMQ_PORT:-5672}"

cd "$ROOT_DIR"

"$PYTHON_BIN" -m pip install -e '.[mq]'

MANAGE_RABBITMQ=0 \
PYTHON_BIN="$PYTHON_BIN" \
TMP_ROOT="$TMP_ROOT" \
QUEUE_NAME="$QUEUE_NAME" \
AMQP_URL="$AMQP_URL" \
RABBITMQ_HOST="$RABBITMQ_HOST" \
RABBITMQ_PORT="$RABBITMQ_PORT" \
WAIT_TIMEOUT_SECONDS=60 \
./scripts/rabbitmq_e2e.sh
