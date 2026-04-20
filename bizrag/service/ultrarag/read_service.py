from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from bizrag.common.observability import observe_operation
from bizrag.contracts.schemas import DEFAULT_OUTPUT_FIELDS, RetrieveItem
from bizrag.infra.metadata_store import MetadataStore
from bizrag.service.ultrarag.pipeline_outputs import (
    extract_first_text_output,
    extract_retrieve_items,
)
from bizrag.service.ultrarag.pipeline_runner import UltraRAGPipelineRunner
from bizrag.service.ultrarag.read_pipeline_payload import build_read_pipeline_payload


logger = logging.getLogger("bizrag.read_service")


class ReadService:
    def __init__(
        self,
        *,
        metadata_db: str,
        pipeline_runner: Optional[UltraRAGPipelineRunner] = None,
    ) -> None:
        self._metadata_db = metadata_db
        self._pipeline_runner = pipeline_runner or UltraRAGPipelineRunner()
        self._health_status = "starting"
        self._warmup_error: Optional[str] = None

    def health_status(self) -> str:
        return self._health_status

    def mark_ready(self) -> None:
        self._warmup_error = None
        self._health_status = "ready"

    async def reset(self) -> None:
        self._health_status = "stopped"
        await self._pipeline_runner.close()

    def _get_kb(self, kb_id: str) -> Dict[str, Any]:
        store = MetadataStore(self._metadata_db)
        try:
            kb = store.get_kb(kb_id)
        finally:
            store.close()
        if kb is None:
            raise RuntimeError(f"Unknown kb_id: {kb_id}. Run register-kb first.")
        return kb

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

    @staticmethod
    def _truncate_text(value: Any, limit: int = 280) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    @classmethod
    def _summarize_items(cls, items: List[RetrieveItem], *, limit: int = 5) -> List[Dict[str, Any]]:
        summary: List[Dict[str, Any]] = []
        for item in items[:limit]:
            summary.append(
                {
                    "title": item.title or item.file_name or item.doc_id,
                    "file_name": item.file_name,
                    "sheet_name": item.sheet_name,
                    "row_index": item.row_index,
                    "score": item.score,
                    "content": cls._truncate_text(item.content, 220),
                }
            )
        return summary

    def _read_pipeline_payload(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int,
        query_instruction: str,
        filters: Optional[Dict[str, Any]],
        system_prompt: str = "",
    ) -> Dict[str, Any]:
        kb = self._get_kb(kb_id)
        return build_read_pipeline_payload(
            server_parameters_path=str(kb["retriever_config_path"]),
            query=query,
            top_k=top_k,
            query_instruction=query_instruction,
            filters=filters or {},
            output_fields=list(DEFAULT_OUTPUT_FIELDS),
            system_prompt=system_prompt,
        )

    def _list_warmup_kb_ids(self) -> Tuple[List[str], List[str]]:
        store = MetadataStore(self._metadata_db)
        try:
            warmup_kb_ids: List[str] = []
            skipped_kb_ids: List[str] = []
            for kb in store.list_kbs():
                kb_id = str(kb["kb_id"])
                counts = store.count_documents_by_status(kb_id)
                active_count = int(counts.get("active") or 0)
                if active_count > 0:
                    warmup_kb_ids.append(kb_id)
                else:
                    skipped_kb_ids.append(kb_id)
            return warmup_kb_ids, skipped_kb_ids
        finally:
            store.close()

    async def warmup(
        self,
        *,
        mode: str = "all",
        kb_ids: Optional[List[str]] = None,
        warm_generation_session: bool = True,
    ) -> None:
        normalized_mode = str(mode or "all").strip().lower()
        if normalized_mode not in {"all", "first", "none"}:
            raise RuntimeError(
                f"Unsupported warmup mode: {mode!r}. Expected one of: all, first, none."
            )

        self._health_status = "warming"
        self._warmup_error = None

        try:
            await self._pipeline_runner.warmup("retrieve_classic")
            if warm_generation_session:
                await self._pipeline_runner.warmup("rag_answer")

            if kb_ids:
                target_kb_ids = list(kb_ids)
                skipped_kb_ids: List[str] = []
            else:
                target_kb_ids, skipped_kb_ids = self._list_warmup_kb_ids()
                if skipped_kb_ids:
                    logger.info(
                        "[read_service] Skipping warmup for %d KB(s) without active documents: %s",
                        len(skipped_kb_ids),
                        ", ".join(skipped_kb_ids),
                    )

            if normalized_mode == "none" or not target_kb_ids:
                self._health_status = "ready"
                return
            if normalized_mode == "first":
                target_kb_ids = target_kb_ids[:1]

            for kb_id in target_kb_ids:
                try:
                    await self._pipeline_runner.run(
                        "retrieve_classic",
                        params=self._read_pipeline_payload(
                            kb_id=kb_id,
                            query="warmup",
                            top_k=1,
                            query_instruction="",
                            filters={},
                        ),
                    )
                    logger.info("[read_service] Warmup completed for kb_id=%s", kb_id)
                except Exception as exc:
                    self._warmup_error = str(exc)
                    self._health_status = "degraded"
                    logger.exception(
                        "[read_service] Warmup failed for kb_id=%s: %s",
                        kb_id,
                        exc,
                    )
                    return

            if warm_generation_session and target_kb_ids:
                warmup_kb_id = target_kb_ids[0]
                await self._pipeline_runner.run(
                    "rag_answer",
                    params=self._read_pipeline_payload(
                        kb_id=warmup_kb_id,
                        query="warmup",
                        top_k=1,
                        query_instruction="",
                        filters={},
                        system_prompt="Reply with OK only.",
                    ),
                )
                logger.info(
                    "[read_service] Generation warmup completed for kb_id=%s",
                    warmup_kb_id,
                )

            self._health_status = "ready"
        except Exception as exc:
            self._warmup_error = str(exc)
            self._health_status = "degraded"
            logger.exception("[read_service] Startup warmup failed: %s", exc)
            raise

    async def retrieve_items(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int,
        query_instruction: str,
        filters: Optional[Dict[str, Any]],
    ) -> List[RetrieveItem]:
        store = MetadataStore(self._metadata_db)
        try:
            async with observe_operation(
                store=store,
                component="retrieve",
                operation="retrieve_items",
                kb_id=kb_id,
                details={
                    "request": {
                        "kb_id": kb_id,
                        "query": query,
                        "top_k": top_k,
                        "query_instruction": query_instruction,
                        "filters": filters or {},
                    }
                },
            ) as span:
                result = await self._pipeline_runner.run(
                    "retrieve_classic",
                    params=self._read_pipeline_payload(
                        kb_id=kb_id,
                        query=query,
                        top_k=top_k,
                        query_instruction=query_instruction,
                        filters=filters,
                    ),
                )
                hits = extract_retrieve_items(result)
                normalized_hits = [self._normalize_hit(hit, kb_id=kb_id) for hit in hits]
                span.annotate(
                    hit_count=len(normalized_hits),
                    response={
                        "item_count": len(normalized_hits),
                        "items": self._summarize_items(normalized_hits),
                    },
                )
                return normalized_hits
        finally:
            store.close()

    async def generate_answer(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int,
        query_instruction: str,
        filters: Optional[Dict[str, Any]],
        system_prompt: str = "",
    ) -> Dict[str, Any]:
        store = MetadataStore(self._metadata_db)
        try:
            async with observe_operation(
                store=store,
                component="retrieve",
                operation="rag_answer",
                kb_id=kb_id,
                details={
                    "request": {
                        "kb_id": kb_id,
                        "query": query,
                        "top_k": top_k,
                        "query_instruction": query_instruction,
                        "filters": filters or {},
                        "system_prompt": system_prompt,
                    }
                },
            ) as span:
                result = await self._pipeline_runner.run(
                    "rag_answer",
                    params=self._read_pipeline_payload(
                        kb_id=kb_id,
                        query=query,
                        top_k=top_k,
                        query_instruction=query_instruction,
                        filters=filters,
                        system_prompt=system_prompt,
                    ),
                )
                citations = [
                    self._normalize_hit(hit, kb_id=kb_id)
                    for hit in extract_retrieve_items(result)
                ]
                answer = extract_first_text_output(result, "ans_ls")
                span.annotate(
                    citation_count=len(citations),
                    answer_chars=len(answer),
                    response={
                        "answer": self._truncate_text(answer, 1200),
                        "citation_count": len(citations),
                        "citations": self._summarize_items(citations),
                    },
                )
                return {
                    "answer": answer,
                    "raw_answer": extract_first_text_output(result, "ans_ls"),
                    "citations": citations,
                }
        finally:
            store.close()
