from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Optional

from bizrag.common.io_utils import load_yaml
from bizrag.service.app.kb_config import build_runtime_server_parameters
from bizrag.service.ultrarag.server_parameters import load_server_parameters

LEGACY_SOURCE_PARAMETER_FILENAMES = {
    "server_parameters.yaml",
    "retriever_runtime.yaml",
}
LEGACY_SOURCE_PARAMETER_RELATIVE_PATHS = (
    Path("config/server_parameters.yaml"),
    Path("index/retriever_runtime.yaml"),
)
LEGACY_DEFAULT_OUTPUT_FIELDS = [
    "doc_id",
    "title",
    "file_name",
    "source_type",
    "sheet_name",
    "row_index",
    "kb_id",
    "doc_version",
    "source_uri",
]


def builtin_source_parameter_candidates() -> list[Path]:
    retriever_dir = Path(__file__).resolve().parents[1] / "servers" / "retriever"
    return sorted(retriever_dir.glob("parameter*.yaml"))


def _preferred_source_parameter_names(*, workspace_dir: Path) -> list[str]:
    workspace = str(workspace_dir)
    if workspace.startswith("/app/"):
        return ["parameter.docker.yaml", "parameter.yaml", "parameter.local.yaml"]
    return ["parameter.local.yaml", "parameter.yaml", "parameter.docker.yaml"]


def _normalize_runtime_profile_for_match(data: Any, *, workspace_dir: Path) -> Any:
    workspace = str(workspace_dir.resolve())

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_walk(item) for item in value]
        if isinstance(value, str) and workspace and value.startswith(workspace):
            return value.replace(workspace, "${WORKSPACE}", 1)
        return value

    normalized = _walk(data)
    if not isinstance(normalized, dict):
        return normalized

    merge_cfg = normalized.get("merge")
    if isinstance(merge_cfg, dict):
        merge_cfg.pop("retrieval_top_k", None)
        merge_cfg.pop("reranker_top_k", None)

    retriever_cfg = normalized.get("retriever")
    if isinstance(retriever_cfg, dict):
        output_fields = retriever_cfg.get("output_fields")
        if output_fields == LEGACY_DEFAULT_OUTPUT_FIELDS:
            retriever_cfg["output_fields"] = []

    return normalized


def _detect_materialized_workspace_dir(
    materialized: Mapping[str, Any],
    *,
    fallback: Path,
) -> Path:
    candidates = [
        ("retriever", "corpus_path", "combined/chunks.jsonl"),
        ("retriever", "embedding_path", "index/embeddings.npy"),
        ("retriever", "backend_configs", "bm25", "save_path", "index/bm25"),
        ("retriever", "index_backend_configs", "faiss", "index_path", "index/index.index"),
    ]

    for candidate in candidates:
        suffix = candidate[-1]
        value: Any = materialized
        for key in candidate[:-1]:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.replace("\\", "/")
        if normalized.endswith(suffix):
            root = normalized[: -len(suffix)].rstrip("/")
            if root:
                return Path(root)
    return fallback


def infer_source_parameters_path_from_legacy_runtime(
    *,
    kb: Mapping[str, Any],
    current_source_parameters_path: str | Path,
    candidate_paths: Optional[list[Path]] = None,
) -> Optional[Path]:
    current_path = Path(str(current_source_parameters_path)).resolve()
    if current_path.name not in LEGACY_SOURCE_PARAMETER_FILENAMES:
        return None
    if not current_path.is_file():
        return None

    materialized = load_yaml(current_path)
    legacy_workspace_dir = _detect_materialized_workspace_dir(
        materialized,
        fallback=current_path.parent.parent,
    )
    retriever_cfg = deepcopy(materialized.get("retriever") or {})
    milvus_cfg = retriever_cfg.get("index_backend_configs", {}).get("milvus", {})
    resolved_index_uri = kb.get("index_uri") or milvus_cfg.get("uri") or ""
    candidates = candidate_paths or builtin_source_parameter_candidates()
    matches: list[Path] = []
    normalized_materialized = _normalize_runtime_profile_for_match(
        materialized,
        workspace_dir=legacy_workspace_dir,
    )

    for candidate_path in candidates:
        candidate = candidate_path.resolve()
        try:
            built = build_runtime_server_parameters(
                source_parameters=load_server_parameters(candidate),
                workspace_dir=str(kb["workspace_dir"]),
                collection_name=str(kb["collection_name"]),
                index_uri=str(resolved_index_uri),
            )
        except Exception:
            continue
        normalized_built = _normalize_runtime_profile_for_match(
            built,
            workspace_dir=Path(str(kb["workspace_dir"])),
        )
        if normalized_built == normalized_materialized:
            matches.append(candidate)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        for preferred_name in _preferred_source_parameter_names(
            workspace_dir=Path(str(kb["workspace_dir"])),
        ):
            for candidate in matches:
                if candidate.name == preferred_name:
                    return candidate
    return None


def candidate_legacy_source_parameter_paths(workspace_dir: str | Path) -> list[Path]:
    root = Path(str(workspace_dir)).resolve()
    return [root / rel_path for rel_path in LEGACY_SOURCE_PARAMETER_RELATIVE_PATHS]
