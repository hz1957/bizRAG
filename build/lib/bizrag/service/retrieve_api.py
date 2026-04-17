from __future__ import annotations

import argparse
import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen
import uuid

import uvicorn
import yaml
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from bizrag.service.extract_engine import extract_fields
from bizrag.service.kb_admin import KBAdmin
from bizrag.servers.retriever.retriever import Retriever, app as retriever_app


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


class RegisterKBRequest(BaseModel):
    kb_id: str
    retriever_config: str
    collection_name: Optional[str] = None
    display_name: Optional[str] = None
    source_root: Optional[str] = None
    index_uri: Optional[str] = None


class IngestPathRequest(BaseModel):
    kb_id: str
    path: str
    sync_deletions: bool = False
    force: bool = False
    prefer_mineru: bool = False
    chunk_backend: str = "sentence"
    chunk_size: int = 512
    chunk_overlap: int = 50


class DeleteDocumentRequest(BaseModel):
    kb_id: str
    source_uri: str


class RebuildKBRequest(BaseModel):
    kb_id: str


class RustFSEventRequest(BaseModel):
    event_id: Optional[str] = None
    event_type: str
    kb_id: str
    doc_id: Optional[str] = None
    source_uri: Optional[str] = None
    old_source_uri: Optional[str] = None
    new_source_uri: Optional[str] = None
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    version: Optional[str] = None
    content_hash: Optional[str] = None
    payload_path: Optional[str] = None
    download_url: Optional[str] = None
    payload_text: Optional[str] = None
    payload_base64: Optional[str] = None
    old_payload_path: Optional[str] = None
    new_payload_path: Optional[str] = None
    sync_deletions: bool = False
    force: bool = False
    prefer_mineru: bool = False
    chunk_backend: str = "sentence"
    chunk_size: int = 512
    chunk_overlap: int = 50


class RustFSEventBatchRequest(BaseModel):
    events: List[RustFSEventRequest]


retriever: Optional[Retriever] = None
retriever_cfg: Optional[Dict[str, Any]] = None
kb_registry: Optional[KBRegistry] = None
kb_admin: Optional[KBAdmin] = None
metadata_db_path: str = "bizrag/state/metadata.db"
workspace_root: str = "runtime/kbs"
rustfs_shared_secret: str = ""
rustfs_token: str = ""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global kb_admin, retriever

    if retriever_cfg is None:
        raise RuntimeError("retriever_cfg is not set")
    if kb_registry is None:
        raise RuntimeError("kb_registry is not set")

    kb_admin = KBAdmin(
        metadata_db=metadata_db_path,
        kb_registry_path=kb_registry.path,
        workspace_root=workspace_root,
    )
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
    try:
        yield
    finally:
        if kb_admin is not None:
            kb_admin.close()
            kb_admin = None
        retriever = None


fastapi_app = FastAPI(title="bizRAG Retrieve Service", lifespan=lifespan)


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


def _require_admin() -> KBAdmin:
    if kb_admin is None:
        raise HTTPException(status_code=503, detail="KB admin is not initialized")
    return kb_admin


