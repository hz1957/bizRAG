from __future__ import annotations

from pydantic import BaseModel, Field


class FileCreateRequest(BaseModel):
    kb_id: str = "default"
    tenant_id: str = "default"
    file_name: str | None = None
    content_type: str | None = None
    force: bool = False


class FileUpdateRequest(BaseModel):
    file_name: str | None = None
    content_type: str | None = None


class FileMetadataResponse(BaseModel):
    file_id: str
    tenant_id: str
    kb_id: str
    source_uri: str
    current_version: str
    file_name: str | None = None
    content_type: str | None = None
    status: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    latest_version: str | None = None


class VersionResponse(BaseModel):
    id: int
    file_id: str
    version: str
    storage_key: str
    size_bytes: int
    content_hash: str
    file_name: str | None = None
    content_type: str | None = None
    created_at: str


class EventResponse(BaseModel):
    event_id: str
    event_type: str
    status: str = "queued"


class EnqueueResult(BaseModel):
    file_id: str
    events: list[EventResponse]


class MessageResponse(BaseModel):
    status: str
    detail: str

