from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from bizrag.contracts.schemas import DEFAULT_OUTPUT_FIELDS, RetrieveItem
from bizrag.service.errors import ServiceUnavailableError
from bizrag.service.kb_registry import KBRegistry
from bizrag.servers.retriever.retriever import Retriever, app as retriever_app


class RetrievalService:
    def __init__(
        self,
        *,
        retriever_cfg: Dict[str, Any],
        kb_registry: KBRegistry,
    ) -> None:
        self._retriever_cfg = retriever_cfg
        self._kb_registry = kb_registry
        self._retriever: Optional[Retriever] = None
        self._retriever_ready = False
        self._retriever_init_lock = asyncio.Lock()

    def health_status(self) -> str:
        return "ready" if self._retriever_ready else "lazy"

    def reset(self) -> None:
        self._retriever = None
        self._retriever_ready = False

    @staticmethod
    def _normalize_hit(hit: Dict[str, Any], *, kb_id: str) -> RetrieveItem:
        known_keys = {
            "content",
            "score",
            "doc_id",
            "title",
            "file_name",
            "source_type",
            "sheet_name",
            "row_index",
            "kb_id",
            "doc_version",
            "source_uri",
        }
        metadata = {k: v for k, v in hit.items() if k not in known_keys}
        return RetrieveItem(
            content=str(hit.get("content") or ""),
            score=float(hit["score"]) if hit.get("score") is not None else None,
            doc_id=str(hit["doc_id"]) if hit.get("doc_id") is not None else None,
            title=str(hit["title"]) if hit.get("title") is not None else None,
            file_name=str(hit["file_name"]) if hit.get("file_name") is not None else None,
            source_type=str(hit["source_type"]) if hit.get("source_type") is not None else None,
            sheet_name=str(hit["sheet_name"]) if hit.get("sheet_name") is not None else None,
            row_index=int(hit["row_index"]) if hit.get("row_index") is not None else None,
            kb_id=str(hit.get("kb_id") or kb_id),
            doc_version=str(hit["doc_version"]) if hit.get("doc_version") is not None else None,
            source_uri=str(hit["source_uri"]) if hit.get("source_uri") is not None else None,
            metadata=metadata,
        )

    async def _ensure_retriever(self) -> Retriever:
        if self._retriever_ready:
            if self._retriever is None:
                raise ServiceUnavailableError("Retriever is not initialized")
            return self._retriever

        async with self._retriever_init_lock:
            if self._retriever_ready:
                if self._retriever is None:
                    raise ServiceUnavailableError("Retriever is not initialized")
                return self._retriever
            if self._retriever is None:
                self._retriever = Retriever(retriever_app)
            await self._retriever.retriever_init(
                model_name_or_path=self._retriever_cfg["model_name_or_path"],
                backend_configs=self._retriever_cfg["backend_configs"],
                batch_size=self._retriever_cfg.get("batch_size", 32),
                corpus_path=self._retriever_cfg.get("corpus_path", ""),
                gpu_ids=self._retriever_cfg.get("gpu_ids"),
                is_multimodal=self._retriever_cfg.get("is_multimodal", False),
                backend=self._retriever_cfg.get("backend", "sentence_transformers"),
                index_backend=self._retriever_cfg.get("index_backend", "faiss"),
                index_backend_configs=self._retriever_cfg.get("index_backend_configs", {}),
                is_demo=self._retriever_cfg.get("is_demo", False),
                collection_name=self._retriever_cfg.get("collection_name", ""),
            )
            self._retriever_ready = True
        return self._retriever

    async def retrieve_items(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int,
        query_instruction: str,
        filters: Optional[Dict[str, Any]],
    ) -> List[RetrieveItem]:
        active_retriever = await self._ensure_retriever()
        collection_name = self._kb_registry.resolve(kb_id)
        rets = await active_retriever.retriever_search_structured(
            query_list=[query],
            top_k=top_k,
            query_instruction=query_instruction,
            collection_name=collection_name,
            filters=filters or None,
            output_fields=DEFAULT_OUTPUT_FIELDS,
        )
        first_row = rets.get("ret_items", [[]])[0]
        return [self._normalize_hit(hit, kb_id=kb_id) for hit in first_row]
