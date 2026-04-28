#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _normalize_positive_int(value: Any, default: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = int(default)
    return normalized if normalized > 0 else int(default)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the BizRAG rag_eval pipeline against a benchmark JSONL and a registered KB."
    )
    parser.add_argument("--kb-id", required=True, help="Registered KB id")
    parser.add_argument(
        "--benchmark-path",
        required=True,
        help="Benchmark JSONL path containing question and golden_answers",
    )
    parser.add_argument(
        "--metadata-db",
        default="runtime/metadata.db",
        help="Metadata DB path used by BizRAG",
    )
    parser.add_argument(
        "--metrics",
        nargs="+",
        default=["acc", "em", "f1", "coverem"],
        help="Generation metrics passed to evaluation.evaluate",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Final reranked top-k. Retrieval depth follows KB defaults unless a larger value is needed.",
    )
    parser.add_argument(
        "--query-instruction",
        default="",
        help="Optional query instruction override for dense retrieval and reranking",
    )
    parser.add_argument("--system-prompt", default="", help="Optional generation system prompt")
    parser.add_argument("--benchmark-limit", type=int, default=-1, help="Benchmark sampling limit")
    parser.add_argument("--benchmark-shuffle", action="store_true", help="Shuffle benchmark rows")
    parser.add_argument("--benchmark-seed", type=int, default=42, help="Shuffle seed")
    parser.add_argument(
        "--save-path",
        default="rag_eval_workspace/generated/bizrag_eval/rag_eval_results.json",
        help="Evaluation result JSON path",
    )
    parser.add_argument("--log-level", default="error", help="Pipeline runner log level")
    parser.add_argument("--generation-backend", default=None, help="Optional generation backend override")
    parser.add_argument("--generation-model", default=None, help="Optional generation model name override")
    parser.add_argument("--generation-base-url", default=None, help="Optional OpenAI-compatible base URL")
    parser.add_argument("--generation-api-key", default=None, help="Optional generation API key override")
    parser.add_argument("--generation-max-tokens", type=int, default=None, help="Optional generation max_tokens override")
    parser.add_argument("--generation-temperature", type=float, default=None, help="Optional generation temperature override")
    return parser.parse_args()


def build_payload(args: argparse.Namespace, kb: dict[str, Any]) -> dict[str, Any]:
    from bizrag.service.app.kb_config import resolve_kb_server_parameters
    from bizrag.service.ultrarag.read_pipeline_payload import build_read_pipeline_payload

    profile = resolve_kb_server_parameters(kb=kb)
    retriever_cfg = dict(profile.get("retriever") or {})
    requested_top_k = _normalize_positive_int(args.top_k, 5)
    default_retrieval_top_k = _normalize_positive_int(
        retriever_cfg.get("retrieval_top_k", retriever_cfg.get("top_k")),
        requested_top_k,
    )
    retrieval_top_k = max(default_retrieval_top_k, requested_top_k)
    merge_top_k = retrieval_top_k * 2

    payload = build_read_pipeline_payload(
        kb=kb,
        query="",
        top_k=requested_top_k,
        query_instruction=args.query_instruction,
        filters=None,
        system_prompt=args.system_prompt,
    )
    payload["benchmark"] = {
        "benchmark": {
            "name": f"{args.kb_id}_benchmark",
            "path": str(Path(args.benchmark_path).resolve()),
            "key_map": {
                "q_ls": "question",
                "gt_ls": "golden_answers",
            },
            "limit": args.benchmark_limit,
            "shuffle": bool(args.benchmark_shuffle),
            "seed": args.benchmark_seed,
        }
    }
    payload["evaluation"] = {
        "metrics": list(args.metrics),
        "save_path": str(Path(args.save_path).resolve()),
    }

    dense_cfg = payload.setdefault("dense", {})
    dense_cfg["top_k"] = retrieval_top_k
    if args.query_instruction:
        dense_cfg["query_instruction"] = args.query_instruction

    sparse_cfg = payload.setdefault("sparse", {})
    sparse_cfg["top_k"] = retrieval_top_k

    reranker_cfg = payload.setdefault("reranker", {})
    reranker_cfg["top_k"] = requested_top_k
    if args.query_instruction:
        reranker_cfg["query_instruction"] = args.query_instruction

    custom_cfg = payload.setdefault("custom", {})
    custom_cfg["top_k"] = merge_top_k

    if (
        args.generation_backend
        or args.generation_model
        or args.generation_base_url
        or args.generation_api_key
        or args.generation_max_tokens is not None
        or args.generation_temperature is not None
        or args.system_prompt
    ):
        generation_cfg = payload.setdefault("generation", {})
        if args.generation_backend:
            generation_cfg["backend"] = args.generation_backend
        backend_name = str(generation_cfg.get("backend") or args.generation_backend or "").lower()
        backend_configs = generation_cfg.setdefault("backend_configs", {})
        if backend_name:
            backend_cfg = backend_configs.setdefault(backend_name, {})
            if args.generation_model:
                backend_cfg["model_name"] = args.generation_model
            if args.generation_base_url:
                backend_cfg["base_url"] = args.generation_base_url
            if args.generation_api_key:
                backend_cfg["api_key"] = args.generation_api_key
        sampling_params = generation_cfg.setdefault("sampling_params", {})
        if args.generation_max_tokens is not None:
            sampling_params["max_tokens"] = int(args.generation_max_tokens)
        if args.generation_temperature is not None:
            sampling_params["temperature"] = float(args.generation_temperature)
        if args.system_prompt:
            generation_cfg["system_prompt"] = args.system_prompt
    return payload


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    from bizrag.infra.metadata_store import MetadataStore
    from bizrag.service.ultrarag.pipeline_runner import UltraRAGPipelineRunner

    store = MetadataStore(args.metadata_db)
    runner = UltraRAGPipelineRunner()
    try:
        kb = store.get_kb(args.kb_id)
        if kb is None:
            raise SystemExit(f"KB not found: {args.kb_id}")
        payload = build_payload(args, kb)
        result = await runner.run("rag_eval", params=payload, log_level=args.log_level)
        return result
    finally:
        store.close()
        await runner.close()


def main() -> None:
    args = parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
