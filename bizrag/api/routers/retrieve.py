from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from bizrag.api.deps import get_retrieval_service
from bizrag.contracts.schemas import (
    ExtractFieldResult,
    ExtractRequest,
    ExtractResponse,
    RetrieveItem,
    RetrieveRequest,
    RetrieveResponse,
)
from bizrag.service.errors import ServiceError
from bizrag.service.extract_engine import extract_fields


router = APIRouter()


def _model_to_dict(item: BaseModel) -> Dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()


@router.get("/healthz")
async def healthz() -> Dict[str, str]:
    retrieval_service = get_retrieval_service()
    return {
        "status": "ok",
        "retriever": retrieval_service.health_status(),
    }


@router.post("/api/v1/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest) -> RetrieveResponse:
    retrieval_service = get_retrieval_service()
    try:
        items = await retrieval_service.retrieve_items(
            kb_id=req.kb_id,
            query=req.query,
            top_k=req.top_k,
            query_instruction=req.query_instruction,
            filters=req.filters,
        )
        return RetrieveResponse(items=items)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/v1/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest) -> ExtractResponse:
    retrieval_service = get_retrieval_service()
    try:
        evidence_items = await retrieval_service.retrieve_items(
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
