from __future__ import annotations

import os
from pathlib import Path
import tempfile
import yaml

from ultrarag.api import PipelineCall

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BIZRAG_DIR = PROJECT_ROOT / "bizrag"
PIPELINES_DIR = BIZRAG_DIR / "pipelines"
PARAMETER_DIR = PIPELINES_DIR / "parameter"


def run_named_pipeline(
    pipeline_name: str,
    *,
    log_level: str = "error",
    override_params: dict | None = None,
):
    """Run one of the local pipelines by name, generating parameter file dynamically from overrides."""
    pipeline_file = PIPELINES_DIR / f"{pipeline_name}.yaml"
    base_params = override_params or {}
    
    fd, temp_param_path = tempfile.mkstemp(suffix=".yaml", text=True)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        yaml.dump(base_params, f, allow_unicode=True)
        
    try:
        return PipelineCall(
            pipeline_file=str(pipeline_file),
            parameter_file=str(temp_param_path),
            log_level=log_level,
        )
    finally:
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