def _pick_first(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if value:
            return value
    return None


def _looks_like_url(value: Optional[str]) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _is_existing_local_path(value: Optional[str]) -> bool:
    if not value:
        return False
    return Path(value).exists()


def _infer_temp_suffix(req: RustFSEventRequest) -> str:
    candidates = [
        req.file_name,
        req.new_source_uri,
        req.source_uri,
        req.new_payload_path,
        req.payload_path,
        req.download_url,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        suffix = Path(urlparse(candidate).path).suffix
        if suffix:
            return suffix
    if req.content_type:
        guessed = mimetypes.guess_extension(req.content_type.split(";", 1)[0].strip())
        if guessed:
            return guessed
    return ".txt"


def _materialize_rustfs_payload(req: RustFSEventRequest) -> Path:
    if req.payload_base64:
        fd, temp_path = tempfile.mkstemp(suffix=_infer_temp_suffix(req))
        path = Path(temp_path)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(req.payload_base64))
        return path

    if req.payload_text is not None:
        fd, temp_path = tempfile.mkstemp(suffix=_infer_temp_suffix(req), text=True)
        path = Path(temp_path)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(req.payload_text)
        return path

    if req.download_url and _looks_like_url(req.download_url):
        fd, temp_path = tempfile.mkstemp(suffix=_infer_temp_suffix(req))
        path = Path(temp_path)
        with urlopen(req.download_url) as resp, path.open("wb") as out:
            out.write(resp.read())
        return path

    raise ValueError("RustFS event must provide a local payload_path, download_url, payload_text, or payload_base64")


def _canonical_event_payload(req: RustFSEventRequest) -> str:
    return _canonical_payload(req)


def _canonical_payload(payload: BaseModel | Dict[str, Any]) -> str:
    if isinstance(payload, BaseModel):
        data = payload.model_dump(exclude_none=True)
    else:
        data = payload
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _verify_rustfs_headers(
    payload: BaseModel | Dict[str, Any],
    *,
    x_rustfs_token: Optional[str],
    x_rustfs_timestamp: Optional[str],
    x_rustfs_signature: Optional[str],
) -> None:
    if rustfs_token:
        if x_rustfs_token != rustfs_token:
            raise HTTPException(status_code=401, detail="Invalid RustFS token")

    if rustfs_shared_secret:
        if not x_rustfs_timestamp or not x_rustfs_signature:
            raise HTTPException(status_code=401, detail="Missing RustFS signature headers")
        payload_text = _canonical_payload(payload)
        sign_input = f"{x_rustfs_timestamp}\n{payload_text}".encode("utf-8")
        expected = hmac.new(
            rustfs_shared_secret.encode("utf-8"),
            sign_input,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, x_rustfs_signature):
            raise HTTPException(status_code=401, detail="Invalid RustFS signature")


def _event_source_uri(req: RustFSEventRequest) -> Optional[str]:
    return _pick_first(
        req.new_source_uri,
        req.source_uri,
        req.old_source_uri,
        req.doc_id,
        req.new_payload_path,
        req.payload_path,
        req.old_payload_path,
    )


async def _process_rustfs_event(
    *,
    admin: KBAdmin,
    req: RustFSEventRequest,
    event_id: str,
) -> Dict[str, Any]:
    event_type = req.event_type.strip().lower()
    temp_path: Optional[Path] = None
    try:
        if event_type in {"document.created", "document.updated"}:
            local_path = _pick_first(
                req.new_payload_path if _is_existing_local_path(req.new_payload_path) else None,
                req.payload_path if _is_existing_local_path(req.payload_path) else None,
            )
            if local_path:
                target_path = local_path
            else:
                temp_path = _materialize_rustfs_payload(req)
                target_path = str(temp_path)

            logical_source_uri = _pick_first(req.new_source_uri, req.source_uri, req.doc_id)
            logical_file_name = _pick_first(
                req.file_name,
                Path(urlparse(str(logical_source_uri)).path).name if logical_source_uri else None,
                Path(target_path).name,
            )
            result = await admin.ingest_file(
                kb_id=req.kb_id,
                path=target_path,
                logical_source_uri=logical_source_uri,
                logical_file_name=logical_file_name,
                force=req.force,
                prefer_mineru=req.prefer_mineru,
                chunk_backend=req.chunk_backend,
                chunk_size=req.chunk_size,
                chunk_overlap=req.chunk_overlap,
            )
            return {
                "event_id": event_id,
                "event_type": event_type,
                "action": "ingest",
                "result": result,
            }

        if event_type == "document.deleted":
            target_source = _pick_first(
                req.old_source_uri,
                req.source_uri,
                req.old_payload_path,
                req.payload_path,
            )
            if not target_source:
                raise ValueError("payload_path or source_uri is required for document.deleted")
            result = await admin.delete_document(kb_id=req.kb_id, source_uri=target_source)
            return {
                "event_id": event_id,
                "event_type": event_type,
                "action": "delete",
                "result": result,
            }

        if event_type == "document.renamed":
            old_source = _pick_first(req.old_source_uri, req.old_payload_path, req.source_uri)
            local_path = _pick_first(
                req.new_payload_path if _is_existing_local_path(req.new_payload_path) else None,
                req.payload_path if _is_existing_local_path(req.payload_path) else None,
            )
            if local_path:
                target_path = local_path
            else:
                temp_path = _materialize_rustfs_payload(req)
                target_path = str(temp_path)
            new_source = _pick_first(req.new_source_uri, req.source_uri, req.doc_id)
            if not old_source or not new_source:
                raise ValueError("old_source_uri and new_source_uri or equivalent payload fields are required for document.renamed")
            delete_result = await admin.delete_document(kb_id=req.kb_id, source_uri=old_source)
            ingest_result = await admin.ingest_file(
                kb_id=req.kb_id,
                path=target_path,
                logical_source_uri=new_source,
                logical_file_name=_pick_first(
                    req.file_name,
                    Path(urlparse(str(new_source)).path).name if new_source else None,
                    Path(target_path).name,
                ),
                force=req.force,
                prefer_mineru=req.prefer_mineru,
                chunk_backend=req.chunk_backend,
                chunk_size=req.chunk_size,
                chunk_overlap=req.chunk_overlap,
            )
            return {
                "event_id": event_id,
                "event_type": event_type,
                "action": "rename",
                "result": {
                    "delete": delete_result,
                    "ingest": ingest_result,
                },
            }

        raise ValueError(f"Unsupported event_type: {req.event_type}")
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


async def _handle_rustfs_event_request(
    *,
    admin: KBAdmin,
    req: RustFSEventRequest,
    x_rustfs_token: Optional[str],
    x_rustfs_timestamp: Optional[str],
    x_rustfs_signature: Optional[str],
    verify_headers: bool = True,
    replay_of: Optional[str] = None,
) -> Dict[str, Any]:
    if verify_headers:
        _verify_rustfs_headers(
            req,
            x_rustfs_token=x_rustfs_token,
            x_rustfs_timestamp=x_rustfs_timestamp,
            x_rustfs_signature=x_rustfs_signature,
        )

    event_id = req.event_id or str(uuid.uuid4())
    existing = admin.store.get_rustfs_event(event_id)
    if existing and existing.get("status") == "success" and not replay_of:
        return {
            "event_id": event_id,
            "event_type": req.event_type.strip().lower(),
            "status": "duplicate",
            "result": existing.get("result_json", {}),
        }

    payload = req.model_dump(exclude_none=True)
    if replay_of:
        payload["replay_of"] = replay_of

    if existing is None:
        admin.store.create_rustfs_event(
            event_id=event_id,
            kb_id=req.kb_id,
            event_type=req.event_type.strip().lower(),
            status="running",
            source_uri=_event_source_uri(req),
            payload=payload,
        )
    else:
        admin.store.update_rustfs_event(event_id, status="running", result={})

    try:
        result = await _process_rustfs_event(admin=admin, req=req, event_id=event_id)
        admin.store.update_rustfs_event(event_id, status="success", result=result, error_message=None)
        return result
    except HTTPException as exc:
        admin.store.update_rustfs_event(
            event_id,
            status="failed",
            error_message=str(exc.detail),
        )
        raise
    except ValueError as exc:
        admin.store.update_rustfs_event(event_id, status="failed", error_message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        admin.store.update_rustfs_event(event_id, status="failed", error_message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        admin.store.update_rustfs_event(event_id, status="failed", error_message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def enqueue_rustfs_event(
    *,
    admin: KBAdmin,
    req: RustFSEventRequest,
    x_rustfs_token: Optional[str],
    x_rustfs_timestamp: Optional[str],
    x_rustfs_signature: Optional[str],
) -> Dict[str, Any]:
    _verify_rustfs_headers(
        req,
        x_rustfs_token=x_rustfs_token,
        x_rustfs_timestamp=x_rustfs_timestamp,
        x_rustfs_signature=x_rustfs_signature,
    )
    event_id = req.event_id or str(uuid.uuid4())
    existing = admin.store.get_rustfs_event(event_id)
    if existing is not None:
        return {
            "event_id": event_id,
            "event_type": req.event_type.strip().lower(),
            "status": existing.get("status"),
        }

    admin.store.create_rustfs_event(
        event_id=event_id,
        kb_id=req.kb_id,
        event_type=req.event_type.strip().lower(),
        status="queued",
        source_uri=_event_source_uri(req),
        payload=req.model_dump(exclude_none=True),
    )
    return {
        "event_id": event_id,
        "event_type": req.event_type.strip().lower(),
        "status": "queued",
    }


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


@fastapi_app.post("/api/v1/admin/kbs/register")
async def register_kb(req: RegisterKBRequest) -> Dict[str, Any]:
    admin = _require_admin()
    try:
        return admin.register_kb(
            kb_id=req.kb_id,
            retriever_config_path=req.retriever_config,
            collection_name=req.collection_name,
            display_name=req.display_name,
            source_root=req.source_root,
            index_uri=req.index_uri,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@fastapi_app.get("/api/v1/admin/kbs")
async def list_kbs() -> Dict[str, Any]:
    admin = _require_admin()
    return {"items": admin.store.list_kbs()}


@fastapi_app.post("/api/v1/admin/kbs/ingest")
async def ingest_kb_path(req: IngestPathRequest) -> Dict[str, Any]:
    admin = _require_admin()
    try:
        return await admin.ingest_path(
            kb_id=req.kb_id,
            path=req.path,
            sync_deletions=req.sync_deletions,
            force=req.force,
            prefer_mineru=req.prefer_mineru,
            chunk_backend=req.chunk_backend,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@fastapi_app.get("/api/v1/admin/kbs/{kb_id}/documents")
async def list_documents(kb_id: str, include_deleted: bool = False) -> Dict[str, Any]:
    admin = _require_admin()
    return {"items": admin.store.list_documents(kb_id, include_deleted=include_deleted)}


@fastapi_app.post("/api/v1/admin/kbs/delete-document")
async def delete_kb_document(req: DeleteDocumentRequest) -> Dict[str, Any]:
    admin = _require_admin()
    try:
        return await admin.delete_document(kb_id=req.kb_id, source_uri=req.source_uri)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@fastapi_app.post("/api/v1/admin/kbs/rebuild")
async def rebuild_kb(req: RebuildKBRequest) -> Dict[str, Any]:
    admin = _require_admin()
    try:
        return await admin.rebuild_kb(kb_id=req.kb_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@fastapi_app.get("/api/v1/admin/tasks")
async def list_tasks(kb_id: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    admin = _require_admin()
    return {"items": admin.store.list_tasks(kb_id=kb_id, limit=limit)}


@fastapi_app.post("/api/v1/admin/tasks/{task_id}/retry")
async def retry_task(task_id: str) -> Dict[str, Any]:
    admin = _require_admin()
    try:
        return await admin.retry_task(task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@fastapi_app.get("/api/v1/admin/events")
async def list_rustfs_events(kb_id: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    admin = _require_admin()
    return {"items": admin.store.list_rustfs_events(kb_id=kb_id, limit=limit)}


@fastapi_app.post("/api/v1/admin/events/{event_id}/replay")
async def replay_rustfs_event(event_id: str) -> Dict[str, Any]:
    admin = _require_admin()
    existing = admin.store.get_rustfs_event(event_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Unknown RustFS event: {event_id}")

    payload = dict(existing.get("payload_json") or {})
    payload.pop("replay_of", None)
    payload["event_id"] = str(uuid.uuid4())
    req = RustFSEventRequest(**payload)
    result = await _handle_rustfs_event_request(
        admin=admin,
        req=req,
        x_rustfs_token=None,
        x_rustfs_timestamp=None,
        x_rustfs_signature=None,
        verify_headers=False,
        replay_of=event_id,
    )
    return {"replayed_from": event_id, **result}


@fastapi_app.post("/api/v1/events/rustfs")
async def handle_rustfs_event(
    req: RustFSEventRequest,
    x_rustfs_token: Optional[str] = Header(default=None),
    x_rustfs_timestamp: Optional[str] = Header(default=None),
    x_rustfs_signature: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    admin = _require_admin()
    return await _handle_rustfs_event_request(
        admin=admin,
        req=req,
        x_rustfs_token=x_rustfs_token,
        x_rustfs_timestamp=x_rustfs_timestamp,
        x_rustfs_signature=x_rustfs_signature,
    )


@fastapi_app.post("/api/v1/events/rustfs/batch")
async def handle_rustfs_batch(
    req: RustFSEventBatchRequest,
    x_rustfs_token: Optional[str] = Header(default=None),
    x_rustfs_timestamp: Optional[str] = Header(default=None),
    x_rustfs_signature: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    admin = _require_admin()
    _verify_rustfs_headers(
        req,
        x_rustfs_token=x_rustfs_token,
        x_rustfs_timestamp=x_rustfs_timestamp,
        x_rustfs_signature=x_rustfs_signature,
    )

    items: List[Dict[str, Any]] = []
    for event in req.events:
        try:
            result = await _handle_rustfs_event_request(
                admin=admin,
                req=event,
                x_rustfs_token=None,
                x_rustfs_timestamp=None,
                x_rustfs_signature=None,
                verify_headers=False,
            )
            items.append({"status": "success", **result})
        except HTTPException as exc:
            items.append(
                {
                    "status": "failed",
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "detail": exc.detail,
                }
            )
    return {"items": items}


@fastapi_app.post("/api/v1/events/rustfs/queue")
async def queue_rustfs_event(
    req: RustFSEventRequest,
    x_rustfs_token: Optional[str] = Header(default=None),
    x_rustfs_timestamp: Optional[str] = Header(default=None),
    x_rustfs_signature: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    admin = _require_admin()
    return enqueue_rustfs_event(
        admin=admin,
        req=req,
        x_rustfs_token=x_rustfs_token,
        x_rustfs_timestamp=x_rustfs_timestamp,
        x_rustfs_signature=x_rustfs_signature,
    )


@fastapi_app.post("/api/v1/events/rustfs/queue/batch")
async def queue_rustfs_batch(
    req: RustFSEventBatchRequest,
    x_rustfs_token: Optional[str] = Header(default=None),
    x_rustfs_timestamp: Optional[str] = Header(default=None),
    x_rustfs_signature: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    admin = _require_admin()
    _verify_rustfs_headers(
        req,
        x_rustfs_token=x_rustfs_token,
        x_rustfs_timestamp=x_rustfs_timestamp,
        x_rustfs_signature=x_rustfs_signature,
    )
    items = [
        enqueue_rustfs_event(
            admin=admin,
            req=event,
            x_rustfs_token=None,
            x_rustfs_timestamp=None,
            x_rustfs_signature=None,
        )
        for event in req.events
    ]
    return {"items": items}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="bizRAG retrieve service")
    parser.add_argument(
        "--retriever-config",
        type=str,
        default="bizrag/servers/retriever/parameter.yaml",
        help="Path to retriever parameter yaml",
    )
    parser.add_argument(
        "--kb-registry",
        type=str,
        default="bizrag/config/kb_registry.yaml",
        help="Path to kb registry yaml",
    )
    parser.add_argument(
        "--metadata-db",
        type=str,
        default="bizrag/state/metadata.db",
        help="SQLite metadata store path for admin endpoints",
    )
    parser.add_argument(
        "--workspace-root",
        type=str,
        default="runtime/kbs",
        help="Workspace root for corpus/chunk/index artifacts",
    )
    parser.add_argument(
        "--rustfs-token",
        type=str,
        default="",
        help="Optional shared token for RustFS webhook requests",
    )
    parser.add_argument(
        "--rustfs-shared-secret",
        type=str,
        default="",
        help="Optional HMAC secret for RustFS webhook signature verification",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=64501)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    retriever_cfg = load_yaml(args.retriever_config)
    kb_registry = KBRegistry(args.kb_registry)
    metadata_db_path = args.metadata_db
    workspace_root = args.workspace_root
    rustfs_token = args.rustfs_token
    rustfs_shared_secret = args.rustfs_shared_secret
    uvicorn.run(fastapi_app, host=args.host, port=args.port, reload=False)
