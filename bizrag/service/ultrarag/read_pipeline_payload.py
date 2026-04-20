from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from bizrag.service.app.kb_config import load_kb_server_parameters


def build_read_pipeline_payload(
    *,
    server_parameters_path: str,
    query: str,
    top_k: int,
    query_instruction: str = "",
    filters: Dict[str, Any] | None = None,
    output_fields: list[str] | None = None,
    system_prompt: str = "",
) -> Dict[str, Any]:
    profile = load_kb_server_parameters(server_parameters_path)
    retriever_cfg = deepcopy(profile.get("retriever") or {})
    reranker_cfg = deepcopy(profile.get("reranker") or {})
    merge_cfg = deepcopy(profile.get("merge") or {})
    prompt_cfg = deepcopy(profile.get("prompt") or {})
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

    effective_instruction = str(
        query_instruction or retriever_cfg.get("query_instruction") or ""
    )
    normalized_filters = dict(filters or {})
    normalized_output_fields = list(output_fields or [])
    candidate_top_k = max(requested_top_k, default_top_k)

    dense_cfg = deepcopy(retriever_cfg)
    dense_cfg.update(
        {
            "query_list": [query],
            "retrieval_top_k": candidate_top_k,
            "query_instruction": effective_instruction,
            "filters": normalized_filters,
            "output_fields": normalized_output_fields,
        }
    )

    sparse_cfg = deepcopy(retriever_cfg)
    sparse_cfg["backend"] = "bm25"
    sparse_cfg.update(
        {
            "query_list": [query],
            "retrieval_top_k": candidate_top_k,
            "filters": normalized_filters,
            "output_fields": normalized_output_fields,
        }
    )

    payload: Dict[str, Any] = {
        "query": query,
        "query_list": [query],
        "q_ls": [query],
        "retrieval_top_k": candidate_top_k,
        "reranker_top_k": requested_top_k,
        "merge_top_k": candidate_top_k * 2,
        "query_instruction": effective_instruction,
        "filters": normalized_filters,
        "output_fields": normalized_output_fields,
        "dense": dense_cfg,
        "custom": {
            "query": query,
            "top_k": requested_top_k,
            "query_instruction": str(query_instruction or ""),
            "filters": normalized_filters,
            "output_fields": normalized_output_fields,
            "retriever_top_k": default_top_k,
            "retriever_query_instruction": str(
                retriever_cfg.get("query_instruction") or ""
            ),
        },
        "sparse": sparse_cfg,
    }
    if merge_cfg:
        payload["custom"].update(
            {
                "merge_top_k": candidate_top_k * 2,
                "strategy": merge_cfg.get("strategy", "rrf"),
                "rrf_k": merge_cfg.get("rrf_k", 60),
                "primary_weight": merge_cfg.get("primary_weight", 1.0),
                "secondary_weight": merge_cfg.get("secondary_weight", 1.0),
            }
        )

    if reranker_cfg:
        reranker_cfg["query_list"] = [query]
        reranker_cfg["query_instruction"] = effective_instruction
        reranker_cfg["reranker_top_k"] = requested_top_k
        payload["reranker"] = reranker_cfg
    if prompt_cfg:
        prompt_cfg["q_ls"] = [query]
        payload["prompt_builder"] = prompt_cfg
    if generation_cfg or system_prompt:
        generation_cfg["system_prompt"] = str(
            system_prompt or generation_cfg.get("system_prompt", "")
        )
        payload["generation"] = generation_cfg
    return payload
