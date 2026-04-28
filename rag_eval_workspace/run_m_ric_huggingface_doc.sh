#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE_DIR="$ROOT_DIR/rag_eval_workspace"

python "$ROOT_DIR/scripts/build_rag_eval_dataset.py" \
  --workspace-dir "$WORKSPACE_DIR" \
  --hf-dataset "m-ric/huggingface_doc" \
  --hf-split "train" \
  --hf-text-column "text" \
  --hf-source-column "source" \
  --provider "openai" \
  --base-url "http://127.0.0.1:11434/v1" \
  --model "mistral:latest" \
  --api-key "ollama" \
  --dataset-profile "production_v1" \
  --chunk-size 600 \
  --chunk-overlap 100 \
  --core-factoid-ratio 0.7 \
  --cross-sentence-ratio 0.2 \
  --unanswerable-ratio 0.1 \
  --ambiguous-rewrite-ratio 0.0 \
  --max-new-tokens 256 \
  --generations 1000 \
  "$@"
