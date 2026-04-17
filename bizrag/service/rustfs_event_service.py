from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

from pydantic import BaseModel

from bizrag.contracts.schemas import RustFSEventRequest
from bizrag.service.errors import (
    BadRequestError,
    InternalServiceError,
    NotFoundError,
    ServiceError,
    UnauthorizedError,
)
from bizrag.service.kb_admin import KBAdmin

RunAdminAsync = Callable[..., Awaitable[Any]]


def _dump_model(model: BaseModel, *, exclude_none: bool = False) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=exclude_none)
    return model.dict(exclude_none=exclude_none)


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

    raise ValueError(
        "RustFS event must provide a local payload_path, download_url, payload_text, or payload_base64"
    )


def _canonical_payload(payload: BaseModel | Dict[str, Any]) -> str:
    if isinstance(payload, BaseModel):
        data = _dump_model(payload, exclude_none=True)
    else:
        data = payload
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verify_rustfs_headers(
    payload: BaseModel | Dict[str, Any],
    *,
    token: str = "",
    shared_secret: str = "",
    x_rustfs_token: Optional[str],
    x_rustfs_timestamp: Optional[str],
    x_rustfs_signature: Optional[str],
) -> None:
    if token and x_rustfs_token != token:
        raise UnauthorizedError("Invalid RustFS token")

    if shared_secret:
        if not x_rustfs_timestamp or not x_rustfs_signature:
            raise UnauthorizedError("Missing RustFS signature headers")
        payload_text = _canonical_payload(payload)
        sign_input = f"{x_rustfs_timestamp}\n{payload_text}".encode("utf-8")
        expected = hmac.new(
            shared_secret.encode("utf-8"),
            sign_input,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, x_rustfs_signature):
            raise UnauthorizedError("Invalid RustFS signature")


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
    req: RustFSEventRequest,
    event_id: str,
    run_admin_async: RunAdminAsync,
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
            result = await run_admin_async(
                "ingest_file",
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
            result = await run_admin_async(
                "delete_document",
                kb_id=req.kb_id,
                source_uri=target_source,
            )
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
                raise ValueError(
                    "old_source_uri and new_source_uri or equivalent payload fields are required for document.renamed"
                )
            delete_result = await run_admin_async(
                "delete_document",
                kb_id=req.kb_id,
                source_uri=old_source,
            )
            ingest_result = await run_admin_async(
                "ingest_file",
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


async def handle_rustfs_event_request(
    *,
    admin: KBAdmin,
    req: RustFSEventRequest,
    run_admin_async: RunAdminAsync,
    token: str = "",
    shared_secret: str = "",
    x_rustfs_token: Optional[str],
    x_rustfs_timestamp: Optional[str],
    x_rustfs_signature: Optional[str],
    verify_headers: bool = True,
    replay_of: Optional[str] = None,
) -> Dict[str, Any]:
    if verify_headers:
        verify_rustfs_headers(
            req,
            token=token,
            shared_secret=shared_secret,
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

    payload = _dump_model(req, exclude_none=True)
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
        result = await _process_rustfs_event(
            req=req,
            event_id=event_id,
            run_admin_async=run_admin_async,
        )
        admin.store.update_rustfs_event(event_id, status="success", result=result, error_message=None)
        return result
    except ServiceError as exc:
        admin.store.update_rustfs_event(
            event_id,
            status="failed",
            error_message=exc.detail,
        )
        raise
    except ValueError as exc:
        admin.store.update_rustfs_event(event_id, status="failed", error_message=str(exc))
        raise BadRequestError(str(exc)) from exc
    except RuntimeError as exc:
        admin.store.update_rustfs_event(event_id, status="failed", error_message=str(exc))
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        admin.store.update_rustfs_event(event_id, status="failed", error_message=str(exc))
        raise InternalServiceError(str(exc)) from exc


def enqueue_rustfs_event(
    *,
    admin: KBAdmin,
    req: RustFSEventRequest,
    token: str = "",
    shared_secret: str = "",
    x_rustfs_token: Optional[str],
    x_rustfs_timestamp: Optional[str],
    x_rustfs_signature: Optional[str],
) -> Dict[str, Any]:
    verify_rustfs_headers(
        req,
        token=token,
        shared_secret=shared_secret,
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
        payload=_dump_model(req, exclude_none=True),
    )
    return {
        "event_id": event_id,
        "event_type": req.event_type.strip().lower(),
        "status": "queued",
    }


async def replay_stored_rustfs_event(
    *,
    admin: KBAdmin,
    event_id: str,
    run_admin_async: RunAdminAsync,
) -> Dict[str, Any]:
    existing = admin.store.get_rustfs_event(event_id)
    if existing is None:
        raise NotFoundError(f"Unknown RustFS event: {event_id}")

    payload = dict(existing.get("payload_json") or {})
    payload.pop("replay_of", None)
    payload["event_id"] = str(uuid.uuid4())
    req = RustFSEventRequest(**payload)
    result = await handle_rustfs_event_request(
        admin=admin,
        req=req,
        run_admin_async=run_admin_async,
        token="",
        shared_secret="",
        x_rustfs_token=None,
        x_rustfs_timestamp=None,
        x_rustfs_signature=None,
        verify_headers=False,
        replay_of=event_id,
    )
    return {"replayed_from": event_id, **result}
