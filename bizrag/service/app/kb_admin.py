from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from bizrag.common.observability import observe_operation
from bizrag.infra.metadata_store import MetadataStore
from bizrag.common.io_utils import (
    load_jsonl,
    sha256_file,
    write_jsonl,
)
from bizrag.service.app.kb_artifacts import (
    build_passthrough_chunks,
    doc_key_for_source,
    document_paths,
    normalize_chunk_rows,
    normalize_corpus_rows,
)
from bizrag.service.app.kb_config import (
    materialize_kb_server_parameters,
    migrate_kb_server_parameters,
)
from bizrag.service.app.kb_files import (
    classify_source_type,
    discover_supported_files,
    normalize_source_uri,
    should_ingest,
)
from bizrag.service.app.kb_indexer import KBIndexManager
from bizrag.service.ultrarag.pipeline_runner import DEFAULT_PIPELINE_RUNNER
from bizrag.service.ultrarag.server_parameters import load_server_parameters

logger = logging.getLogger("bizrag.kb_admin")


class KBAdmin:
    def __init__(
        self,
        *,
        metadata_db: str | Path,
        workspace_root: str | Path,
    ) -> None:
        self.store = MetadataStore(metadata_db)
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._migrate_registered_kbs()
        self._indexer = KBIndexManager(store=self.store)

    def close(self) -> None:
        self.store.close()

    def _migrate_registered_kbs(self) -> None:
        for kb in self.store.list_kbs():
            migrated = migrate_kb_server_parameters(kb=kb)
            if migrated is None:
                continue
            self.store.register_kb(
                kb_id=migrated["kb_id"],
                collection_name=migrated["collection_name"],
                display_name=migrated.get("display_name"),
                source_root=migrated.get("source_root"),
                workspace_dir=migrated["workspace_dir"],
                retriever_config_path=migrated["retriever_config_path"],
                index_uri=migrated["index_uri"],
            )

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

        cfg = load_server_parameters(retriever_config_path)["retriever"]
        milvus_cfg = cfg.get("index_backend_configs", {}).get("milvus", {})
        resolved_collection = collection_name or kb_id
        resolved_index_uri = index_uri
        if not resolved_index_uri and str(cfg.get("index_backend") or "").lower() == "milvus":
            resolved_index_uri = milvus_cfg.get("uri")
        if str(cfg.get("index_backend") or "").lower() == "milvus" and not resolved_index_uri:
            raise RuntimeError(
                "Milvus backend requires retriever.index_backend_configs.milvus.uri or register-kb index_uri"
            )
        materialized_config_path = materialize_kb_server_parameters(
            source_parameters_path=retriever_config_path,
            workspace_dir=workspace_dir,
            collection_name=resolved_collection,
            index_uri=str(resolved_index_uri),
        )

        kb = self.store.register_kb(
            kb_id=kb_id,
            collection_name=resolved_collection,
            display_name=display_name,
            source_root=str(Path(source_root).resolve()) if source_root else None,
            workspace_dir=str(workspace_dir),
            retriever_config_path=str(materialized_config_path),
            index_uri=str(resolved_index_uri),
        )
        return kb

    def _get_kb(self, kb_id: str) -> Dict[str, Any]:
        kb = self.store.get_kb(kb_id)
        if kb is None:
            raise RuntimeError(f"Unknown kb_id: {kb_id}. Run register-kb first.")
        return kb

    async def ingest_file(
        self,
        *,
        kb_id: str,
        path: str,
        logical_source_uri: Optional[str],
        logical_file_name: Optional[str],
        force: bool,
        prefer_mineru: bool,
        chunk_backend: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> Dict[str, Any]:
        kb = self._get_kb(kb_id)
        file_path = Path(path).resolve()
        if not file_path.exists():
            raise RuntimeError(f"Input path not found: {file_path}")
        if not should_ingest(file_path):
            raise RuntimeError(f"Unsupported file type: {file_path}")
        source_uri = str(logical_source_uri or file_path)
        existing_doc = self.store.get_document(kb_id, source_uri)

        task_id = str(uuid.uuid4())
        self.store.create_task(
            task_id=task_id,
            kb_id=kb_id,
            task_type="ingest_file",
            status="running",
            source_uri=source_uri,
            payload={
                "path": str(file_path),
                "logical_source_uri": logical_source_uri,
                "logical_file_name": logical_file_name,
                "force": force,
                "prefer_mineru": prefer_mineru,
                "chunk_backend": chunk_backend,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            },
        )
        try:
            async with observe_operation(
                store=self.store,
                component="ingest",
                operation="ingest_file",
                kb_id=kb_id,
                task_id=task_id,
                source_uri=source_uri,
                details={"path": str(file_path), "force": force},
            ) as span:
                result_type = await self._upsert_file(
                    kb=kb,
                    file_path=file_path,
                    logical_source_uri=logical_source_uri,
                    logical_file_name=logical_file_name,
                    force=force,
                    prefer_mineru=prefer_mineru,
                    chunk_backend=chunk_backend,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                active_doc = self.store.get_document(kb_id, source_uri)
                index_mode = await self._indexer.sync_document_index(
                    kb=kb,
                    document=active_doc,
                    replace_existing=bool(existing_doc and existing_doc.get("status") == "active"),
                )
                result = {
                    "task_id": task_id,
                    "kb_id": kb_id,
                    "path": str(file_path),
                    "logical_source_uri": logical_source_uri or str(file_path),
                    "status": result_type,
                    "reindexed": True,
                    "index_mode": index_mode,
                }
                span.annotate(result_type=result_type, index_mode=index_mode)
                self.store.update_task(task_id, status="success", result=result)
                return result
        except Exception as exc:
            self._record_failed_file(
                kb=kb,
                file_path=file_path,
                error_message=str(exc),
                logical_source_uri=logical_source_uri,
                logical_file_name=logical_file_name,
            )
            self.store.update_task(task_id, status="failed", error_message=str(exc))
            raise

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
        changed_docs: List[Dict[str, Any]] = []
        replaced_doc_keys: List[str] = []
        deleted_docs: List[Dict[str, Any]] = []

        try:
            async with observe_operation(
                store=self.store,
                component="ingest",
                operation="ingest_path",
                kb_id=kb_id,
                task_id=task_id,
                source_uri=str(input_path),
                details={"path": str(input_path), "force": force, "sync_deletions": sync_deletions},
            ) as span:
                for file_path in files:
                    try:
                        existing_doc = self.store.get_document(kb["kb_id"], str(file_path.resolve()))
                        result = await self._upsert_file(
                            kb=kb,
                            file_path=file_path,
                            logical_source_uri=None,
                            logical_file_name=None,
                            force=force,
                            prefer_mineru=prefer_mineru,
                            chunk_backend=chunk_backend,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                        )
                        if result == "created":
                            created += 1
                            changed = True
                            active_doc = self.store.get_document(kb["kb_id"], str(file_path.resolve()))
                            if active_doc is not None:
                                changed_docs.append(active_doc)
                        elif result == "updated":
                            updated += 1
                            changed = True
                            if existing_doc is not None and existing_doc.get("status") == "active":
                                replaced_doc_keys.append(str(existing_doc["doc_key"]))
                            active_doc = self.store.get_document(kb["kb_id"], str(file_path.resolve()))
                            if active_doc is not None:
                                changed_docs.append(active_doc)
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
                        logger.warning(
                            "[kb_admin] Failed to ingest %s: %s",
                            file_path,
                            exc,
                        )

                if sync_deletions and input_path.is_dir():
                    deleted_docs = self._sync_deleted_documents(kb=kb, scanned_root=input_path, keep_paths=files)
                    deleted += len(deleted_docs)
                    if deleted_docs:
                        changed = True

                if changed or force:
                    index_mode = await self._indexer.sync_documents_index_batch(
                        kb=kb,
                        upsert_documents=changed_docs,
                        replace_doc_keys=replaced_doc_keys,
                        deleted_documents=deleted_docs,
                    )
                else:
                    index_mode = "noop"

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
                    "index_mode": index_mode,
                }
                if failed_items:
                    result["failed_items"] = failed_items
                span.annotate(
                    files_seen=len(files),
                    created=created,
                    updated=updated,
                    skipped=skipped,
                    failed=failed,
                    deleted=deleted,
                    index_mode=index_mode,
                )
                self.store.update_task(task_id, status="success", result=result)
                return result
        except Exception as exc:
            self.store.update_task(task_id, status="failed", error_message=str(exc))
            raise

    async def delete_document(self, *, kb_id: str, source_uri: str) -> Dict[str, Any]:
        kb = self._get_kb(kb_id)
        resolved_source = normalize_source_uri(source_uri)
        existing_doc = self.store.get_document(kb_id, resolved_source)
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
            index_mode = None
            if deleted:
                index_mode = await self._indexer.sync_deleted_document_index(
                    kb=kb,
                    deleted_doc=existing_doc,
                )
            result = {
                "task_id": task_id,
                "kb_id": kb_id,
                "source_uri": resolved_source,
                "deleted": deleted,
            }
            if index_mode:
                result["index_mode"] = index_mode
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
            result = await self._indexer.rebuild_kb(kb=kb)
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
        if task_type == "ingest_file":
            return await self.ingest_file(
                kb_id=task["kb_id"],
                path=str(payload["path"]),
                logical_source_uri=payload.get("logical_source_uri"),
                logical_file_name=payload.get("logical_file_name"),
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
        logical_source_uri: Optional[str],
        logical_file_name: Optional[str],
        force: bool,
        prefer_mineru: bool,
        chunk_backend: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> str:
        source_uri = str(logical_source_uri or file_path.resolve())
        file_name = str(logical_file_name or file_path.name)
        doc_key = doc_key_for_source(source_uri)
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

        output_paths = document_paths(kb, doc_key)
        raw_corpus_rows = await self._build_raw_corpus(
            file_path=file_path,
            output_paths=output_paths,
            prefer_mineru=prefer_mineru,
        )
        normalized_corpus = normalize_corpus_rows(
            raw_rows=raw_corpus_rows,
            kb_id=kb["kb_id"],
            source_path=file_path,
            logical_source_uri=source_uri,
            logical_file_name=file_name,
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
                await self._chunk_document(
                    raw_chunk_path=str(output_paths["corpus"]),
                    chunk_path=str(temp_chunk_path),
                    chunk_backend=chunk_backend,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                raw_chunk_rows = load_jsonl(temp_chunk_path)
            except Exception as exc:
                logger.warning(
                    "[kb_admin] chunk_documents failed for %s, fallback to passthrough chunks: %s",
                    file_path,
                    exc,
                )
                raw_chunk_rows = build_passthrough_chunks(
                    corpus_rows=normalized_corpus,
                    doc_key=doc_key,
                    source_path=file_path,
                    logical_source_uri=source_uri,
                    logical_file_name=file_name,
                    content_hash=content_hash,
                )
        finally:
            if temp_chunk_path.exists():
                temp_chunk_path.unlink()

        normalized_chunks = normalize_chunk_rows(
            raw_rows=raw_chunk_rows,
            doc_key=doc_key,
            source_path=file_path,
            logical_source_uri=source_uri,
            logical_file_name=file_name,
            content_hash=content_hash,
        )
        write_jsonl(output_paths["chunk"], normalized_chunks)

        self.store.upsert_document(
            kb_id=kb["kb_id"],
            source_uri=source_uri,
            doc_key=doc_key,
            file_name=file_name,
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
        logical_source_uri: Optional[str] = None,
        logical_file_name: Optional[str] = None,
    ) -> None:
        source_uri = str(logical_source_uri or file_path.resolve())
        file_name = str(logical_file_name or file_path.name)
        doc_key = doc_key_for_source(source_uri)
        content_hash = sha256_file(file_path) if file_path.exists() else ""
        source_type = classify_source_type(file_path) or ""
        self.store.upsert_document(
            kb_id=kb["kb_id"],
            source_uri=source_uri,
            doc_key=doc_key,
            file_name=file_name,
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
        if suffix in {".xls", ".xlsx"}:
            await DEFAULT_PIPELINE_RUNNER.run(
                "build_excel_corpus",
                params={
                    "biz_corpus": {
                        "parse_file_path": str(file_path),
                        "text_corpus_save_path": str(output_paths["corpus"]),
                        "sheet_mode": "row",
                        "include_header": True,
                    }
                },
            )
            return load_jsonl(output_paths["corpus"])

        if suffix == ".pdf" and prefer_mineru:
            await DEFAULT_PIPELINE_RUNNER.run(
                "build_mineru_corpus",
                params={
                    "corpus": {
                        "parse_file_path": str(file_path),
                        "mineru_dir": str(output_paths["mineru"]),
                        "mineru_extra_params": None,
                        "text_corpus_save_path": str(output_paths["corpus"]),
                        "image_corpus_save_path": str(
                            output_paths["images"].with_suffix(".jsonl")
                        ),
                    }
                },
            )
            return load_jsonl(output_paths["corpus"])

        await DEFAULT_PIPELINE_RUNNER.run(
            "build_text_corpus",
            params={
                "corpus": {
                    "parse_file_path": str(file_path),
                    "text_corpus_save_path": str(output_paths["corpus"]),
                }
            },
        )
        return load_jsonl(output_paths["corpus"])

    async def _chunk_document(
        self,
        *,
        raw_chunk_path: str,
        chunk_path: str,
        chunk_backend: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        await DEFAULT_PIPELINE_RUNNER.run(
            "corpus_chunk",
            params={
                "corpus": {
                    "raw_chunk_path": raw_chunk_path,
                    "chunk_path": chunk_path,
                    "chunk_backend": chunk_backend,
                    "chunk_size": chunk_size,
                    "use_title": True,
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

    def _sync_deleted_documents(
        self,
        *,
        kb: Dict[str, Any],
        scanned_root: Path,
        keep_paths: List[Path],
    ) -> List[Dict[str, Any]]:
        keep_uris = {str(path.resolve()) for path in keep_paths}
        prefix = str(scanned_root.resolve())
        if not prefix.endswith(os.sep):
            prefix = f"{prefix}{os.sep}"
        deleted_docs: List[Dict[str, Any]] = []
        for doc in self.store.list_documents(kb["kb_id"], include_deleted=False, source_prefix=prefix):
            if str(doc["source_uri"]) not in keep_uris:
                if self._mark_deleted(kb_id=kb["kb_id"], source_uri=str(doc["source_uri"])):
                    deleted_docs.append(doc)
        return deleted_docs

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
