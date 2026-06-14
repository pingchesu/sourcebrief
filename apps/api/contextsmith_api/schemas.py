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


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)
    allowed_project_ids: list[UUID] | None = None
    allowed_resource_ids: list[UUID] | None = None
    expires_at: datetime | None = None


class ApiTokenRead(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    scopes: list[str]
    allowed_project_ids: list[UUID] | None = None
    allowed_resource_ids: list[UUID] | None = None
    created_by: UUID | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None


class ApiTokenCreateResponse(BaseModel):
    token: str
    api_token: ApiTokenRead


class AgentProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    default_runtime: str | None = Field(default=None, pattern=r"^(api|hermes|claude|codex|cursor)$")
    system_prompt: str | None = None
    tool_policy: dict | None = None


class AgentProfileRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    default_runtime: str
    system_prompt: str | None = None
    tool_policy: dict = Field(default_factory=dict)
    resource_count: int = 0
    current_snapshot_count: int = 0
    graph_node_count: int = 0
    graph_edge_count: int = 0
    last_index_finished_at: datetime | None = None
    mcp_endpoint: str
    agent_context_endpoint: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    stale_after_days: int | None = Field(default=None, ge=1, le=3650)


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
    review_status: str = "unreviewed"
    review_note: str | None = None
    last_reviewed_at: datetime | None = None
    last_reviewed_by: UUID | None = None
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
    next_refresh_at: datetime | None = None
    last_refresh_started_at: datetime | None = None
    last_refresh_finished_at: datetime | None = None
    stale_after_days: int = 30


class ResourceReviewRequest(BaseModel):
    review_status: str = Field(pattern=r"^(approved|needs_update|stale|ignored|unreviewed)$")
    review_note: str | None = None
    retrieval_enabled: bool | None = None
    stale_after_days: int | None = Field(default=None, ge=1, le=3650)


class ResourceReviewItem(BaseModel):
    resource: ResourceRead
    freshness_status: str
    freshness_age_days: int | None = None
    usage_count: int = 0
    last_used_at: datetime | None = None
    last_index_status: str | None = None
    last_index_finished_at: datetime | None = None
    stale_reasons: list[str] = Field(default_factory=list)


class ResourceReviewResponse(BaseModel):
    count: int
    resources: list[ResourceReviewItem]


class ResourceUsageItem(BaseModel):
    resource_id: UUID
    query_count: int
    hit_count: int
    context_packet_count: int
    last_used_at: datetime | None = None


class ResourceUsageResponse(BaseModel):
    count: int
    resources: list[ResourceUsageItem]


class DueRefreshResponse(BaseModel):
    scanned: int
    enqueued: int
    resource_ids: list[UUID] = Field(default_factory=list)
    skipped_active: list[UUID] = Field(default_factory=list)
    dry_run: bool = False


class PurgeResourceResponse(BaseModel):
    resource_id: UUID
    purged: bool
    counts: dict[str, int] = Field(default_factory=dict)


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
    actor_user_id: UUID | None = None
    actor_token_id: UUID | None = None
    action: str
    target_type: str
    target_id: UUID | None
    target_ref: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
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
    graph_score: float = 0.0
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


class AgentContextRequest(BaseModel):
    query: str = Field(min_length=1)
    resource_ids: list[UUID] | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    runtime: str | None = Field(default=None, pattern=r"^(api|hermes|claude|codex|cursor)$")
    include_code_symbols: bool = True
    max_chars: int = Field(default=12000, ge=1000, le=50000)


class AgentContextCitation(BaseModel):
    resource_id: UUID
    snapshot_id: UUID
    chunk_id: UUID
    path: str | None = None
    title: str | None = None
    ordinal: int
    version: str
    version_kind: str
    commit: str | None = None
    score: float
    graph_score: float = 0.0


class AgentContextResponse(BaseModel):
    query: str
    runtime: str
    instruction: str
    context: str
    citations: list[AgentContextCitation]
    symbols: list[CodeSymbolHit] = Field(default_factory=list)
    token_budget_hint: int


class GraphNodeRead(BaseModel):
    id: UUID
    resource_id: UUID
    snapshot_id: UUID
    node_key: str
    node_type: str
    label: str
    path: str | None = None
    metadata: dict = Field(default_factory=dict)


class GraphEdgeRead(BaseModel):
    id: UUID
    resource_id: UUID
    snapshot_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    edge_type: str
    weight: float
    metadata: dict = Field(default_factory=dict)


class GraphRead(BaseModel):
    node_count: int
    edge_count: int
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]
