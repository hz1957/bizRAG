from __future__ import annotations

from typing import Any, Dict, List, Optional

from bizrag.contracts.schemas import DEFAULT_OUTPUT_FIELDS, RetrieveItem
from bizrag.infra.metadata_store import MetadataStore
from bizrag.service.ultrarag.pipeline_outputs import (
    extract_first_text_output,
    extract_retrieve_items,
)
from bizrag.service.ultrarag.pipeline_runner import UltraRAGPipelineRunner
from bizrag.service.ultrarag.read_pipeline_payload import build_read_pipeline_payload


class ReadService:
    def __init__(
        self,
        *,
        metadata_db: str,
        pipeline_runner: Optional[UltraRAGPipelineRunner] = None,
    ) -> None:
        self._metadata_db = metadata_db
        self._pipeline_runner = pipeline_runner or UltraRAGPipelineRunner()

    def health_status(self) -> str:
        return "ready"

    def reset(self) -> None:
        return None

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

    async def retrieve_items(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int,
        query_instruction: str,
        filters: Optional[Dict[str, Any]],
    ) -> List[RetrieveItem]:
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
        return [self._normalize_hit(hit, kb_id=kb_id) for hit in hits]

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
        return {
            "answer": extract_first_text_output(result, "pred_ls"),
            "raw_answer": extract_first_text_output(result, "ans_ls"),
            "citations": citations,
        }
