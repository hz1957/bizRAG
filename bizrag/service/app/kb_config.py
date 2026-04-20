from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from typing import Any, Dict, Optional

from bizrag.common.io_utils import dump_yaml, load_yaml
from bizrag.service.app.kb_artifacts import combined_paths
from bizrag.service.ultrarag.server_parameters import (
    normalize_server_parameters,
    merge_with_default_server_parameters,
    load_server_parameters,
)

MATERIALIZED_SERVER_PARAMETERS_FILE = Path("config/server_parameters.yaml")
LEGACY_RETRIEVER_RUNTIME_FILE = Path("index/retriever_runtime.yaml")
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


def _build_materialized_server_parameters(
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


def build_kb_server_parameters(
    *,
    source_parameters_path: str | Path,
    workspace_dir: str | Path,
    collection_name: str,
    index_uri: str,
) -> Dict[str, Any]:
    return _build_materialized_server_parameters(
        source_parameters=load_server_parameters(source_parameters_path),
        workspace_dir=workspace_dir,
        collection_name=collection_name,
        index_uri=index_uri,
    )


def materialize_kb_server_parameters(
    *,
    source_parameters_path: str | Path,
    workspace_dir: str | Path,
    collection_name: str,
    index_uri: str,
) -> Path:
    workspace_path = Path(workspace_dir).resolve()
    config_path = workspace_path / MATERIALIZED_SERVER_PARAMETERS_FILE
    dump_yaml(
        config_path,
        build_kb_server_parameters(
            source_parameters_path=source_parameters_path,
            workspace_dir=workspace_path,
            collection_name=collection_name,
            index_uri=index_uri,
        ),
    )
    return config_path


def load_kb_server_parameters(path: str | Path) -> Dict[str, Any]:
    return normalize_server_parameters(load_yaml(path))


def load_kb_retriever_parameters(path: str | Path) -> Dict[str, Any]:
    return deepcopy(load_kb_server_parameters(path).get("retriever") or {})


def migrate_kb_server_parameters(
    *,
    kb: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    workspace_path = Path(str(kb["workspace_dir"])).resolve()
    materialized_path = workspace_path / MATERIALIZED_SERVER_PARAMETERS_FILE
    legacy_runtime_path = workspace_path / LEGACY_RETRIEVER_RUNTIME_FILE
    configured_path = Path(str(kb["retriever_config_path"]))

    source_path: Optional[Path] = None
    for candidate in (configured_path, legacy_runtime_path, materialized_path):
        if candidate.exists():
            source_path = candidate
            break
    if source_path is None:
        return None

    retriever_cfg = normalize_server_parameters(load_yaml(source_path)).get("retriever") or {}
    milvus_cfg = retriever_cfg.get("index_backend_configs", {}).get("milvus", {})
    resolved_index_uri = kb.get("index_uri")
    if str(retriever_cfg.get("index_backend") or "").lower() == "milvus":
        resolved_index_uri = milvus_cfg.get("uri") or resolved_index_uri
        if not resolved_index_uri:
            raise RuntimeError(
                f"KB {kb['kb_id']} uses milvus backend but retriever.index_backend_configs.milvus.uri is not configured"
            )
    resolved_index_uri = str(resolved_index_uri or "")
    materialized = _build_materialized_server_parameters(
        source_parameters=load_yaml(source_path),
        workspace_dir=workspace_path,
        collection_name=str(kb["collection_name"]),
        index_uri=resolved_index_uri,
    )
    dump_yaml(materialized_path, materialized)
    return {
        "kb_id": str(kb["kb_id"]),
        "collection_name": str(kb["collection_name"]),
        "display_name": kb.get("display_name"),
        "source_root": kb.get("source_root"),
        "workspace_dir": str(workspace_path),
        "retriever_config_path": str(materialized_path),
        "index_uri": resolved_index_uri,
    }
