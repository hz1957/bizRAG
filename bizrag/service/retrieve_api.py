from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RETRIEVER_SRC = PROJECT_ROOT / "bizrag" / "src" / "servers" / "retriever" / "src"
if str(RETRIEVER_SRC) not in sys.path:
    sys.path.insert(0, str(RETRIEVER_SRC))

from bizrag.src.service.extract_engine import extract_fields  # noqa: E402
from retriever import Retriever, app as retriever_app  # noqa: E402


DEFAULT_OUTPUT_FIELDS = [
    "doc_id",
    "title",
    "file_name",
    "source_type",
    "sheet_name",
    "row_index",
    "kb_id",
    "doc_version",
    "source_uri",
]


def load_yaml(path: str | Path) -> Dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise RuntimeError(f"Config file does not exist: {file_path}")
    with file_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class KBRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.mapping: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self.mapping = {}
            return
        data = load_yaml(self.path)
        self.mapping = data.get("mappings", data)

    def resolve(self, kb_id: str) -> str:
        if not kb_id:
            raise ValueError("kb_id is required")
        mapped = self.mapping.get(kb_id)
        if isinstance(mapped, dict):
            collection_name = mapped.get("collection_name")
            if collection_name:
                return str(collection_name)
        elif isinstance(mapped, str) and mapped.strip():
            return mapped.strip()
        return kb_id


class RetrieveRequest(BaseModel):
    kb_id: str
    query: str
    top_k: int = 5
    query_instruction: str = ""
    filters: Dict[str, Any] = Field(default_factory=dict)


class RetrieveItem(BaseModel):
    content: str
    score: Optional[float] = None
    doc_id: Optional[str] = None
    title: Optional[str] = None
    file_name: Optional[str] = None
    source_type: Optional[str] = None
    sheet_name: Optional[str] = None
    row_index: Optional[int] = None
    kb_id: Optional[str] = None
    doc_version: Optional[str] = None
    source_uri: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrieveResponse(BaseModel):
    items: List[RetrieveItem]


class ExtractFieldSpec(BaseModel):
    name: str
    description: str = ""
    type: str = "string"
    aliases: List[str] = Field(default_factory=list)
    required: bool = False
    enum_values: List[str] = Field(default_factory=list)
    patterns: List[str] = Field(default_factory=list)
    normalizers: List[str] = Field(default_factory=list)


class ExtractRequest(BaseModel):
    kb_id: str
    query: str
    fields: List[ExtractFieldSpec]
    top_k: int = 8
    query_instruction: str = ""
    filters: Dict[str, Any] = Field(default_factory=dict)
    max_evidence_per_field: int = 2


class ExtractFieldResult(BaseModel):
    name: str
    value: Any = None
    raw_value: Optional[str] = None
    status: str
    confidence: float = 0.0
    reason: str = ""
    evidence: List[RetrieveItem] = Field(default_factory=list)


class ExtractResponse(BaseModel):
    result: Dict[str, Any]
    field_results: List[ExtractFieldResult]
    citations: List[RetrieveItem]
    status: str
    missing_required_fields: List[str] = Field(default_factory=list)


fastapi_app = FastAPI(title="bizRAG Retrieve Service")
retriever: Optional[Retriever] = None
retriever_cfg: Optional[Dict[str, Any]] = None
kb_registry: Optional[KBRegistry] = None


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


def _model_to_dict(item: BaseModel) -> Dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()


async def _retrieve_items(
    *,
    kb_id: str,
    query: str,
    top_k: int,
    query_instruction: str,
    filters: Optional[Dict[str, Any]],
) -> List[RetrieveItem]:
    global retriever, kb_registry

    if retriever is None:
        raise HTTPException(status_code=503, detail="Retriever is not initialized")
    if kb_registry is None:
        raise HTTPException(status_code=503, detail="KB registry is not initialized")

    collection_name = kb_registry.resolve(kb_id)
    rets = await retriever.retriever_search_structured(
        query_list=[query],
        top_k=top_k,
        query_instruction=query_instruction,
        collection_name=collection_name,
        filters=filters or None,
        output_fields=DEFAULT_OUTPUT_FIELDS,
    )
    first_row = rets.get("ret_items", [[]])[0]
    return [_normalize_hit(hit, kb_id=kb_id) for hit in first_row]


@fastapi_app.on_event("startup")
async def startup_event() -> None:
    global retriever
    if retriever_cfg is None:
        raise RuntimeError("retriever_cfg is not set")

    retriever = Retriever(retriever_app)
    await retriever.retriever_init(
        model_name_or_path=retriever_cfg["model_name_or_path"],
        backend_configs=retriever_cfg["backend_configs"],
        batch_size=retriever_cfg.get("batch_size", 32),
        corpus_path=retriever_cfg.get("corpus_path", ""),
        gpu_ids=retriever_cfg.get("gpu_ids"),
        is_multimodal=retriever_cfg.get("is_multimodal", False),
        backend=retriever_cfg.get("backend", "sentence_transformers"),
        index_backend=retriever_cfg.get("index_backend", "faiss"),
        index_backend_configs=retriever_cfg.get("index_backend_configs", {}),
        is_demo=retriever_cfg.get("is_demo", False),
        collection_name=retriever_cfg.get("collection_name", ""),
    )


@fastapi_app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@fastapi_app.post("/api/v1/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest) -> RetrieveResponse:
    try:
        items = await _retrieve_items(
            kb_id=req.kb_id,
            query=req.query,
            top_k=req.top_k,
            query_instruction=req.query_instruction,
            filters=req.filters,
        )
        return RetrieveResponse(items=items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@fastapi_app.post("/api/v1/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest) -> ExtractResponse:
    try:
        evidence_items = await _retrieve_items(
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
                evidence=[
                    RetrieveItem(**evidence)
                    for evidence in item.get("evidence", [])
                ],
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="bizRAG retrieve service")
    parser.add_argument(
        "--retriever-config",
        type=str,
        default="bizrag/src/servers/retriever/parameter.yaml",
        help="Path to retriever parameter yaml",
    )
    parser.add_argument(
        "--kb-registry",
        type=str,
        default="bizrag/config/kb_registry.yaml",
        help="Path to kb registry yaml",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=64501)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    retriever_cfg = load_yaml(args.retriever_config)
    kb_registry = KBRegistry(args.kb_registry)
    uvicorn.run(fastapi_app, host=args.host, port=args.port, reload=False)
