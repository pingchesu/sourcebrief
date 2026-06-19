from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class UserRead(BaseModel):
    id: UUID
    email: str
    display_name: str | None = None
    is_active: bool = True
    is_platform_admin: bool = False
    created_at: datetime | None = None


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class WorkspaceMemberCreate(BaseModel):
    email: str = Field(min_length=3)
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: str = Field(pattern=r"^(owner|admin|member|viewer)$")


class WorkspaceMemberUpdate(BaseModel):
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: str | None = Field(default=None, pattern=r"^(owner|admin|member|viewer)$")
    is_active: bool | None = None


class CurrentUserResponse(BaseModel):
    user: UserRead
    workspaces: list[WorkspaceRead]
    memberships: list[WorkspaceMemberRead] = Field(default_factory=list)
    projects_by_workspace: dict[UUID, list[ProjectRead]] = Field(default_factory=dict)
    default_workspace_id: UUID | None = None
    default_project_id: UUID | None = None


class AuthLoginResponse(CurrentUserResponse):
    session_token: str


class AuthLogoutResponse(BaseModel):
    status: str


class WorkspaceMemberRead(BaseModel):
    id: UUID
    workspace_id: UUID
    user: UserRead
    role: str
    created_at: datetime | None = None


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
    model_config = ConfigDict(from_attributes=True)

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
    source_family_label: str | None = None
    version_label: str | None = None
    has_manifest_diff: bool = False


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


class AgentFileRead(BaseModel):
    path: str
    kind: str
    description: str
    content: str


class AgentFilesResponse(BaseModel):
    workspace_id: UUID
    project_id: UUID
    generated_at: datetime
    resource_count: int
    repo_agent_count: int
    files: list[AgentFileRead]


class GitResourceEnvRead(BaseModel):
    resource_id: UUID
    name: str
    uri: str
    branch: str | None = None
    auth_token_env: str | None = None
    clone_timeout: int | None = None
    max_file_bytes: int | None = None
    max_repo_files: int | None = None
    max_repo_bytes: int | None = None
    update_frequency: str
    next_refresh_at: datetime | None = None


class GitResourceEnvUpdate(BaseModel):
    branch: str | None = None
    auth_token_env: str | None = None
    clone_timeout: int | None = Field(default=None, ge=1, le=600)
    max_file_bytes: int | None = Field(default=None, ge=1)
    max_repo_files: int | None = Field(default=None, ge=1)
    max_repo_bytes: int | None = Field(default=None, ge=1)
    update_frequency: str | None = None


class AgentCardSummaryRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    resource_id: UUID
    status: str
    severity: str
    summary: str
    findings: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    source: str
    acknowledged_at: datetime | None = None
    acknowledged_by: UUID | None = None
    suppressed_until: datetime | None = None
    created_at: datetime


class AgentCardSummaryAcknowledgeRequest(BaseModel):
    suppress_for_hours: int | None = Field(default=None, ge=1, le=24 * 90)


class AgentCardSummaryListResponse(BaseModel):
    count: int
    summaries: list[AgentCardSummaryRead]


class RepoAgentBriefRead(BaseModel):
    resource_id: UUID
    name: str
    uri: str
    readiness: str
    current_snapshot_id: UUID | None = None
    branch: str | None = None
    commit: str | None = None
    update_frequency: str
    freshness: dict = Field(default_factory=dict)
    stats: dict = Field(default_factory=dict)
    operating_brief: str
    entrypoint_paths: list[str] = Field(default_factory=list)
    config_paths: list[str] = Field(default_factory=list)
    runtime_paths: list[str] = Field(default_factory=list)
    runbook_paths: list[str] = Field(default_factory=list)
    symbol_samples: list[dict] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    invocation: dict = Field(default_factory=dict)
    safety_boundary: str
    quality_gates: list[str] = Field(default_factory=list)


