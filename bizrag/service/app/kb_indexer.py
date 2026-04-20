from __future__ import annotations

import logging
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from bizrag.common.observability import observe_operation
from bizrag.infra.metadata_store import MetadataStore
from bizrag.common.io_utils import load_jsonl, write_jsonl
from bizrag.service.ultrarag.pipeline_outputs import extract_int_output
from bizrag.service.ultrarag.pipeline_runner import DEFAULT_PIPELINE_RUNNER
from bizrag.service.app.kb_artifacts import combined_paths, iter_jsonl_paths
from bizrag.service.app.kb_config import load_kb_retriever_parameters

logger = logging.getLogger("bizrag.kb_admin")


class KBIndexManager:
    def __init__(self, *, store: MetadataStore) -> None:
        self._store = store

    def _runtime_cfg(self, kb: Dict[str, Any]) -> Dict[str, Any]:
        return load_kb_retriever_parameters(str(kb["retriever_config_path"]))

    @staticmethod
    def _retriever_params(runtime_cfg: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
        retriever_cfg = dict(runtime_cfg)
        retriever_params = {
            "model_name_or_path": retriever_cfg["model_name_or_path"],
            "backend_configs": retriever_cfg["backend_configs"],
            "batch_size": retriever_cfg.get("batch_size", 32),
            "corpus_path": retriever_cfg["corpus_path"],
            "embedding_path": retriever_cfg["embedding_path"],
            "gpu_ids": retriever_cfg.get("gpu_ids"),
            "is_multimodal": retriever_cfg.get("is_multimodal", False),
            "backend": retriever_cfg.get("backend", "sentence_transformers"),
            "index_backend": retriever_cfg.get("index_backend", "milvus"),
            "index_backend_configs": retriever_cfg.get("index_backend_configs", {}),
            "is_demo": retriever_cfg.get("is_demo", False),
            "collection_name": retriever_cfg["collection_name"],
            "overwrite": False,
        }
        retriever_params.update(extra)
        return {"retriever": retriever_params}

    @staticmethod
    def _bm25_params(runtime_cfg: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
        retriever_cfg = dict(runtime_cfg)
        retriever_params = {
            "model_name_or_path": retriever_cfg["model_name_or_path"],
            "backend_configs": retriever_cfg["backend_configs"],
            "batch_size": retriever_cfg.get("batch_size", 32),
            "corpus_path": retriever_cfg["corpus_path"],
            "gpu_ids": retriever_cfg.get("gpu_ids"),
            "is_multimodal": retriever_cfg.get("is_multimodal", False),
            "backend": "bm25",
            "index_backend": retriever_cfg.get("index_backend", "milvus"),
            "index_backend_configs": retriever_cfg.get("index_backend_configs", {}),
            "is_demo": retriever_cfg.get("is_demo", False),
            "collection_name": retriever_cfg["collection_name"],
            "overwrite": False,
        }
        retriever_params.update(extra)
        return {"retriever": retriever_params}

    async def _build_index(
        self,
        *,
        runtime_cfg: Dict[str, Any],
        corpus_path: str,
        embedding_path: str,
        overwrite: bool,
        collection_name: str,
    ) -> None:
        async with observe_operation(
            store=self._store,
            component="index",
            operation="milvus_index",
            kb_id=collection_name,
            details={"corpus_path": corpus_path, "overwrite": overwrite},
        ):
            await DEFAULT_PIPELINE_RUNNER.run(
                "milvus_index",
                params=self._retriever_params(
                    runtime_cfg,
                    corpus_path=corpus_path,
                    embedding_path=embedding_path,
                    overwrite=overwrite,
                    collection_name=collection_name,
                ),
            )

    async def _build_bm25_index(
        self,
        *,
        runtime_cfg: Dict[str, Any],
        corpus_path: str,
        overwrite: bool,
    ) -> None:
        async with observe_operation(
            store=self._store,
            component="index",
            operation="bm25_index",
            kb_id=str(runtime_cfg.get("collection_name") or ""),
            details={"corpus_path": corpus_path, "overwrite": overwrite},
        ):
            await DEFAULT_PIPELINE_RUNNER.run(
                "bm25_index",
                params=self._bm25_params(
                    runtime_cfg,
                    corpus_path=corpus_path,
                    overwrite=overwrite,
                ),
            )

    async def _delete_doc_key(
        self,
        *,
        runtime_cfg: Dict[str, Any],
        collection_name: str,
        doc_key: str,
    ) -> int:
        result = await DEFAULT_PIPELINE_RUNNER.run(
            "milvus_delete",
            params=self._retriever_params(
                runtime_cfg,
                filter_expr=f"doc_key == {json.dumps(doc_key, ensure_ascii=False)}",
                collection_name=collection_name,
            ),
        )
        return extract_int_output(result, "deleted_count", default=0)

    async def _drop_collection_with_runtime(
        self,
        *,
        runtime_cfg: Dict[str, Any],
        collection_name: str,
    ) -> None:
        await DEFAULT_PIPELINE_RUNNER.run(
            "milvus_drop_collection",
            params=self._retriever_params(
                runtime_cfg,
                collection_name=collection_name,
            ),
        )

    def refresh_combined_artifacts(
        self,
        kb: Dict[str, Any],
    ) -> tuple[list[Dict[str, Any]], Dict[str, Path], Dict[str, Any]]:
        paths = combined_paths(kb)
        active_docs = self._store.list_documents(kb["kb_id"], include_deleted=False)
        write_jsonl(paths["corpus"], iter_jsonl_paths(active_docs, "corpus_path"))
        write_jsonl(paths["chunk"], iter_jsonl_paths(active_docs, "chunk_path"))
        runtime_cfg = self._runtime_cfg(kb)
        return active_docs, paths, runtime_cfg

    @staticmethod
    def _clear_bm25_artifacts(paths: Dict[str, Path]) -> None:
        bm25_path = paths["bm25"]
        if bm25_path.is_dir():
            shutil.rmtree(bm25_path)
        elif bm25_path.exists():
            bm25_path.unlink()

    async def sync_document_index(
        self,
        *,
        kb: Dict[str, Any],
        document: Optional[Dict[str, Any]],
        replace_existing: bool,
    ) -> str:
        async with observe_operation(
            store=self._store,
            component="index",
            operation="sync_document_index",
            kb_id=str(kb["kb_id"]),
            source_uri=str(document.get("source_uri") or "") if document else None,
            details={"replace_existing": replace_existing},
        ) as span:
            active_docs, paths, runtime_cfg = self.refresh_combined_artifacts(kb)
            if document is None or document.get("status") != "active":
                if not active_docs:
                    self._clear_bm25_artifacts(paths)
                    await self._drop_collection(kb)
                    span.annotate(mode="drop_collection")
                    return "drop_collection"
                await self.rebuild_kb(kb=kb)
                span.annotate(mode="full_rebuild")
                return "full_rebuild"

            try:
                if replace_existing:
                    await self._delete_document_from_index(
                        kb=kb,
                        doc_key=str(document["doc_key"]),
                    )
                await self._index_documents_incremental(
                    kb=kb,
                    documents=[document],
                    runtime_cfg=runtime_cfg,
                )
                await self._build_bm25_index(
                    runtime_cfg=runtime_cfg,
                    corpus_path=runtime_cfg["corpus_path"],
                    overwrite=True,
                )
                span.annotate(mode="incremental")
                return "incremental"
            except Exception as exc:
                logger.warning(
                    "[kb_admin] Incremental index failed for %s, fallback to full rebuild: %s",
                    document.get("source_uri"),
                    exc,
                )
                await self.rebuild_kb(kb=kb)
                span.annotate(mode="full_rebuild")
                return "full_rebuild"

    async def sync_documents_index_batch(
        self,
        *,
        kb: Dict[str, Any],
        upsert_documents: list[Dict[str, Any]],
        replace_doc_keys: list[str],
        deleted_documents: list[Dict[str, Any]],
    ) -> str:
        active_docs, paths, runtime_cfg = self.refresh_combined_artifacts(kb)
        if not active_docs:
            self._clear_bm25_artifacts(paths)
            await self._drop_collection(kb)
            return "drop_collection"

        delete_doc_keys = {
            str(doc["doc_key"])
            for doc in deleted_documents
            if doc is not None and doc.get("doc_key")
        }
        delete_doc_keys.update(key for key in replace_doc_keys if key)

        dedup_upserts: Dict[str, Dict[str, Any]] = {}
        for doc in upsert_documents:
            if doc is None or doc.get("status") != "active" or not doc.get("doc_key"):
                continue
            dedup_upserts[str(doc["doc_key"])] = doc

        try:
            for doc_key in sorted(delete_doc_keys):
                await self._delete_document_from_index(kb=kb, doc_key=doc_key)
            if dedup_upserts:
                await self._index_documents_incremental(
                    kb=kb,
                    documents=list(dedup_upserts.values()),
                    runtime_cfg=runtime_cfg,
                )
            await self._build_bm25_index(
                runtime_cfg=runtime_cfg,
                corpus_path=runtime_cfg["corpus_path"],
                overwrite=True,
            )
            return "incremental_batch"
        except Exception as exc:
            logger.warning(
                "[kb_admin] Batch incremental index failed for kb=%s, fallback to full rebuild: %s",
                kb.get("kb_id"),
                exc,
            )
            await self.rebuild_kb(kb=kb)
            return "full_rebuild"

    async def sync_deleted_document_index(
        self,
        *,
        kb: Dict[str, Any],
        deleted_doc: Optional[Dict[str, Any]],
    ) -> str:
        active_docs, paths, runtime_cfg = self.refresh_combined_artifacts(kb)
        if not active_docs:
            self._clear_bm25_artifacts(paths)
            await self._drop_collection(kb)
            return "drop_collection"
        if deleted_doc is None:
            await self.rebuild_kb(kb=kb)
            return "full_rebuild"

        try:
            await self._delete_document_from_index(
                kb=kb,
                doc_key=str(deleted_doc["doc_key"]),
            )
            await self._build_bm25_index(
                runtime_cfg=runtime_cfg,
                corpus_path=runtime_cfg["corpus_path"],
                overwrite=True,
            )
            return "incremental"
        except Exception as exc:
            logger.warning(
                "[kb_admin] Incremental delete failed for %s, fallback to full rebuild: %s",
                deleted_doc.get("source_uri"),
                exc,
            )
            await self.rebuild_kb(kb=kb)
            return "full_rebuild"

    async def rebuild_kb(self, *, kb: Dict[str, Any]) -> Dict[str, Any]:
        async with observe_operation(
            store=self._store,
            component="index",
            operation="rebuild_kb",
            kb_id=str(kb["kb_id"]),
        ) as span:
            paths = combined_paths(kb)
            active_docs = self._store.list_documents(kb["kb_id"], include_deleted=False)

            write_jsonl(paths["corpus"], iter_jsonl_paths(active_docs, "corpus_path"))
            write_jsonl(paths["chunk"], iter_jsonl_paths(active_docs, "chunk_path"))

            active_doc_count = len(active_docs)
            chunk_count = sum(1 for _ in iter_jsonl_paths(active_docs, "chunk_path"))
            if chunk_count == 0:
                self._clear_bm25_artifacts(paths)
                await self._drop_collection(kb)
                span.annotate(documents=active_doc_count, chunks=0, dropped_collection=True)
                return {
                    "kb_id": kb["kb_id"],
                    "collection_name": kb["collection_name"],
                    "documents": active_doc_count,
                    "chunks": 0,
                    "dropped_collection": True,
                }

            runtime_cfg = self._runtime_cfg(kb)

            await self._build_index(
                runtime_cfg=runtime_cfg,
                corpus_path=runtime_cfg["corpus_path"],
                embedding_path=runtime_cfg["embedding_path"],
                overwrite=True,
                collection_name=kb["collection_name"],
            )
            await self._build_bm25_index(
                runtime_cfg=runtime_cfg,
                corpus_path=runtime_cfg["corpus_path"],
                overwrite=True,
            )
            span.annotate(documents=active_doc_count, chunks=chunk_count)
            return {
                "kb_id": kb["kb_id"],
                "collection_name": kb["collection_name"],
                "documents": active_doc_count,
                "chunks": chunk_count,
                "embedding_path": runtime_cfg["embedding_path"],
            }

    async def _index_documents_incremental(
        self,
        *,
        kb: Dict[str, Any],
        documents: list[Dict[str, Any]],
        runtime_cfg: Dict[str, Any],
    ) -> None:
        if not documents:
            return

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as corpus_file:
            batch_chunk_path = Path(corpus_file.name)
        try:
            rows: list[Dict[str, Any]] = []
            for document in documents:
                chunk_path = str(document.get("chunk_path") or "")
                if not chunk_path or not Path(chunk_path).exists():
                    raise RuntimeError(
                        f"Chunk file not found for incremental index: {chunk_path}"
                    )
                rows.extend(load_jsonl(chunk_path))
            write_jsonl(batch_chunk_path, rows)

            with tempfile.TemporaryDirectory(prefix="bizrag_inc_embed_") as temp_dir:
                embedding_path = str(Path(temp_dir) / "embeddings.npy")
                await self._build_index(
                    runtime_cfg=runtime_cfg,
                    corpus_path=str(batch_chunk_path),
                    embedding_path=embedding_path,
                    overwrite=False,
                    collection_name=kb["collection_name"],
                )
        finally:
            batch_chunk_path.unlink(missing_ok=True)

    async def _delete_document_from_index(
        self,
        *,
        kb: Dict[str, Any],
        doc_key: str,
    ) -> int:
        return await self._delete_doc_key(
            runtime_cfg=self._runtime_cfg(kb),
            collection_name=kb["collection_name"],
            doc_key=doc_key,
        )

    async def _drop_collection(self, kb: Dict[str, Any]) -> None:
        await self._drop_collection_with_runtime(
            runtime_cfg=self._runtime_cfg(kb),
            collection_name=kb["collection_name"],
        )
