from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from bizrag import sdk


async def build_raw_corpus(
    *,
    file_path: Path,
    output_paths: Dict[str, Path],
    prefer_mineru: bool,
) -> None:
    suffix = file_path.suffix.lower()
    if suffix in {".xls", ".xlsx"}:
        await sdk.abuild_excel_corpus(
            parse_file_path=str(file_path),
            text_corpus_save_path=str(output_paths["corpus"]),
        )
        return

    if suffix == ".pdf" and prefer_mineru:
        await sdk.abuild_mineru_corpus(
            parse_file_path=str(file_path),
            mineru_dir=str(output_paths["mineru"]),
            text_corpus_save_path=str(output_paths["corpus"]),
            image_corpus_save_path=str(output_paths["images"].with_suffix(".jsonl")),
        )
        return

    await sdk.abuild_text_corpus(
        parse_file_path=str(file_path),
        text_corpus_save_path=str(output_paths["corpus"]),
    )


async def chunk_corpus(
    *,
    raw_chunk_path: str,
    chunk_path: str,
    chunk_backend: str,
    chunk_size: int,
    chunk_overlap: int,
    use_title: bool = True,
) -> None:
    await sdk.achunk_documents(
        raw_chunk_path=raw_chunk_path,
        chunk_path=chunk_path,
        chunk_backend=chunk_backend,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        use_title=use_title,
    )


def _retriever_override(runtime_cfg: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    retriever_params = {
        "model_name_or_path": runtime_cfg["model_name_or_path"],
        "backend_configs": runtime_cfg["backend_configs"],
        "batch_size": runtime_cfg.get("batch_size", 32),
        "corpus_path": runtime_cfg["corpus_path"],
        "embedding_path": runtime_cfg["embedding_path"],
        "gpu_ids": runtime_cfg.get("gpu_ids"),
        "is_multimodal": runtime_cfg.get("is_multimodal", False),
        "backend": runtime_cfg.get("backend", "sentence_transformers"),
        "index_backend": runtime_cfg.get("index_backend", "milvus"),
        "index_backend_configs": runtime_cfg.get("index_backend_configs", {}),
        "is_demo": runtime_cfg.get("is_demo", False),
        "collection_name": runtime_cfg["collection_name"],
        "overwrite": False,
    }
    retriever_params.update(extra)
    return {"retriever": retriever_params}


async def build_milvus_index(
    *,
    runtime_cfg: Dict[str, Any],
    corpus_path: str,
    embedding_path: str,
    overwrite: bool,
    collection_name: str,
) -> None:
    await sdk.abuild_milvus_index(
        override_params=_retriever_override(
            runtime_cfg,
            corpus_path=corpus_path,
            embedding_path=embedding_path,
            overwrite=overwrite,
            collection_name=collection_name,
        )
    )


async def delete_milvus_doc_key(
    *,
    runtime_cfg: Dict[str, Any],
    collection_name: str,
    doc_key: str,
) -> int:
    result = await sdk.amilvus_delete(
        override_params=_retriever_override(
            runtime_cfg,
            filter_expr=f"doc_key == {json.dumps(doc_key, ensure_ascii=False)}",
            collection_name=collection_name,
        )
    )
    if isinstance(result, list) and result:
        result = result[-1]
    if isinstance(result, dict):
        return int(result.get("deleted_count", 0))
    return int(result or 0)


async def drop_milvus_collection(
    *,
    runtime_cfg: Dict[str, Any],
    collection_name: str,
) -> None:
    await sdk.amilvus_drop_collection(
        override_params=_retriever_override(
            runtime_cfg,
            collection_name=collection_name,
        )
    )