class RetrievalProfileRead(BaseModel):
    name: str
    description: str
    weights: dict[str, float]


class RetrievalProfilesResponse(BaseModel):
    default: str
    profiles: list[RetrievalProfileRead]


class RetrievalEvalQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4000)
    expected_resource_ids: list[UUID] = Field(default_factory=list, max_length=20)
    forbidden_resource_ids: list[UUID] = Field(default_factory=list, max_length=20)
    resource_ids: list[UUID] | None = Field(default=None, max_length=20)
    expected_paths: list[str] = Field(default_factory=list, max_length=20)
    expected_symbols: list[str] = Field(default_factory=list, max_length=20)
    required_texts: list[str] = Field(default_factory=list, max_length=20)
    min_citations: int = Field(default=1, ge=0, le=20)
    top_k: int = Field(default=8, ge=1, le=20)
    include_code_symbols: bool = True


class RetrievalEvalRequest(BaseModel):
    questions: list[RetrievalEvalQuestion] = Field(min_length=1, max_length=10)
    profile: str | None = Field(default=None, pattern=r"^(lexical|vector|hybrid|hybrid[-_]rerank|graph)$")
    runtime: str = Field(default="hermes", pattern=r"^(api|hermes|claude|codex|cursor)$")
    max_chars: int = Field(default=8000, ge=1000, le=12000)


class RetrievalEvalResult(BaseModel):
    id: str
    query: str
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)
    latency_ms: float
    citation_count: int
    context_chars: int
    symbol_count: int
    expected_resource_ids: list[UUID] = Field(default_factory=list)
    cited_resource_ids: list[UUID] = Field(default_factory=list)
    forbidden_resource_ids: list[UUID] = Field(default_factory=list)
    hit_quality: list[dict] = Field(default_factory=list)


class RetrievalEvalSummary(BaseModel):
    status: str
    question_count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    max_latency_ms: float
    avg_latency_ms: float
    failure_reasons: list[str] = Field(default_factory=list)


class RetrievalEvalResponse(BaseModel):
    run_id: UUID | None = None
    profile: str
    workspace_id: UUID
    project_id: UUID
    generated_at: datetime
    provider: str
    model: str
    diagnostics: dict = Field(default_factory=dict)
    summary: RetrievalEvalSummary
    results: list[RetrievalEvalResult]


class RetrievalEvalRunSummaryRead(BaseModel):
    id: UUID
    profile: str
    workspace_id: UUID
    project_id: UUID
    created_at: datetime
    runtime: str
    provider: str
    model: str
    status: str
    question_count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    max_latency_ms: float
    avg_latency_ms: float
    project_wide: bool
    resource_ids: list[UUID] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)


class RetrievalEvalRunListResponse(BaseModel):
    count: int
    runs: list[RetrievalEvalRunSummaryRead]


class RetrievalEvalRunRead(BaseModel):
    run_id: UUID
    profile: str
    workspace_id: UUID
    project_id: UUID
    created_at: datetime
    runtime: str
    provider: str
    model: str
    diagnostics: dict = Field(default_factory=dict)
    summary: RetrievalEvalSummary
    results: list[RetrievalEvalResult]


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
    model_config = ConfigDict(from_attributes=True)

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


class FolderBundleUploadResponse(BaseModel):
    resource: ResourceRead
    index_run: IndexRunRead


class ResourceManifestFileRead(BaseModel):
    id: UUID
    normalized_path: str
    display_path: str | None = None
    size_bytes: int
    content_hash: str
    mime_type: str | None = None
    status: str
    warnings_json: list = Field(default_factory=list)


class ResourceManifestRead(BaseModel):
    id: UUID
    resource_id: UUID
    source_snapshot_id: UUID
    manifest_hash: str
    file_count: int
    total_bytes: int
    parser_warning_count: int
    unsupported_file_count: int
    section_count: int = 0
    sections_reused_count: int = 0
    sections_extracted_count: int = 0
    sections_from_deleted_files_count: int = 0
    sections_absent_count: int = 0
    created_at: datetime
    files: list[ResourceManifestFileRead]


