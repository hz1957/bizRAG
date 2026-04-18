from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from bizrag.common.io_utils import dump_yaml, load_yaml
from bizrag.service.app.kb_artifacts import combined_paths
from bizrag.service.ultrarag.server_parameters import (
    load_server_parameters,
    normalize_server_parameters,
)

MATERIALIZED_SERVER_PARAMETERS_FILE = Path("config/server_parameters.yaml")


def build_kb_server_parameters(
    *,
    source_parameters_path: str | Path,
    workspace_dir: str | Path,
    collection_name: str,
    index_uri: str,
) -> Dict[str, Any]:
    profile = load_server_parameters(source_parameters_path)
    paths = combined_paths({"workspace_dir": str(Path(workspace_dir).resolve())})

    retriever_cfg = deepcopy(profile.get("retriever") or {})
    retriever_cfg["corpus_path"] = str(paths["chunk"])
    retriever_cfg["embedding_path"] = str(paths["embedding"])
    retriever_cfg["collection_name"] = str(collection_name)

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

    materialized = deepcopy(profile)
    materialized["retriever"] = retriever_cfg
    return materialized


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
