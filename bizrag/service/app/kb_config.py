from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from bizrag.service.app.kb_artifacts import combined_paths
from bizrag.service.ultrarag.server_parameters import (
    deep_merge_dicts,
    merge_with_default_server_parameters,
    load_server_parameters,
)

LEGACY_MINICPM_EMBEDDING_MODEL = "openbmb/MiniCPM-Embedding-Light"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"
DEFAULT_RUNTIME_ACCELERATOR = "auto"


def _runtime_accelerator_mode() -> str:
    raw = str(os.getenv("BIZRAG_ACCELERATOR", DEFAULT_RUNTIME_ACCELERATOR) or DEFAULT_RUNTIME_ACCELERATOR)
    mode = raw.strip().lower()
    if mode not in {"auto", "cpu", "cuda"}:
        raise RuntimeError(
            f"Unsupported BIZRAG_ACCELERATOR={raw!r}. Expected one of: auto, cpu, cuda."
        )
    return mode


def _runtime_gpu_ids() -> Optional[str]:
    raw = os.getenv("BIZRAG_GPU_IDS")
    if raw is None:
        return None
    normalized = raw.strip()
    return normalized or None


def _canonicalize_hf_model_name_or_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value
    if value.startswith("models--") and "/" not in value:
        cache_ref = value[len("models--") :]
        if "--" in cache_ref:
            org, repo = cache_ref.split("--", 1)
            if org and repo:
                normalized = f"{org}/{repo}"
    if normalized == LEGACY_MINICPM_EMBEDDING_MODEL:
        return DEFAULT_EMBEDDING_MODEL
    return normalized


def _apply_runtime_accelerator_profile(materialized: Dict[str, Any]) -> None:
    mode = _runtime_accelerator_mode()
    gpu_ids = _runtime_gpu_ids()

    retriever_cfg = deepcopy(materialized.get("retriever") or {})
    reranker_cfg = deepcopy(materialized.get("reranker") or {})

    if mode == "cpu":
        retriever_cfg["gpu_ids"] = None
        retriever_cfg["retriever_gpu_ids"] = None
        if reranker_cfg:
            reranker_cfg["gpu_ids"] = None
            reranker_cfg.setdefault("backend_configs", {})
            reranker_cfg["backend_configs"].setdefault("sentence_transformers", {})
            reranker_cfg["backend_configs"]["sentence_transformers"]["device"] = "cpu"
            reranker_cfg["backend_configs"].setdefault("infinity", {})
            reranker_cfg["backend_configs"]["infinity"]["device"] = "cpu"
    elif mode == "cuda":
        if gpu_ids is None:
            raise RuntimeError(
                "BIZRAG_ACCELERATOR=cuda requires BIZRAG_GPU_IDS to be set."
            )
        retriever_cfg["gpu_ids"] = gpu_ids
        retriever_cfg["retriever_gpu_ids"] = gpu_ids
        if reranker_cfg:
            reranker_cfg["gpu_ids"] = gpu_ids
            reranker_cfg.setdefault("backend_configs", {})
            reranker_cfg["backend_configs"].setdefault("sentence_transformers", {})
            reranker_cfg["backend_configs"]["sentence_transformers"]["device"] = "cuda"
            reranker_cfg["backend_configs"].setdefault("infinity", {})
            reranker_cfg["backend_configs"]["infinity"]["device"] = "cuda"

    materialized["retriever"] = retriever_cfg
    if reranker_cfg:
        materialized["reranker"] = reranker_cfg


def build_runtime_server_parameters(
    *,
    source_parameters: Dict[str, Any],
    workspace_dir: str | Path,
    collection_name: str,
    index_uri: str,
) -> Dict[str, Any]:
    profile = merge_with_default_server_parameters(source_parameters)
    paths = combined_paths({"workspace_dir": str(Path(workspace_dir).resolve())})

    materialized = deepcopy(profile)
    retriever_cfg = deepcopy(materialized.get("retriever") or {})
    retriever_cfg["model_name_or_path"] = _canonicalize_hf_model_name_or_path(
        retriever_cfg.get("model_name_or_path")
    )
    retriever_cfg["retriever_model_name_or_path"] = retriever_cfg["model_name_or_path"]
    retriever_cfg["corpus_path"] = str(paths["chunk"])
    retriever_cfg["embedding_path"] = str(paths["embedding"])
    retriever_cfg["collection_name"] = str(collection_name)
    retriever_cfg["index_backend"] = "milvus"
    retriever_cfg["retriever_index_backend"] = "milvus"

    retriever_cfg.setdefault("backend_configs", {})
    retriever_cfg["backend_configs"].setdefault("bm25", {})
    retriever_cfg["backend_configs"]["bm25"]["save_path"] = str(paths["bm25"])

    retriever_cfg.setdefault("index_backend_configs", {})
    retriever_cfg["index_backend_configs"].setdefault("faiss", {})
    retriever_cfg["index_backend_configs"]["faiss"]["index_path"] = str(
        paths["faiss_index"]
    )
    retriever_cfg["index_backend_configs"].setdefault("milvus", {})
    retriever_cfg["index_backend_configs"]["milvus"]["uri"] = str(index_uri)
    materialized["retriever"] = retriever_cfg

    reranker_cfg = deepcopy(materialized.get("reranker") or {})
    if reranker_cfg:
        reranker_cfg["model_name_or_path"] = _canonicalize_hf_model_name_or_path(
            reranker_cfg.get("model_name_or_path")
        )
        materialized["reranker"] = reranker_cfg

    _apply_runtime_accelerator_profile(materialized)

    return materialized