class SnapshotSectionRead(BaseModel):
    id: UUID
    normalized_path: str
    ordinal: int
    title: str | None = None
    reuse_status: str
    start_line: int | None = None
    end_line: int | None = None
    content_preview: str


class SnapshotSectionsRead(BaseModel):
    source_snapshot_id: UUID
    version_resource_id: UUID
    section_count: int
    total_row_count: int
    row_count_returned: int
    limit: int
    next_cursor: str | None = None
    rows: list[SnapshotSectionRead]


class SectionImpactRead(BaseModel):
    sections_from_deleted_files_count: int
    sections_absent_count: int
    impacted_artifacts_known: bool = False
    message: str
    deleted_paths: list[dict] = Field(default_factory=list)
    changed_paths_with_absent_sections: list[dict] = Field(default_factory=list)


class ContextArtifactSourceRead(BaseModel):
    id: UUID
    normalized_path: str
    status: str
    coverage_status: str
    section_count: int
    metadata_json: dict = Field(default_factory=dict)


class ContextArtifactCitationRead(BaseModel):
    id: UUID
    normalized_path: str
    ordinal: int
    title: str | None = None
    content_hash: str
    line_start: int | None = None
    line_end: int | None = None


class ContextArtifactRead(BaseModel):
    id: UUID
    resource_id: UUID
    source_snapshot_id: UUID
    resource_manifest_id: UUID
    artifact_type: str
    artifact_revision: int
    status: str
    artifact_hash: str
    title: str
    summary: str | None = None
    coverage_json: dict = Field(default_factory=dict)
    validation_json: dict = Field(default_factory=dict)
    error_message: str | None = None
    review_comment: str | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    created_at: datetime
    sources: list[ContextArtifactSourceRead] = Field(default_factory=list)
    citations: list[ContextArtifactCitationRead] = Field(default_factory=list)


class ArtifactApprovalRequest(BaseModel):
    comment: str | None = None
    acknowledge_warnings: bool = False


class ArtifactRejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class ManifestDiffRowRead(BaseModel):
    normalized_path: str
    change_type: str
    base_file_id: UUID | None = None
    head_file_id: UUID | None = None
    base_status: str | None = None
    head_status: str | None = None
    base_size_bytes: int | None = None
    head_size_bytes: int | None = None
    base_content_hash: str | None = None
    head_content_hash: str | None = None
    warning_changed: bool
    reason: str


class DeletedFileImpactStubRead(BaseModel):
    deleted_file_count: int
    impacted_sections_known: bool
    message: str


class ManifestDiffRead(BaseModel):
    base_manifest_id: UUID
    head_manifest_id: UUID
    base_resource_id: UUID
    head_resource_id: UUID
    source_family_label: str | None = None
    added_count: int
    changed_count: int
    deleted_count: int
    unchanged_count: int
    warning_changed_count: int
    base_file_count: int
    head_file_count: int
    total_row_count: int
    row_count_returned: int
    limit: int
    next_cursor: str | None = None
    rows: list[ManifestDiffRowRead]
    deleted_file_impact: DeletedFileImpactStubRead


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


class AuditEventListResponse(BaseModel):
    count: int
    events: list[AuditEventRead]


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
    profile: str | None = Field(default=None, pattern=r"^(lexical|vector|hybrid|hybrid[-_]rerank|graph)$")
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
    diagnostics: dict = Field(default_factory=dict)
    items: list[ContextPacketItemRead]


class CodeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    resource_ids: list[UUID] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class RemoteSearchCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    resource_ids: list[UUID] | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    cursor: str | None = None


class RemoteSearchCodeHit(BaseModel):
    resource_id: UUID
    snapshot_id: UUID
    indexed_commit: str | None = None
    path: str
    line_start: int
    line_end: int
    snippet: str
    score: float
    score_components: dict = Field(default_factory=dict)


