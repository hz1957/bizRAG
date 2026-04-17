from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
