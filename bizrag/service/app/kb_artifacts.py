from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from bizrag.common.io_utils import load_jsonl
from bizrag.service.app.kb_files import classify_source_type


def document_paths(kb: Mapping[str, Any], doc_key: str) -> Dict[str, Path]:
    workspace = Path(str(kb["workspace_dir"]))
    return {
        "corpus": workspace / "corpus" / "documents" / f"{doc_key}.jsonl",
        "chunk": workspace / "chunks" / "documents" / f"{doc_key}.jsonl",
        "images": workspace / "images" / doc_key,
        "mineru": workspace / "mineru" / doc_key,
    }


def combined_paths(kb: Mapping[str, Any]) -> Dict[str, Path]:
    workspace = Path(str(kb["workspace_dir"]))
    return {
        "corpus": workspace / "combined" / "corpus.jsonl",
        "chunk": workspace / "combined" / "chunks.jsonl",
        "embedding": workspace / "index" / "embeddings.npy",
        "bm25": workspace / "index" / "bm25",
        "faiss_index": workspace / "index" / "index.index",
    }


def doc_key_for_source(source_uri: str) -> str:
    return hashlib.sha1(source_uri.encode("utf-8")).hexdigest()[:16]


def normalize_corpus_rows(
    *,
    raw_rows: list[Dict[str, Any]],
    kb_id: str,
    source_path: Path,
    logical_source_uri: str,
    logical_file_name: str,
    doc_key: str,
    content_hash: str,
    source_root: Optional[str],
) -> list[Dict[str, Any]]:
    relative_path = None
    logical_source_path = Path(logical_source_uri)
    if source_root and logical_source_path.exists():
        try:
            relative_path = str(
                logical_source_path.resolve().relative_to(Path(source_root).resolve())
            )
        except ValueError:
            relative_path = None

    normalized: list[Dict[str, Any]] = []
    for idx, row in enumerate(raw_rows):
        source_doc_id = row.get("id")
        doc_id = (
            f"{doc_key}::{source_doc_id}"
            if source_doc_id is not None
            else f"{doc_key}::{idx}"
        )
        title = str(row.get("title") or Path(logical_file_name).stem)
        contents = str(row.get("contents") or "").strip()
        if not contents:
            continue
        item = dict(row)
        item["id"] = doc_id
        item["title"] = title
        item["contents"] = contents
        item["file_name"] = logical_file_name
        item["source_type"] = classify_source_type(source_path) or str(
            row.get("source_type") or ""
        )
        item["source_uri"] = logical_source_uri
        item["kb_id"] = kb_id
        item["doc_version"] = content_hash
        item["content_hash"] = content_hash
        item["doc_key"] = doc_key
        item["source_doc_id"] = source_doc_id
        if relative_path:
            item["source_rel_path"] = relative_path
        normalized.append(item)
    return normalized


def normalize_chunk_rows(
    *,
    raw_rows: list[Dict[str, Any]],
    doc_key: str,
    source_path: Path,
    logical_source_uri: str,
    logical_file_name: str,
    content_hash: str,
) -> list[Dict[str, Any]]:
    normalized: list[Dict[str, Any]] = []
    for idx, row in enumerate(raw_rows):
        item = dict(row)
        item["id"] = f"{doc_key}::chunk::{row.get('id', idx)}"
        item["doc_key"] = doc_key
        item["file_name"] = str(item.get("file_name") or logical_file_name)
        item["source_type"] = str(
            item.get("source_type") or classify_source_type(source_path) or ""
        )
        item["source_uri"] = str(item.get("source_uri") or logical_source_uri)
        item["doc_version"] = str(item.get("doc_version") or content_hash)
        item["content_hash"] = str(item.get("content_hash") or content_hash)
        normalized.append(item)
    return normalized


def build_passthrough_chunks(
    *,
    corpus_rows: list[Dict[str, Any]],
    doc_key: str,
    source_path: Path,
    logical_source_uri: str,
    logical_file_name: str,
    content_hash: str,
) -> list[Dict[str, Any]]:
    chunks: list[Dict[str, Any]] = []
    for idx, row in enumerate(corpus_rows):
        title = str(row.get("title") or Path(logical_file_name).stem)
        contents = str(row.get("contents") or "").strip()
        if not contents:
            continue
        item = {k: v for k, v in row.items() if k != "contents"}
        item["id"] = f"{doc_key}::chunk::{idx}"
        item["doc_id"] = str(row.get("id") or f"{doc_key}::{idx}")
        item["title"] = title
        item["contents"] = f"Title:\n{title}\n\nContent:\n{contents}"
        item["file_name"] = str(item.get("file_name") or logical_file_name)
        item["source_type"] = str(
            item.get("source_type") or classify_source_type(source_path) or ""
        )
        item["source_uri"] = str(item.get("source_uri") or logical_source_uri)
        item["doc_version"] = str(item.get("doc_version") or content_hash)
        item["content_hash"] = str(item.get("content_hash") or content_hash)
        item["doc_key"] = doc_key
        chunks.append(item)
    return chunks


def iter_jsonl_paths(
    docs: list[Dict[str, Any]],
    field_name: str,
) -> Iterable[Dict[str, Any]]:
    for doc in sorted(docs, key=lambda item: str(item["source_uri"])):
        path_value = doc.get(field_name)
        if not path_value:
            continue
        file_path = Path(str(path_value))
        if not file_path.exists():
            continue
        for row in load_jsonl(file_path):
            yield row