class RemoteSearchCodeResponse(BaseModel):
    results: list[RemoteSearchCodeHit]
    next_cursor: str | None = None


class RemoteGrepCodeRequest(BaseModel):
    pattern: str = Field(min_length=1)
    resource_ids: list[UUID] | None = None
    path_glob: str | None = None
    max_matches: int = Field(default=50, ge=1, le=100)
    cursor: str | None = None
    regex: bool = False
    context_lines: int = Field(default=1, ge=0, le=5)


class RemoteGrepCodeMatch(BaseModel):
    resource_id: UUID
    snapshot_id: UUID
    indexed_commit: str | None = None
    path: str
    line_start: int
    line_end: int
    line_text: str
    before: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)


class RemoteGrepCodeResponse(BaseModel):
    matches: list[RemoteGrepCodeMatch]
    next_cursor: str | None = None
    truncated: bool = False


class RemoteReadFileRequest(BaseModel):
    resource_id: UUID
    path: str = Field(min_length=1)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class RemoteReadFileResponse(BaseModel):
    resource_id: UUID
    snapshot_id: UUID
    indexed_commit: str | None = None
    path: str
    start_line: int
    end_line: int
    total_lines: int
    content: str
    truncated: bool = False


class RemoteFindSymbolRequest(BaseModel):
    name: str = Field(min_length=1)
    kind: str | None = None
    resource_ids: list[UUID] | None = None
    top_k: int = Field(default=20, ge=1, le=100)


class RemoteFindSymbolResponse(BaseModel):
    symbols: list[CodeSymbolHit]
    next_cursor: str | None = None


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


class PatchFileChange(BaseModel):
    path: str = Field(min_length=1)
    new_content: str = Field(max_length=20000)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    rationale: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_range(self) -> PatchFileChange:
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class GeneratePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: UUID
    scope: str = Field(min_length=1, max_length=500)
    files: list[PatchFileChange] = Field(min_length=1, max_length=5)
    source_branch: str | None = Field(default=None, max_length=200)
    target_branch: str | None = Field(default=None, max_length=200)
    base_commit: str | None = Field(default=None, max_length=80)
    approval_note: str | None = Field(default=None, max_length=1000)


class PatchProposalFileRead(BaseModel):
    path: str
    start_line: int
    end_line: int
    original_hash: str
    new_hash: str
    rationale: str | None = None


class PatchProposalRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    resource_id: UUID
    source_snapshot_id: UUID
    status: str
    scope: str
    source_branch: str | None = None
    target_branch: str | None = None
    indexed_commit: str | None = None
    base_commit: str | None = None
    branch_moved: bool = False
    warnings: list[str] = Field(default_factory=list)
    files: list[PatchProposalFileRead] = Field(default_factory=list)
    unified_diff: str
    diff_summary: str
    created_at: datetime


class OpenPrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_proposal_id: UUID
    source_branch: str = Field(min_length=1, max_length=200)
    target_branch: str = Field(min_length=1, max_length=200)
    approval_note: str = Field(min_length=1, max_length=1000)
    github_pr_url: str | None = Field(default=None, max_length=500)


class PrRequestRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    resource_id: UUID
    patch_proposal_id: UUID
    status: str
    source_branch: str
    target_branch: str
    scope: str
    diff_summary: str
    approval_note: str
    github_pr_url: str | None = None
    external_ref: dict = Field(default_factory=dict)
    created_at: datetime


class CodeSearchResponse(BaseModel):
    query: str
    count: int
    symbols: list[CodeSymbolHit]


class AgentContextRequest(BaseModel):
    query: str = Field(min_length=1)
    profile: str | None = Field(default=None, pattern=r"^(lexical|vector|hybrid|hybrid[-_]rerank|graph)$")
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
    profile: str
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
