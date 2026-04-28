from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml


DEFAULT_CHUNK_BACKEND = "sentence"
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_TOKENIZER_OR_TOKEN_COUNTER = "character"
CORPUS_PARAMETER_PATH = Path(__file__).resolve().parents[1] / "servers" / "corpus" / "parameter.yaml"


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def load_corpus_parameter_defaults() -> Dict[str, Any]:
    try:
        payload = yaml.safe_load(CORPUS_PARAMETER_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        payload = {}

    chunk_backend = str(payload.get("chunk_backend") or DEFAULT_CHUNK_BACKEND)
    chunk_size = _safe_int(payload.get("chunk_size"), DEFAULT_CHUNK_SIZE)
    tokenizer = str(payload.get("tokenizer_or_token_counter") or DEFAULT_TOKENIZER_OR_TOKEN_COUNTER)
    backend_configs = deepcopy(payload.get("chunk_backend_configs") or {})
    chunk_overlap = _safe_int(
        (backend_configs.get(chunk_backend) or {}).get("chunk_overlap"),
        DEFAULT_CHUNK_OVERLAP,
    )
    return {
        "chunk_backend": chunk_backend,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "tokenizer_or_token_counter": tokenizer,
        "chunk_backend_configs": backend_configs,
    }


CORPUS_CHUNK_DEFAULTS = load_corpus_parameter_defaults()
DEFAULT_CHUNK_BACKEND = str(CORPUS_CHUNK_DEFAULTS["chunk_backend"])
DEFAULT_CHUNK_SIZE = int(CORPUS_CHUNK_DEFAULTS["chunk_size"])
DEFAULT_CHUNK_OVERLAP = int(CORPUS_CHUNK_DEFAULTS["chunk_overlap"])
DEFAULT_TOKENIZER_OR_TOKEN_COUNTER = str(CORPUS_CHUNK_DEFAULTS["tokenizer_or_token_counter"])


def current_chunk_settings() -> Dict[str, Any]:
    return {
        "chunk_backend": DEFAULT_CHUNK_BACKEND,
        "chunk_size": DEFAULT_CHUNK_SIZE,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "tokenizer_or_token_counter": DEFAULT_TOKENIZER_OR_TOKEN_COUNTER,
    }


def build_chunk_pipeline_overrides(
    *,
    raw_chunk_path: str,
    chunk_path: str,
    use_title: bool,
    chunk_settings: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    settings = deepcopy(chunk_settings or current_chunk_settings())
    backend_configs = deepcopy(CORPUS_CHUNK_DEFAULTS["chunk_backend_configs"])
    for backend_name in ("token", "sentence"):
        cfg = backend_configs.setdefault(backend_name, {})
        cfg["chunk_overlap"] = int(settings["chunk_overlap"])
    return {
        "raw_chunk_path": raw_chunk_path,
        "chunk_path": chunk_path,
        "chunk_backend": settings["chunk_backend"],
        "chunk_size": int(settings["chunk_size"]),
        "use_title": bool(use_title),
        "tokenizer_or_token_counter": settings["tokenizer_or_token_counter"],
        "chunk_backend_configs": backend_configs,
    }