def _resolve_runtime_source_path(
    kb: Mapping[str, Any],
    *,
    source_parameters_path: str | Path | None = None,
) -> Path:
    configured_path = str(source_parameters_path or kb.get("source_parameters_path") or "").strip()
    if not configured_path:
        raise RuntimeError(
            f"KB {kb.get('kb_id')} is missing source_parameters_path."
        )
    return Path(configured_path).resolve()


def load_kb_source_server_parameters(
    *,
    kb: Mapping[str, Any],
    source_parameters_path: str | Path | None = None,
) -> Dict[str, Any]:
    source_path = _resolve_runtime_source_path(
        kb,
        source_parameters_path=source_parameters_path,
    )
    return load_server_parameters(source_path)


def resolve_kb_runtime_paths(*, kb: Mapping[str, Any]) -> Dict[str, str]:
    workspace_dir = str(Path(str(kb["workspace_dir"])).resolve())
    paths = combined_paths({"workspace_dir": workspace_dir})
    return {
        "workspace_dir": workspace_dir,
        "chunk_path": str(paths["chunk"]),
        "embedding_path": str(paths["embedding"]),
        "bm25_path": str(paths["bm25"]),
        "faiss_index_path": str(paths["faiss_index"]),
    }


def _resolve_kb_index_uri(
    *,
    kb: Mapping[str, Any],
    source_parameters: Mapping[str, Any],
) -> str:
    retriever_cfg = deepcopy(source_parameters.get("retriever") or {})
    milvus_cfg = retriever_cfg.get("index_backend_configs", {}).get("milvus", {})
    resolved_index_uri = kb.get("index_uri")
    if str(retriever_cfg.get("index_backend") or "").lower() == "milvus":
        resolved_index_uri = milvus_cfg.get("uri") or resolved_index_uri
        if not resolved_index_uri:
            raise RuntimeError(
                f"KB {kb.get('kb_id')} uses milvus backend but retriever.index_backend_configs.milvus.uri is not configured"
            )
    return str(resolved_index_uri or "")


def resolve_kb_runtime_overrides(
    *,
    kb: Mapping[str, Any],
    source_parameters: Optional[Mapping[str, Any]] = None,
    source_parameters_path: str | Path | None = None,
) -> Dict[str, Dict[str, Any]]:
    resolved_source_parameters = deepcopy(
        source_parameters
        or load_kb_source_server_parameters(
            kb=kb,
            source_parameters_path=source_parameters_path,
        )
    )
    runtime_paths = resolve_kb_runtime_paths(kb=kb)
    resolved_index_uri = _resolve_kb_index_uri(
        kb=kb,
        source_parameters=resolved_source_parameters,
    )
    return {
        "retriever": {
            "corpus_path": runtime_paths["chunk_path"],
            "embedding_path": runtime_paths["embedding_path"],
            "collection_name": str(kb["collection_name"]),
            "index_backend": "milvus",
            "retriever_index_backend": "milvus",
            "backend_configs": {
                "bm25": {
                    "save_path": runtime_paths["bm25_path"],
                }
            },
            "index_backend_configs": {
                "faiss": {
                    "index_path": runtime_paths["faiss_index_path"],
                },
                "milvus": {
                    "uri": resolved_index_uri,
                },
            },
        }
    }


def resolve_kb_server_parameters(
    *,
    kb: Mapping[str, Any],
    source_parameters_path: str | Path | None = None,
) -> Dict[str, Any]:
    source_parameters = load_kb_source_server_parameters(
        kb=kb,
        source_parameters_path=source_parameters_path,
    )
    materialized = merge_with_default_server_parameters(source_parameters)
    runtime_overrides = resolve_kb_runtime_overrides(
        kb=kb,
        source_parameters=source_parameters,
    )

    retriever_cfg = deep_merge_dicts(
        deepcopy(materialized.get("retriever") or {}),
        deepcopy(runtime_overrides.get("retriever") or {}),
    )
    retriever_cfg["model_name_or_path"] = _canonicalize_hf_model_name_or_path(
        retriever_cfg.get("model_name_or_path")
    )
    retriever_cfg["retriever_model_name_or_path"] = retriever_cfg["model_name_or_path"]
    materialized["retriever"] = retriever_cfg

    reranker_cfg = deepcopy(materialized.get("reranker") or {})
    if reranker_cfg:
        reranker_cfg["model_name_or_path"] = _canonicalize_hf_model_name_or_path(
            reranker_cfg.get("model_name_or_path")
        )
        materialized["reranker"] = reranker_cfg

    _apply_runtime_accelerator_profile(materialized)
    return materialized


def resolve_kb_retriever_parameters(
    *,
    kb: Mapping[str, Any],
    source_parameters_path: str | Path | None = None,
) -> Dict[str, Any]:
    return deepcopy(
        resolve_kb_server_parameters(
            kb=kb,
            source_parameters_path=source_parameters_path,
        ).get("retriever")
        or {}
    )
