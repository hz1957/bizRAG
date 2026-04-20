from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bizrag.api.deps import get_read_service, require_admin
from bizrag.common.observability import observe_operation
from bizrag.contracts.schemas import (
    ExtractFieldResult,
    ExtractRequest,
    ExtractResponse,
    RAGRequest,
    RAGResponse,
    RetrieveItem,
    RetrieveRequest,
    RetrieveResponse,
)
from bizrag.common.errors import ServiceError
from bizrag.service.app.extract_engine import extract_fields


router = APIRouter()


def _model_to_dict(item: BaseModel) -> Dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()


def _truncate_text(value: Any, limit: int = 280) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _summarize_retrieve_items(items: list[RetrieveItem], *, limit: int = 5) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in items[:limit]:
        summary.append(
            {
                "title": item.title or item.file_name or item.doc_id,
                "file_name": item.file_name,
                "sheet_name": item.sheet_name,
                "row_index": item.row_index,
                "score": item.score,
                "content": _truncate_text(item.content, 220),
            }
        )
    return summary


@router.get("/healthz")
async def healthz(request: Request) -> Dict[str, str]:
    read_service = get_read_service(request)
    retriever_status = read_service.health_status()
    return {
        "status": "ok" if retriever_status == "ready" else retriever_status,
        "retriever": retriever_status,
    }


@router.get("/livez")
async def livez(request: Request) -> Dict[str, str]:
    read_service = get_read_service(request)
    return {
        "status": "ok",
        "retriever": read_service.health_status(),
    }


@router.get("/readyz")
async def readyz(request: Request) -> Dict[str, str]:
    read_service = get_read_service(request)
    retriever_status = read_service.health_status()
    return {
        "status": "ok" if retriever_status == "ready" else retriever_status,
        "retriever": retriever_status,
    }


@router.post("/api/v1/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest, request: Request) -> RetrieveResponse:
    read_service = get_read_service(request)
    admin = require_admin(request)
    try:
        async with observe_operation(
            store=admin.store,
            component="api",
            operation="retrieve_endpoint",
            kb_id=req.kb_id,
            details={
                "request": {
                    "kb_id": req.kb_id,
                    "query": req.query,
                    "top_k": req.top_k,
                    "query_instruction": req.query_instruction,
                    "filters": req.filters,
                }
            },
        ) as span:
            items = await read_service.retrieve_items(
                kb_id=req.kb_id,
                query=req.query,
                top_k=req.top_k,
                query_instruction=req.query_instruction,
                filters=req.filters,
            )
            span.annotate(
                item_count=len(items),
                response={
                    "item_count": len(items),
                    "items": _summarize_retrieve_items(items),
                },
            )
            return RetrieveResponse(items=items)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/v1/rag", response_model=RAGResponse)
async def rag(req: RAGRequest, request: Request) -> RAGResponse:
    read_service = get_read_service(request)
    admin = require_admin(request)
    try:
        async with observe_operation(
            store=admin.store,
            component="api",
            operation="rag_endpoint",
            kb_id=req.kb_id,
            details={
                "request": {
                    "kb_id": req.kb_id,
                    "query": req.query,
                    "top_k": req.top_k,
                    "query_instruction": req.query_instruction,
                    "filters": req.filters,
                    "system_prompt": req.system_prompt,
                }
            },
        ) as span:
            result = await read_service.generate_answer(
                kb_id=req.kb_id,
                query=req.query,
                top_k=req.top_k,
                query_instruction=req.query_instruction,
                filters=req.filters,
                system_prompt=req.system_prompt,
            )
            span.annotate(
                citation_count=len(result.get("citations") or []),
                answer_chars=len(str(result.get("answer") or "")),
                response={
                    "answer": _truncate_text(result.get("answer"), 1200),
                    "citation_count": len(result.get("citations") or []),
                    "citations": _summarize_retrieve_items(result.get("citations") or []),
                },
            )
            return RAGResponse(**result)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/v1/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest, request: Request) -> ExtractResponse:
    read_service = get_read_service(request)
    admin = require_admin(request)
    try:
        async with observe_operation(
            store=admin.store,
            component="extract",
            operation="extract_fields",
            kb_id=req.kb_id,
            details={"query": req.query, "field_count": len(req.fields), "top_k": req.top_k},
        ) as span:
            evidence_items = await read_service.retrieve_items(
                kb_id=req.kb_id,
                query=req.query,
                top_k=req.top_k,
                query_instruction=req.query_instruction,
                filters=req.filters,
            )
            extraction = extract_fields(
                fields=[_model_to_dict(field) for field in req.fields],
                evidence_items=[_model_to_dict(item) for item in evidence_items],
                max_evidence_per_field=req.max_evidence_per_field,
            )
            field_results = [
                ExtractFieldResult(
                    name=str(item["name"]),
                    value=item.get("value"),
                    raw_value=item.get("raw_value"),
                    status=str(item.get("status") or "missing"),
                    confidence=float(item.get("confidence") or 0.0),
                    reason=str(item.get("reason") or ""),
                    evidence=[RetrieveItem(**evidence) for evidence in item.get("evidence", [])],
                )
                for item in extraction["field_results"]
            ]
            citations = [RetrieveItem(**item) for item in extraction["citations"]]
            span.annotate(
                evidence_count=len(evidence_items),
                citation_count=len(citations),
                missing_required=len(extraction.get("missing_required_fields", [])),
            )
            return ExtractResponse(
                result=extraction["result"],
                field_results=field_results,
                citations=citations,
                status=str(extraction["status"]),
                missing_required_fields=list(extraction.get("missing_required_fields", [])),
            )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
