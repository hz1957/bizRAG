from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping

from bizrag.service.app.kb_config import resolve_kb_server_parameters
from bizrag.service.ultrarag.server_parameters import (
    default_server_parameters,
    extract_override_dict,
)

_RETRIEVER_LOCAL_FIELDS = (
    "model_name_or_path",
    "backend_configs",
    "batch_size",
    "corpus_path",
    "gpu_ids",
    "is_multimodal",
    "backend",
    "index_backend",
    "index_backend_configs",
    "is_demo",
    "collection_name",
)
_RERANKER_LOCAL_FIELDS = (
    "model_name_or_path",
    "backend_configs",
    "batch_size",
    "gpu_ids",
    "backend",
)
_GENERATION_LOCAL_FIELDS = (
    "backend",
    "backend_configs",
    "sampling_params",
    "extra_params",
    "system_prompt",
)


def _pick_local_fields(cfg: Mapping[str, Any], field_names: tuple[str, ...]) -> Dict[str, Any]:
    return {
        field_name: deepcopy(cfg[field_name])
        for field_name in field_names
        if field_name in cfg
    }


def build_read_pipeline_payload(
    *,
    kb: Mapping[str, Any],
    query: str,
    top_k: int,
    query_instruction: str = "",
    filters: Dict[str, Any] | None = None,
    output_fields: list[str] | None = None,
    system_prompt: str = "",
) -> Dict[str, Any]:
    defaults = default_server_parameters()
    profile = resolve_kb_server_parameters(kb=kb)
    retriever_cfg = deepcopy(profile.get("retriever") or {})
    reranker_cfg = deepcopy(profile.get("reranker") or {})
    merge_cfg = deepcopy(profile.get("merge") or {})
    generation_cfg = deepcopy(profile.get("generation") or {})

    try:
        requested_top_k = int(top_k)
    except (TypeError, ValueError):
        requested_top_k = 5
    if requested_top_k <= 0:
        requested_top_k = 5

    try:
        default_top_k = int(retriever_cfg.get("top_k") or requested_top_k)
    except (TypeError, ValueError):
        default_top_k = requested_top_k
    if default_top_k <= 0:
        default_top_k = requested_top_k

    normalized_filters = dict(filters or {})
    normalized_output_fields = list(output_fields or [])

    dense_cfg = _pick_local_fields(retriever_cfg, _RETRIEVER_LOCAL_FIELDS)
    sparse_cfg = deepcopy(dense_cfg)
    sparse_cfg["backend"] = "bm25"

    payload: Dict[str, Any] = {}

    custom_target = {
        "query": query,
        "top_k": requested_top_k,
        "query_instruction": str(query_instruction or ""),
        "filters": normalized_filters,
        "output_fields": normalized_output_fields,
        "retriever_top_k": default_top_k,
        "retriever_query_instruction": str(
            retriever_cfg.get("query_instruction") or ""
        ),
        "strategy": merge_cfg.get("strategy", "rrf"),
        "rrf_k": merge_cfg.get("rrf_k", 60),
        "primary_weight": merge_cfg.get("primary_weight", 1.0),
        "secondary_weight": merge_cfg.get("secondary_weight", 1.0),
    }
    custom_override = extract_override_dict(defaults.get("merge") or {}, custom_target)
    if isinstance(custom_override, dict) and custom_override:
        payload["custom"] = custom_override

    dense_override = extract_override_dict(
        _pick_local_fields(defaults.get("retriever") or {}, _RETRIEVER_LOCAL_FIELDS),
        dense_cfg,
    )
    if isinstance(dense_override, dict) and dense_override:
        payload["dense"] = dense_override

    sparse_override = extract_override_dict(
        _pick_local_fields(defaults.get("retriever") or {}, _RETRIEVER_LOCAL_FIELDS),
        sparse_cfg,
    )
    if isinstance(sparse_override, dict) and sparse_override:
        payload["sparse"] = sparse_override

    if reranker_cfg:
        reranker_override = extract_override_dict(
            _pick_local_fields(defaults.get("reranker") or {}, _RERANKER_LOCAL_FIELDS),
            _pick_local_fields(reranker_cfg, _RERANKER_LOCAL_FIELDS),
        )
        if isinstance(reranker_override, dict) and reranker_override:
            payload["reranker"] = reranker_override

    generation_target = _pick_local_fields(generation_cfg, _GENERATION_LOCAL_FIELDS)
    if generation_target or system_prompt:
        generation_target["system_prompt"] = str(
            system_prompt or generation_cfg.get("system_prompt", "")
        )
        generation_override = extract_override_dict(
            _pick_local_fields(defaults.get("generation") or {}, _GENERATION_LOCAL_FIELDS),
            generation_target,
        )
        if isinstance(generation_override, dict) and generation_override:
            payload["generation"] = generation_override
    return payload
