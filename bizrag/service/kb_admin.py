from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORPUS_SRC = PROJECT_ROOT / "bizrag" / "src" / "servers" / "corpus" / "src"
BIZ_CORPUS_SRC = PROJECT_ROOT / "bizrag" / "src" / "servers" / "biz_corpus" / "src"
RETRIEVER_SRC = PROJECT_ROOT / "bizrag" / "src" / "servers" / "retriever" / "src"

for src_path in (CORPUS_SRC, BIZ_CORPUS_SRC, RETRIEVER_SRC):
    src_str = str(src_path)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)

from biz_corpus import build_excel_corpus as build_excel_corpus_tool  # noqa: E402
from corpus import (  # noqa: E402
    build_mineru_corpus as build_mineru_corpus_tool,
    build_text_corpus as build_text_corpus_tool,
    chunk_documents as chunk_documents_tool,
    mineru_parse as mineru_parse_tool,
)
from index_backends.milvus_backend import MilvusIndexBackend  # noqa: E402
from retriever import Retriever, app as retriever_app  # noqa: E402

from bizrag.src.service.metadata_store import MetadataStore


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".docx",
    ".doc",
    ".wps",
    ".pdf",
    ".xps",
    ".oxps",
    ".epub",
    ".mobi",
    ".fb2",
}
EXCEL_EXTENSIONS = {".xls", ".xlsx"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | EXCEL_EXTENSIONS
IGNORED_PREFIXES = {"~$"}


def load_yaml(path: str | Path) -> Dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise RuntimeError(f"Config file does not exist: {file_path}")
    with file_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def dump_yaml(path: str | Path, data: Dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def load_jsonl(path: str | Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: str | Path, rows: Iterable[Dict[str, Any]]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def classify_source_type(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()
    if suffix in EXCEL_EXTENSIONS:
        return "excel"
    if suffix in TEXT_EXTENSIONS:
        return suffix.lstrip(".")
    return None


def discover_supported_files(path: Path) -> List[Path]:
    if path.is_file():
        return [path] if should_ingest(path) else []

    files: List[Path] = []
    for file_path in sorted(path.rglob("*")):
        if file_path.is_file() and should_ingest(file_path):
            files.append(file_path.resolve())
    return files


def should_ingest(path: Path) -> bool:
    if any(path.name.startswith(prefix) for prefix in IGNORED_PREFIXES):
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def default_chunk_backend_configs(chunk_overlap: int) -> Dict[str, Any]:
    return {
        "token": {"chunk_overlap": chunk_overlap},
        "sentence": {
            "chunk_overlap": chunk_overlap,
            "min_sentences_per_chunk": 1,
            "delim": "['.', '!', '?', '；', '。', '！', '？', '\\n']",
        },
        "recursive": {"min_characters_per_chunk": 12},
    }


async def invoke_tool(tool_obj: Any, /, **kwargs: Any) -> Any:
    fn = getattr(tool_obj, "fn", None)
    if fn is None:
        raise RuntimeError(f"Tool object does not expose callable fn: {tool_obj!r}")
    return await fn(**kwargs)


class KBAdmin:
    def __init__(
        self,
        *,
        metadata_db: str | Path,
        kb_registry_path: str | Path,
        workspace_root: str | Path,
    ) -> None:
        self.store = MetadataStore(Path(metadata_db))
        self.kb_registry_path = Path(kb_registry_path)
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.store.close()

    def register_kb(
        self,
        *,
        kb_id: str,
        retriever_config_path: str,
        collection_name: Optional[str] = None,
        display_name: Optional[str] = None,
        source_root: Optional[str] = None,
        index_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg = load_yaml(retriever_config_path)
        milvus_cfg = (
            cfg.get("index_backend_configs", {})
            .get("milvus", {})
        )
        workspace_dir = self.workspace_root / kb_id
        for subdir in (
            workspace_dir / "corpus" / "documents",
            workspace_dir / "chunks" / "documents",
            workspace_dir / "combined",
            workspace_dir / "index",
            workspace_dir / "mineru",
            workspace_dir / "images",
        ):
            subdir.mkdir(parents=True, exist_ok=True)

        resolved_collection = collection_name or kb_id
        resolved_index_uri = index_uri or milvus_cfg.get("uri")
        if not resolved_index_uri:
            resolved_index_uri = str(workspace_dir / "index" / "milvus_lite.db")

        kb = self.store.register_kb(
            kb_id=kb_id,
            collection_name=resolved_collection,
            display_name=display_name,
            source_root=str(Path(source_root).resolve()) if source_root else None,
            workspace_dir=str(workspace_dir),
            retriever_config_path=str(Path(retriever_config_path).resolve()),
            index_uri=str(resolved_index_uri),
        )
        self._sync_kb_registry(kb_id=kb_id, collection_name=resolved_collection)
        return kb

    def _sync_kb_registry(self, *, kb_id: str, collection_name: str) -> None:
        data = {}
        if self.kb_registry_path.exists():
            data = load_yaml(self.kb_registry_path)
        mappings = data.get("mappings")
        if not isinstance(mappings, dict):
            mappings = {}
        mappings[kb_id] = {"collection_name": collection_name}
        data["mappings"] = mappings
        dump_yaml(self.kb_registry_path, data)

    def _get_kb(self, kb_id: str) -> Dict[str, Any]:
        kb = self.store.get_kb(kb_id)
        if kb is None:
            raise RuntimeError(f"Unknown kb_id: {kb_id}. Run register-kb first.")
        return kb

    def _document_paths(self, kb: Dict[str, Any], doc_key: str) -> Dict[str, Path]:
        workspace = Path(kb["workspace_dir"])
        return {
            "corpus": workspace / "corpus" / "documents" / f"{doc_key}.jsonl",
            "chunk": workspace / "chunks" / "documents" / f"{doc_key}.jsonl",
            "images": workspace / "images" / doc_key,
            "mineru": workspace / "mineru" / doc_key,
        }

    def _combined_paths(self, kb: Dict[str, Any]) -> Dict[str, Path]:
        workspace = Path(kb["workspace_dir"])
        return {
            "corpus": workspace / "combined" / "corpus.jsonl",
            "chunk": workspace / "combined" / "chunks.jsonl",
            "embedding": workspace / "index" / "embeddings.npy",
            "runtime_cfg": workspace / "index" / "retriever_runtime.yaml",
        }

    @staticmethod
    def _doc_key_for_source(source_uri: str) -> str:
        return hashlib.sha1(source_uri.encode("utf-8")).hexdigest()[:16]

    def _normalize_corpus_rows(
        self,
        *,
        raw_rows: List[Dict[str, Any]],
        kb_id: str,
        source_path: Path,
        doc_key: str,
        content_hash: str,
        source_root: Optional[str],
    ) -> List[Dict[str, Any]]:
        relative_path = None
        if source_root:
            try:
                relative_path = str(source_path.resolve().relative_to(Path(source_root).resolve()))
            except ValueError:
                relative_path = None

        normalized: List[Dict[str, Any]] = []
        for idx, row in enumerate(raw_rows):
            source_doc_id = row.get("id")
            doc_id = f"{doc_key}::{source_doc_id}" if source_doc_id is not None else f"{doc_key}::{idx}"
            title = str(row.get("title") or source_path.stem)
            contents = str(row.get("contents") or "").strip()
            if not contents:
                continue
            item = dict(row)
            item["id"] = doc_id
            item["title"] = title
            item["contents"] = contents
            item["file_name"] = source_path.name
            item["source_type"] = classify_source_type(source_path) or str(row.get("source_type") or "")
            item["source_uri"] = str(source_path.resolve())
            item["kb_id"] = kb_id
            item["doc_version"] = content_hash
            item["content_hash"] = content_hash
            item["doc_key"] = doc_key
            item["source_doc_id"] = source_doc_id
            if relative_path:
                item["source_rel_path"] = relative_path
            normalized.append(item)
        return normalized

    def _normalize_chunk_rows(
        self,
        *,
        raw_rows: List[Dict[str, Any]],
        doc_key: str,
        source_path: Path,
        content_hash: str,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for idx, row in enumerate(raw_rows):
            item = dict(row)
            item["id"] = f"{doc_key}::chunk::{row.get('id', idx)}"
            item["doc_key"] = doc_key
            item["file_name"] = str(item.get("file_name") or source_path.name)
            item["source_type"] = str(item.get("source_type") or classify_source_type(source_path) or "")
            item["source_uri"] = str(item.get("source_uri") or source_path.resolve())
            item["doc_version"] = str(item.get("doc_version") or content_hash)
            item["content_hash"] = str(item.get("content_hash") or content_hash)
            normalized.append(item)
        return normalized

    def _build_passthrough_chunks(
        self,
        *,
        corpus_rows: List[Dict[str, Any]],
        doc_key: str,
        source_path: Path,
        content_hash: str,
    ) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        for idx, row in enumerate(corpus_rows):
            title = str(row.get("title") or source_path.stem)
            contents = str(row.get("contents") or "").strip()
            if not contents:
                continue
            item = {k: v for k, v in row.items() if k != "contents"}
            item["id"] = f"{doc_key}::chunk::{idx}"
            item["doc_id"] = str(row.get("id") or f"{doc_key}::{idx}")
            item["title"] = title
            item["contents"] = f"Title:\n{title}\n\nContent:\n{contents}"
            item["file_name"] = str(item.get("file_name") or source_path.name)
            item["source_type"] = str(item.get("source_type") or classify_source_type(source_path) or "")
            item["source_uri"] = str(item.get("source_uri") or source_path.resolve())
            item["doc_version"] = str(item.get("doc_version") or content_hash)
            item["content_hash"] = str(item.get("content_hash") or content_hash)
            item["doc_key"] = doc_key
            chunks.append(item)
        return chunks

    async def ingest_path(
        self,
        *,
        kb_id: str,
        path: str,
        sync_deletions: bool,
        force: bool,
        prefer_mineru: bool,
        chunk_backend: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> Dict[str, Any]:
        kb = self._get_kb(kb_id)
        input_path = Path(path).resolve()
        if not input_path.exists():
            raise RuntimeError(f"Input path not found: {input_path}")

        task_id = str(uuid.uuid4())
        self.store.create_task(
            task_id=task_id,
            kb_id=kb_id,
            task_type="sync_dir" if input_path.is_dir() else "ingest_path",
            status="running",
            source_uri=str(input_path),
            payload={
                "path": str(input_path),
                "sync_deletions": sync_deletions,
                "force": force,
                "prefer_mineru": prefer_mineru,
                "chunk_backend": chunk_backend,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            },
        )

        files = discover_supported_files(input_path)
        created = 0
        updated = 0
        skipped = 0
        failed = 0
        deleted = 0
        changed = False
        failed_items: List[Dict[str, str]] = []

        try:
            for file_path in files:
                try:
                    result = await self._upsert_file(
                        kb=kb,
                        file_path=file_path,
                        force=force,
                        prefer_mineru=prefer_mineru,
                        chunk_backend=chunk_backend,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                    )
                    if result == "created":
                        created += 1
                        changed = True
                    elif result == "updated":
                        updated += 1
                        changed = True
                    else:
                        skipped += 1
                except Exception as exc:
                    failed += 1
                    failed_items.append(
                        {
                            "source_uri": str(file_path.resolve()),
                            "error": str(exc),
                        }
                    )
                    self._record_failed_file(kb=kb, file_path=file_path, error_message=str(exc))
                    retriever_app.logger.warning(
                        "[kb_admin] Failed to ingest %s: %s",
                        file_path,
                        exc,
                    )

            if sync_deletions and input_path.is_dir():
                deleted_docs = self._sync_deleted_documents(kb=kb, scanned_root=input_path, keep_paths=files)
                deleted += deleted_docs
                if deleted_docs:
                    changed = True

            if changed or force:
                await self._rebuild_kb(kb)

            result = {
                "task_id": task_id,
                "kb_id": kb_id,
                "files_seen": len(files),
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
                "deleted": deleted,
                "reindexed": bool(changed or force),
            }
            if failed_items:
                result["failed_items"] = failed_items
            self.store.update_task(task_id, status="success", result=result)
            return result
        except Exception as exc:
            self.store.update_task(task_id, status="failed", error_message=str(exc))
            raise

    async def delete_document(self, *, kb_id: str, source_uri: str) -> Dict[str, Any]:
        kb = self._get_kb(kb_id)
        resolved_source = str(Path(source_uri).resolve())
        task_id = str(uuid.uuid4())
        self.store.create_task(
            task_id=task_id,
            kb_id=kb_id,
            task_type="delete_document",
            status="running",
            source_uri=resolved_source,
            payload={"source_uri": resolved_source},
        )
        try:
            deleted = self._mark_deleted(kb_id=kb_id, source_uri=resolved_source)
            if deleted:
                await self._rebuild_kb(kb)
            result = {
                "task_id": task_id,
                "kb_id": kb_id,
                "source_uri": resolved_source,
                "deleted": deleted,
            }
            self.store.update_task(task_id, status="success", result=result)
            return result
        except Exception as exc:
            self.store.update_task(task_id, status="failed", error_message=str(exc))
            raise

    async def rebuild_kb(self, *, kb_id: str) -> Dict[str, Any]:
        kb = self._get_kb(kb_id)
        task_id = str(uuid.uuid4())
        self.store.create_task(
            task_id=task_id,
            kb_id=kb_id,
            task_type="rebuild_collection",
            status="running",
            payload={"kb_id": kb_id},
        )
        try:
            result = await self._rebuild_kb(kb)
            result["task_id"] = task_id
            self.store.update_task(task_id, status="success", result=result)
            return result
        except Exception as exc:
            self.store.update_task(task_id, status="failed", error_message=str(exc))
            raise

    async def retry_task(self, task_id: str) -> Dict[str, Any]:
        task = self.store.get_task(task_id)
        if task is None:
            raise RuntimeError(f"Unknown task_id: {task_id}")
        payload = task.get("payload_json") or {}
        task_type = task["task_type"]
        if task_type in {"ingest_path", "sync_dir"}:
            return await self.ingest_path(
                kb_id=task["kb_id"],
                path=str(payload["path"]),
                sync_deletions=bool(payload.get("sync_deletions", False)),
                force=bool(payload.get("force", False)),
                prefer_mineru=bool(payload.get("prefer_mineru", False)),
                chunk_backend=str(payload.get("chunk_backend", "sentence")),
                chunk_size=int(payload.get("chunk_size", 512)),
                chunk_overlap=int(payload.get("chunk_overlap", 50)),
            )
        if task_type == "delete_document":
            return await self.delete_document(
                kb_id=task["kb_id"],
                source_uri=str(payload["source_uri"]),
            )
        if task_type == "rebuild_collection":
            return await self.rebuild_kb(kb_id=task["kb_id"])
        raise RuntimeError(f"Retry is not implemented for task_type={task_type}")

    async def _upsert_file(
        self,
        *,
        kb: Dict[str, Any],
        file_path: Path,
        force: bool,
        prefer_mineru: bool,
        chunk_backend: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> str:
        source_uri = str(file_path.resolve())
        doc_key = self._doc_key_for_source(source_uri)
        content_hash = sha256_file(file_path)
        source_type = classify_source_type(file_path)
        if source_type is None:
            return "skipped"

        existing = self.store.get_document(kb["kb_id"], source_uri)
        if (
            existing is not None
            and existing.get("status") == "active"
            and existing.get("content_hash") == content_hash
            and not force
        ):
            return "skipped"

        output_paths = self._document_paths(kb, doc_key)
        raw_corpus_rows = await self._build_raw_corpus(
            file_path=file_path,
            output_paths=output_paths,
            prefer_mineru=prefer_mineru,
        )
        normalized_corpus = self._normalize_corpus_rows(
            raw_rows=raw_corpus_rows,
            kb_id=kb["kb_id"],
            source_path=file_path,
            doc_key=doc_key,
            content_hash=content_hash,
            source_root=kb.get("source_root"),
        )
        if not normalized_corpus:
            raise RuntimeError(f"No corpus rows generated for {file_path}")
        write_jsonl(output_paths["corpus"], normalized_corpus)

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as temp_chunk_file:
            temp_chunk_path = Path(temp_chunk_file.name)
        try:
            try:
                await invoke_tool(
                    chunk_documents_tool,
                    raw_chunk_path=str(output_paths["corpus"]),
                    chunk_backend_configs=default_chunk_backend_configs(chunk_overlap),
                    chunk_backend=chunk_backend,
                    tokenizer_or_token_counter="character",
                    chunk_size=chunk_size,
                    chunk_path=str(temp_chunk_path),
                    use_title=True,
                )
                raw_chunk_rows = load_jsonl(temp_chunk_path)
            except Exception as exc:
                retriever_app.logger.warning(
                    "[kb_admin] chunk_documents failed for %s, fallback to passthrough chunks: %s",
                    file_path,
                    exc,
                )
                raw_chunk_rows = self._build_passthrough_chunks(
                    corpus_rows=normalized_corpus,
                    doc_key=doc_key,
                    source_path=file_path,
                    content_hash=content_hash,
                )
        finally:
            if temp_chunk_path.exists():
                temp_chunk_path.unlink()

        normalized_chunks = self._normalize_chunk_rows(
            raw_rows=raw_chunk_rows,
            doc_key=doc_key,
            source_path=file_path,
            content_hash=content_hash,
        )
        write_jsonl(output_paths["chunk"], normalized_chunks)

        self.store.upsert_document(
            kb_id=kb["kb_id"],
            source_uri=source_uri,
            doc_key=doc_key,
            file_name=file_path.name,
            source_type=source_type,
            content_hash=content_hash,
            doc_version=content_hash,
            status="active",
            corpus_path=str(output_paths["corpus"]),
            chunk_path=str(output_paths["chunk"]),
        )
        return "created" if existing is None or existing.get("status") == "deleted" else "updated"

    def _record_failed_file(
        self,
        *,
        kb: Dict[str, Any],
        file_path: Path,
        error_message: str,
    ) -> None:
        source_uri = str(file_path.resolve())
        doc_key = self._doc_key_for_source(source_uri)
        content_hash = sha256_file(file_path) if file_path.exists() else ""
        source_type = classify_source_type(file_path) or ""
        self.store.upsert_document(
            kb_id=kb["kb_id"],
            source_uri=source_uri,
            doc_key=doc_key,
            file_name=file_path.name,
            source_type=source_type,
            content_hash=content_hash,
            doc_version=content_hash,
            status="failed",
            corpus_path=None,
            chunk_path=None,
            last_error=error_message,
        )

    async def _build_raw_corpus(
        self,
        *,
        file_path: Path,
        output_paths: Dict[str, Path],
        prefer_mineru: bool,
    ) -> List[Dict[str, Any]]:
        suffix = file_path.suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as temp_file:
            temp_corpus_path = Path(temp_file.name)
        try:
            if suffix in EXCEL_EXTENSIONS:
                await invoke_tool(
                    build_excel_corpus_tool,
                    parse_file_path=str(file_path),
                    text_corpus_save_path=str(temp_corpus_path),
                )
            elif suffix == ".pdf" and prefer_mineru:
                text_output = temp_corpus_path
                image_output = output_paths["images"].with_suffix(".jsonl")
                await invoke_tool(
                    mineru_parse_tool,
                    parse_file_path=str(file_path),
                    mineru_dir=str(output_paths["mineru"]),
                    mineru_extra_params=None,
                )
                await invoke_tool(
                    build_mineru_corpus_tool,
                    mineru_dir=str(output_paths["mineru"]),
                    parse_file_path=str(file_path),
                    text_corpus_save_path=str(text_output),
                    image_corpus_save_path=str(image_output),
                )
            else:
                await invoke_tool(
                    build_text_corpus_tool,
                    parse_file_path=str(file_path),
                    text_corpus_save_path=str(temp_corpus_path),
                )
            return load_jsonl(temp_corpus_path)
        finally:
            if temp_corpus_path.exists():
                temp_corpus_path.unlink()

    def _sync_deleted_documents(
        self,
        *,
        kb: Dict[str, Any],
        scanned_root: Path,
        keep_paths: List[Path],
    ) -> int:
        keep_uris = {str(path.resolve()) for path in keep_paths}
        prefix = str(scanned_root.resolve())
        if not prefix.endswith(os.sep):
            prefix = f"{prefix}{os.sep}"
        deleted = 0
        for doc in self.store.list_documents(kb["kb_id"], include_deleted=False, source_prefix=prefix):
            if str(doc["source_uri"]) not in keep_uris:
                deleted += int(self._mark_deleted(kb_id=kb["kb_id"], source_uri=str(doc["source_uri"])))
        return deleted

    def _mark_deleted(self, *, kb_id: str, source_uri: str) -> bool:
        doc = self.store.get_document(kb_id, source_uri)
        if doc is None or doc.get("status") == "deleted":
            return False
        for path_key in ("corpus_path", "chunk_path"):
            path_value = doc.get(path_key)
            if path_value and Path(path_value).exists():
                Path(path_value).unlink()
        self.store.mark_document_deleted(kb_id, source_uri)
        return True

    async def _rebuild_kb(self, kb: Dict[str, Any]) -> Dict[str, Any]:
        combined_paths = self._combined_paths(kb)
        active_docs = self.store.list_documents(kb["kb_id"], include_deleted=False)

        write_jsonl(combined_paths["corpus"], self._iterate_jsonl_paths(active_docs, "corpus_path"))
        write_jsonl(combined_paths["chunk"], self._iterate_jsonl_paths(active_docs, "chunk_path"))

        active_doc_count = len(active_docs)
        chunk_count = sum(1 for _ in self._iterate_jsonl_paths(active_docs, "chunk_path"))
        if chunk_count == 0:
            self._drop_collection(kb)
            return {
                "kb_id": kb["kb_id"],
                "collection_name": kb["collection_name"],
                "documents": active_doc_count,
                "chunks": 0,
                "dropped_collection": True,
            }

        runtime_cfg = self._build_runtime_retriever_config(kb, combined_paths)
        dump_yaml(combined_paths["runtime_cfg"], runtime_cfg)

        retriever = Retriever(retriever_app)
        await retriever.retriever_init(
            model_name_or_path=runtime_cfg["model_name_or_path"],
            backend_configs=runtime_cfg["backend_configs"],
            batch_size=runtime_cfg.get("batch_size", 32),
            corpus_path=runtime_cfg["corpus_path"],
            gpu_ids=runtime_cfg.get("gpu_ids"),
            is_multimodal=runtime_cfg.get("is_multimodal", False),
            backend=runtime_cfg.get("backend", "sentence_transformers"),
            index_backend=runtime_cfg.get("index_backend", "milvus"),
            index_backend_configs=runtime_cfg.get("index_backend_configs", {}),
            is_demo=runtime_cfg.get("is_demo", False),
            collection_name=runtime_cfg.get("collection_name", kb["collection_name"]),
        )
        await retriever.retriever_embed(
            embedding_path=runtime_cfg["embedding_path"],
            overwrite=True,
            is_multimodal=runtime_cfg.get("is_multimodal", False),
        )
        await retriever.retriever_index(
            embedding_path=runtime_cfg["embedding_path"],
            overwrite=True,
            collection_name=kb["collection_name"],
            corpus_path=runtime_cfg["corpus_path"],
        )
        return {
            "kb_id": kb["kb_id"],
            "collection_name": kb["collection_name"],
            "documents": active_doc_count,
            "chunks": chunk_count,
            "runtime_config": str(combined_paths["runtime_cfg"]),
            "embedding_path": runtime_cfg["embedding_path"],
        }

    def _iterate_jsonl_paths(
        self,
        docs: List[Dict[str, Any]],
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

    def _build_runtime_retriever_config(
        self,
        kb: Dict[str, Any],
        combined_paths: Dict[str, Path],
    ) -> Dict[str, Any]:
        cfg = load_yaml(kb["retriever_config_path"])
        cfg["corpus_path"] = str(combined_paths["chunk"])
        cfg["embedding_path"] = str(combined_paths["embedding"])
        cfg["collection_name"] = kb["collection_name"]
        cfg.setdefault("index_backend_configs", {})
        cfg["index_backend_configs"].setdefault("milvus", {})
        cfg["index_backend_configs"]["milvus"]["uri"] = kb["index_uri"]
        return cfg

    def _drop_collection(self, kb: Dict[str, Any]) -> None:
        cfg = self._build_runtime_retriever_config(kb, self._combined_paths(kb))
        milvus_backend = MilvusIndexBackend(
            contents=[],
            config=cfg.get("index_backend_configs", {}).get("milvus", {}),
            logger=retriever_app.logger,
        )
        try:
            milvus_backend.drop_collection(kb["collection_name"])
        finally:
            milvus_backend.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BizRAG knowledge-base admin")
    parser.add_argument(
        "--metadata-db",
        type=str,
        default="bizrag/state/metadata.db",
        help="SQLite metadata store path",
    )
    parser.add_argument(
        "--kb-registry",
        type=str,
        default="bizrag/config/kb_registry.yaml",
        help="KB registry yaml used by retrieve_api",
    )
    parser.add_argument(
        "--workspace-root",
        type=str,
        default="runtime/kbs",
        help="Workspace root for corpus/chunk/index artifacts",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register-kb")
    register.add_argument("--kb-id", required=True)
    register.add_argument("--retriever-config", required=True)
    register.add_argument("--collection-name")
    register.add_argument("--display-name")
    register.add_argument("--source-root")
    register.add_argument("--index-uri")

    ingest = subparsers.add_parser("ingest-path")
    ingest.add_argument("--kb-id", required=True)
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--sync-deletions", action="store_true")
    ingest.add_argument("--force", action="store_true")
    ingest.add_argument("--prefer-mineru", action="store_true")
    ingest.add_argument("--chunk-backend", default="sentence")
    ingest.add_argument("--chunk-size", type=int, default=512)
    ingest.add_argument("--chunk-overlap", type=int, default=50)

    delete = subparsers.add_parser("delete-document")
    delete.add_argument("--kb-id", required=True)
    delete.add_argument("--source-uri", required=True)

    rebuild = subparsers.add_parser("rebuild-kb")
    rebuild.add_argument("--kb-id", required=True)

    retry = subparsers.add_parser("retry-task")
    retry.add_argument("--task-id", required=True)

    list_docs = subparsers.add_parser("list-documents")
    list_docs.add_argument("--kb-id", required=True)
    list_docs.add_argument("--include-deleted", action="store_true")

    list_tasks = subparsers.add_parser("list-tasks")
    list_tasks.add_argument("--kb-id")
    list_tasks.add_argument("--limit", type=int, default=20)

    list_kbs = subparsers.add_parser("list-kbs")

    return parser.parse_args()


async def run_command(args: argparse.Namespace) -> Dict[str, Any]:
    admin = KBAdmin(
        metadata_db=args.metadata_db,
        kb_registry_path=args.kb_registry,
        workspace_root=args.workspace_root,
    )
    try:
        if args.command == "register-kb":
            return admin.register_kb(
                kb_id=args.kb_id,
                retriever_config_path=args.retriever_config,
                collection_name=args.collection_name,
                display_name=args.display_name,
                source_root=args.source_root,
                index_uri=args.index_uri,
            )
        if args.command == "ingest-path":
            return await admin.ingest_path(
                kb_id=args.kb_id,
                path=args.path,
                sync_deletions=args.sync_deletions,
                force=args.force,
                prefer_mineru=args.prefer_mineru,
                chunk_backend=args.chunk_backend,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
        if args.command == "delete-document":
            return await admin.delete_document(kb_id=args.kb_id, source_uri=args.source_uri)
        if args.command == "rebuild-kb":
            return await admin.rebuild_kb(kb_id=args.kb_id)
        if args.command == "retry-task":
            return await admin.retry_task(args.task_id)
        if args.command == "list-documents":
            return {
                "items": admin.store.list_documents(
                    args.kb_id,
                    include_deleted=args.include_deleted,
                )
            }
        if args.command == "list-tasks":
            return {"items": admin.store.list_tasks(kb_id=args.kb_id, limit=args.limit)}
        if args.command == "list-kbs":
            return {"items": admin.store.list_kbs()}
        raise RuntimeError(f"Unsupported command: {args.command}")
    finally:
        admin.close()


def main() -> None:
    args = parse_args()
    result = asyncio.run(run_command(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
