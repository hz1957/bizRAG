from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import yaml
from typing import Any

from ultrarag.api import PipelineCall

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIZRAG_DIR = Path(__file__).resolve().parent
PIPELINES_DIR = BIZRAG_DIR / "pipelines"
PARAMETER_DIR = PIPELINES_DIR / "parameter"


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _resolve_project_path(ref: str, *, base_dir: Path) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute():
        return candidate

    project_candidate = PROJECT_ROOT / candidate
    if project_candidate.exists():
        return project_candidate

    base_candidate = base_dir / candidate
    if base_candidate.exists():
        return base_candidate

    return project_candidate


def _build_server_companion(pipeline_file: Path) -> dict[str, Any]:
    pipeline_cfg = _load_yaml(pipeline_file)
    servers = pipeline_cfg.get("servers") or {}
    companion: dict[str, Any] = {}

    for alias, server_ref in servers.items():
        server_path = _resolve_project_path(str(server_ref), base_dir=pipeline_file.parent)
        server_yaml = server_path if server_path.is_file() else server_path / "server.yaml"
        if not server_yaml.is_file():
            raise FileNotFoundError(
                f"Server config for '{alias}' not found: expected {server_yaml}"
            )
        companion[alias] = _load_yaml(server_yaml)

    return companion


def _materialize_pipeline_bundle(pipeline_file: Path) -> tuple[tempfile.TemporaryDirectory, Path]:
    bundle = tempfile.TemporaryDirectory(prefix=f"bizrag_pipeline_{pipeline_file.stem}_")
    bundle_root = Path(bundle.name)
    bundle_pipelines = bundle_root / "pipelines"
    bundle_server_dir = bundle_pipelines / "server"
    bundle_server_dir.mkdir(parents=True, exist_ok=True)

    materialized_pipeline = bundle_pipelines / pipeline_file.name
    materialized_pipeline.write_text(pipeline_file.read_text(encoding="utf-8"), encoding="utf-8")

    server_companion = bundle_server_dir / f"{pipeline_file.stem}_server.yaml"
    server_companion.write_text(
        yaml.safe_dump(
            _build_server_companion(pipeline_file),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return bundle, materialized_pipeline


def run_named_pipeline(
    pipeline_name: str,
    *,
    log_level: str = "error",
    override_params: dict | None = None,
):
    """Run one of the local pipelines by name synchronously."""
    loop = asyncio.get_event_loop_policy().get_event_loop()
    if loop.is_running():
        raise RuntimeError("run_named_pipeline cannot be used inside a running event loop; use arun_named_pipeline instead")

    return loop.run_until_complete(
        arun_named_pipeline(
            pipeline_name,
            log_level=log_level,
            override_params=override_params,
        )
    )


async def arun_named_pipeline(
    pipeline_name: str,
    *,
    log_level: str = "error",
    override_params: dict | None = None,
):
    """Run one of the local pipelines by name, generating parameter file dynamically from overrides."""
    pipeline_file = PIPELINES_DIR / f"{pipeline_name}.yaml"
    base_params = override_params or {}
    pipeline_bundle, materialized_pipeline = _materialize_pipeline_bundle(pipeline_file)

    fd, temp_param_path = tempfile.mkstemp(suffix=".yaml", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.dump(base_params, f, allow_unicode=True)

    try:
        result = PipelineCall(
            pipeline_file=str(materialized_pipeline),
            parameter_file=str(temp_param_path),
            log_level=log_level,
        )
        if asyncio.isfuture(result) or hasattr(result, "__await__"):
            return await result
        return result
    finally:
        pipeline_bundle.cleanup()
        os.remove(temp_param_path)


def build_text_corpus(*, parse_file_path: str, text_corpus_save_path: str):
    """Run corpus.build_text_corpus through PipelineCall."""
    return run_named_pipeline(
        "build_text_corpus",
        override_params={
            "corpus": {
                "parse_file_path": parse_file_path,
                "text_corpus_save_path": text_corpus_save_path
            }
        }
    )


async def abuild_text_corpus(*, parse_file_path: str, text_corpus_save_path: str):
    return await arun_named_pipeline(
        "build_text_corpus",
        override_params={
            "corpus": {
                "parse_file_path": parse_file_path,
                "text_corpus_save_path": text_corpus_save_path,
            }
        },
    )


def build_mineru_corpus(*, parse_file_path: str, mineru_dir: str, text_corpus_save_path: str, image_corpus_save_path: str):
    """Run corpus.mineru_parse through PipelineCall."""
    return run_named_pipeline(
        "build_mineru_corpus",
        override_params={
            "corpus": {
                "parse_file_path": parse_file_path,
                "mineru_dir": mineru_dir,
                "text_corpus_save_path": text_corpus_save_path,
                "image_corpus_save_path": image_corpus_save_path
            }
        }
    )


async def abuild_mineru_corpus(*, parse_file_path: str, mineru_dir: str, text_corpus_save_path: str, image_corpus_save_path: str):
    return await arun_named_pipeline(
        "build_mineru_corpus",
        override_params={
            "corpus": {
                "parse_file_path": parse_file_path,
                "mineru_dir": mineru_dir,
                "text_corpus_save_path": text_corpus_save_path,
                "image_corpus_save_path": image_corpus_save_path,
            }
        },
    )


def build_excel_corpus(*, parse_file_path: str, text_corpus_save_path: str, sheet_mode: str = "row", include_header: bool = True):
    """Run biz_corpus.build_excel_corpus through PipelineCall."""
    return run_named_pipeline(
        "build_excel_corpus",
        override_params={
            "biz_corpus": {
                "parse_file_path": parse_file_path,
                "text_corpus_save_path": text_corpus_save_path,
                "sheet_mode": sheet_mode,
                "include_header": include_header
            }
        }
    )


async def abuild_excel_corpus(*, parse_file_path: str, text_corpus_save_path: str, sheet_mode: str = "row", include_header: bool = True):
    return await arun_named_pipeline(
        "build_excel_corpus",
        override_params={
            "biz_corpus": {
                "parse_file_path": parse_file_path,
                "text_corpus_save_path": text_corpus_save_path,
                "sheet_mode": sheet_mode,
                "include_header": include_header,
            }
        },
    )


def chunk_documents(
    *,
    raw_chunk_path: str,
    chunk_path: str,
    chunk_backend: str = "sentence",
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    use_title: bool = True,
):
    """Run corpus.chunk_documents through PipelineCall with dynamic parameter override."""
    return run_named_pipeline(
        "corpus_chunk",
        override_params={
            "corpus": {
                "raw_chunk_path": raw_chunk_path,
                "chunk_path": chunk_path,
                "chunk_backend": chunk_backend,
                "chunk_size": chunk_size,
                "use_title": use_title,
                "tokenizer_or_token_counter": "character",
                "chunk_backend_configs": {
                    "token": {"chunk_overlap": chunk_overlap},
                    "sentence": {
                        "chunk_overlap": chunk_overlap,
                        "min_sentences_per_chunk": 1,
                        "delim": "['.', '!', '?', '；', '。', '！', '？', '\\n']",
                    },
                    "recursive": {"min_characters_per_chunk": 12},
                },
            }
        }
    )


async def achunk_documents(
    *,
    raw_chunk_path: str,
    chunk_path: str,
    chunk_backend: str = "sentence",
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    use_title: bool = True,
):
    return await arun_named_pipeline(
        "corpus_chunk",
        override_params={
            "corpus": {
                "raw_chunk_path": raw_chunk_path,
                "chunk_path": chunk_path,
                "chunk_backend": chunk_backend,
                "chunk_size": chunk_size,
                "use_title": use_title,
                "tokenizer_or_token_counter": "character",
                "chunk_backend_configs": {
                    "token": {"chunk_overlap": chunk_overlap},
                    "sentence": {
                        "chunk_overlap": chunk_overlap,
                        "min_sentences_per_chunk": 1,
                        "delim": "['.', '!', '?', '；', '。', '！', '？', '\\n']",
                    },
                    "recursive": {"min_characters_per_chunk": 12},
                },
            }
        },
    )


def build_milvus_index(
    *,
    corpus_path: str,
    uri: str = "index/milvus_demo.db",
    collection_name: str = "wiki",
    token: str | None = None,
    backend: str = "sentence_transformers",
    model_name_or_path: str = "openbmb/MiniCPM-Embedding-Light",
    gpu_ids: str = "1",
    batch_size: int = 16,
    query_instruction: str = "query",
    document_instruction: str = "document",
    overwrite: bool = False
):
    """Run milvus_index pipeline, replacing standalone yaml parameters with python arguments."""
    return run_named_pipeline(
        "milvus_index",
        override_params={
            "retriever": {
                "corpus_path": corpus_path,
                "collection_name": collection_name,
                "model_name_or_path": model_name_or_path,
                "backend": backend,
                "batch_size": batch_size,
                "gpu_ids": gpu_ids,
                "index_backend": "milvus",
                "overwrite": overwrite,
                "backend_configs": {
                    "sentence_transformers": {
                        "trust_remote_code": True,
                        "sentence_transformers_encode": {
                            "encode_chunk_size": 256,
                            "normalize_embeddings": False,
                            "q_prompt_name": query_instruction,
                            "psg_prompt_name": document_instruction
                        }
                    }
                },
                "index_backend_configs": {
                    "milvus": {
                        "uri": uri,
                        "token": token,
                        "id_field_name": "id",
                        "id_max_length": 64,
                        "text_field_name": "contents",
                        "text_max_length": 60000,
                        "vector_field_name": "vector",
                        "index_chunk_size": 1000,
                        "metric_type": "IP",
                        "index_params": {"index_type": "AUTOINDEX", "metric_type": "IP"},
                        "search_params": {"metric_type": "IP", "params": {}},
                    }
                }
            }
        }
    )


async def abuild_milvus_index(
    *,
    override_params: dict,
    log_level: str = "error",
):
    return await arun_named_pipeline(
        "milvus_index",
        log_level=log_level,
        override_params=override_params,
    )


async def amilvus_delete(
    *,
    override_params: dict,
    log_level: str = "error",
):
    return await arun_named_pipeline(
        "milvus_delete",
        log_level=log_level,
        override_params=override_params,
    )


async def amilvus_drop_collection(
    *,
    override_params: dict,
    log_level: str = "error",
):
    return await arun_named_pipeline(
        "milvus_drop_collection",
        log_level=log_level,
        override_params=override_params,
    )
