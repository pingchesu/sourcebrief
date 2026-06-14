from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")


class WorkspaceRead(BaseModel):
    id: UUID
    name: str
    slug: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None


class ProjectRead(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    description: str | None = None
    visibility: str


class ResourceCreate(BaseModel):
    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    update_frequency: str = "manual"
    source_config: dict = Field(default_factory=dict)


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    uri: str | None = Field(default=None, min_length=1)
    update_frequency: str | None = None
    source_config: dict | None = None
    retrieval_enabled: bool | None = None


class ResourceRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    type: str
    name: str
    uri: str
    status: str
    retrieval_enabled: bool
    update_frequency: str
    current_snapshot_id: UUID | None = None


class IndexRunRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    resource_id: UUID
    snapshot_id: UUID | None = None
    trigger: str
    status: str
    documents_seen: int
    chunks_created: int
    chunks_reused: int
    symbols_created: int
    embeddings_created: int
    graph_nodes_created: int
    graph_edges_created: int
    error_message: str | None = None
    log_ref: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class SnapshotRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    resource_id: UUID
    version: str
    version_kind: str
    status: str
    metadata: dict = Field(default_factory=dict)
    fetched_at: datetime | None = None
    indexed_at: datetime | None = None
    created_at: datetime | None = None
    is_current: bool = False


class AuditEventRead(BaseModel):
    id: UUID
    workspace_id: UUID
    action: str
    target_type: str
    target_id: UUID | None
    created_at: datetime


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    resource_ids: list[UUID] | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    resource_id: UUID
    snapshot_id: UUID
    path: str | None = None
    title: str | None = None
    ordinal: int
    content_hash: str
    version: str
    version_kind: str
    commit: str | None = None
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    count: int
    hits: list[SearchHit]


class ContextPacketRequest(BaseModel):
    query: str = Field(min_length=1)
    resource_ids: list[UUID] | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    mode: str = "hybrid"


class ContextPacketItemRead(BaseModel):
    rank: int
    resource_id: UUID
    snapshot_id: UUID
    chunk_id: UUID
    path: str | None = None
    title: str | None = None
    ordinal: int
    content_hash: str
    version: str
    version_kind: str
    commit: str | None = None
    snippet: str
    score: float
    lexical_score: float
    vector_score: float
    rerank_score: float
    citation: dict = Field(default_factory=dict)


class ContextPacketRead(BaseModel):
    id: UUID
    query_run_id: UUID
    workspace_id: UUID
    project_id: UUID
    query: str
    mode: str
    provider: str
    model: str
    count: int
    items: list[ContextPacketItemRead]


class CodeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    resource_ids: list[UUID] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CodeSymbolHit(BaseModel):
    resource_id: UUID
    snapshot_id: UUID
    path: str
    name: str
    kind: str
    language: str
    line_start: int
    line_end: int
    signature: str
    content_hash: str
    version: str
    version_kind: str
    commit: str | None = None
    score: float


class CodeSearchResponse(BaseModel):
    query: str
    count: int
    symbols: list[CodeSymbolHit]
