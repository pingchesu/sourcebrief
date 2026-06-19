from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from contextsmith_shared.db import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Workspace(Base):
    __tablename__ = "workspaces"
    id = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    id = uuid_pk()
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),)
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token_type: Mapped[str] = mapped_column(Text, nullable=False, default="api")
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    allowed_project_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    allowed_resource_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_project_name_per_workspace"),)
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="workspace")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_membership"),)
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentProfile(Base):
    __tablename__ = "agent_profiles"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_runtime: Mapped[str] = mapped_column(Text, nullable=False, default="api")
    system_prompt: Mapped[str | None] = mapped_column(Text)
    tool_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_resource_name_per_project"),
        UniqueConstraint("id", "workspace_id", "project_id", name="uq_resources_id_scope"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    source_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    update_frequency: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    retrieval_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_status: Mapped[str] = mapped_column(Text, nullable=False, default="unreviewed")
    review_note: Mapped[str | None] = mapped_column(Text)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_after_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "resource_id",
            name="uq_source_snapshots_id_scope",
        ),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    version_kind: Mapped[str] = mapped_column(Text, nullable=False, default="content_hash")
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunks"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_snapshots.id"), nullable=False
    )
    path: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SnapshotFile(Base):
    __tablename__ = "snapshot_files"
    __table_args__ = (UniqueConstraint("source_snapshot_id", "path", name="uq_snapshot_files_snapshot_path"),)
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[str | None] = mapped_column(Text)
    is_binary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IndexRun(Base):
    __tablename__ = "index_runs"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_snapshots.id"))
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    documents_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_reused: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    symbols_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embeddings_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    graph_nodes_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    graph_edges_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    log_ref: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CodeSymbol(Base):
    __tablename__ = "code_symbols"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("source_snapshot_id", "node_key", name="uq_graph_nodes_snapshot_key"),)
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    node_key: Mapped[str] = mapped_column(Text, nullable=False)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_snapshot_id",
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_graph_edges_snapshot_source_target_type",
        ),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    source_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id"), nullable=False)
    target_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id"), nullable=False)
    edge_type: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(nullable=False, default=1.0)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Graph(Base):
    __tablename__ = "graphs"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", "project_id", name="uq_graphs_id_scope"),
        UniqueConstraint("id", "workspace_id", "project_id", "resource_id", name="uq_graphs_id_resource_scope"),
        UniqueConstraint("workspace_id", "project_id", "graph_key", name="uq_graphs_key"),
        Index("uq_graphs_resource_active", "workspace_id", "project_id", "resource_id", unique=True, postgresql_where=text("resource_id IS NOT NULL")),
        CheckConstraint("status IN ('active', 'archived')", name="ck_graphs_status"),
        CheckConstraint("graph_type = 'resource'", name="ck_graphs_type_e0"),
        CheckConstraint("graph_key ~ '^[a-z0-9][a-z0-9-]{2,62}$'", name="ck_graphs_key_format"),
        ForeignKeyConstraint(["resource_id", "workspace_id", "project_id"], ["resources.id", "resources.workspace_id", "resources.project_id"], name="fk_graphs_resource_scope"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    graph_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    graph_type: Mapped[str] = mapped_column(Text, nullable=False, default="resource")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GraphVersion(Base):
    __tablename__ = "graph_versions"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", "project_id", name="uq_graph_versions_id_scope"),
        UniqueConstraint("graph_id", "version", name="uq_graph_versions_graph_version"),
        Index("ix_graph_versions_graph_status", "graph_id", "status"),
        Index("ix_graph_versions_resource_snapshot", "resource_id", "source_snapshot_id"),
        CheckConstraint("status IN ('draft', 'published', 'superseded', 'invalidated')", name="ck_graph_versions_status"),
        CheckConstraint("version >= 1", name="ck_graph_versions_version_positive"),
        CheckConstraint("version_hash LIKE 'sha256:%' AND length(version_hash) = 71", name="ck_graph_versions_hash_format"),
        CheckConstraint("node_count >= 0", name="ck_graph_versions_node_count_nonnegative"),
        CheckConstraint("edge_count >= 0", name="ck_graph_versions_edge_count_nonnegative"),
        ForeignKeyConstraint(["graph_id", "workspace_id", "project_id"], ["graphs.id", "graphs.workspace_id", "graphs.project_id"], name="fk_graph_versions_graph_scope"),
        ForeignKeyConstraint(["graph_id", "workspace_id", "project_id", "resource_id"], ["graphs.id", "graphs.workspace_id", "graphs.project_id", "graphs.resource_id"], name="fk_graph_versions_graph_resource_scope"),
        ForeignKeyConstraint(["resource_id", "workspace_id", "project_id"], ["resources.id", "resources.workspace_id", "resources.project_id"], name="fk_graph_versions_resource_scope"),
        ForeignKeyConstraint(["source_snapshot_id", "workspace_id", "project_id", "resource_id"], ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"], name="fk_graph_versions_snapshot_scope"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    graph_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    version_hash: Mapped[str] = mapped_column(Text, nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    membership_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provenance_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    validation_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QueryRun(Base):
    __tablename__ = "query_runs"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetrievalHit(Base):
    __tablename__ = "retrieval_hits"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    query_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("query_runs.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    lexical_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    vector_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    graph_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rerank_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    score: Mapped[float] = mapped_column(nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetrievalEvalRun(Base):
    __tablename__ = "retrieval_eval_runs"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_tokens.id"))
    runtime: Mapped[str] = mapped_column(Text, nullable=False)
    profile: Mapped[str] = mapped_column(Text, nullable=False, default="hybrid")
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_rate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    max_latency_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    avg_latency_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    max_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    project_wide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resource_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    diagnostics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetrievalEvalItem(Base):
    __tablename__ = "retrieval_eval_items"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    eval_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retrieval_eval_runs.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    symbol_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_resource_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    cited_resource_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    forbidden_resource_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    failure_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    hit_quality: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextPacket(Base):
    __tablename__ = "context_packets"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    query_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("query_runs.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextPacketItem(Base):
    __tablename__ = "context_packet_items"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    context_packet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_packets.id"), nullable=False)
    retrieval_hit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retrieval_hits.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    citation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentCardSummary(Base):
    __tablename__ = "agent_card_summaries"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="auditor")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    suppressed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PatchProposal(Base):
    __tablename__ = "patch_proposals"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_tokens.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    source_branch: Mapped[str | None] = mapped_column(Text)
    target_branch: Mapped[str | None] = mapped_column(Text)
    indexed_commit: Mapped[str | None] = mapped_column(Text)
    base_commit: Mapped[str | None] = mapped_column(Text)
    branch_moved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    files: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    unified_diff: Mapped[str] = mapped_column(Text, nullable=False)
    diff_summary: Mapped[str] = mapped_column(Text, nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PrRequest(Base):
    __tablename__ = "pr_requests"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    patch_proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patch_proposals.id"), nullable=False)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approver_token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_tokens.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="recorded")
    source_branch: Mapped[str] = mapped_column(Text, nullable=False)
    target_branch: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    diff_summary: Mapped[str] = mapped_column(Text, nullable=False)
    approval_note: Mapped[str] = mapped_column(Text, nullable=False)
    github_pr_url: Mapped[str | None] = mapped_column(Text)
    external_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_tokens.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceManifest(Base):
    __tablename__ = "resource_manifests"
    __table_args__ = (
        UniqueConstraint("source_snapshot_id", name="uq_resource_manifests_snapshot"),
        UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "resource_id",
            name="uq_resource_manifests_id_scope",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "resource_id",
            "source_snapshot_id",
            name="uq_resource_manifests_id_snapshot_scope",
        ),
        ForeignKeyConstraint(
            ["source_snapshot_id", "workspace_id", "project_id", "resource_id"],
            [
                "source_snapshots.id",
                "source_snapshots.workspace_id",
                "source_snapshots.project_id",
                "source_snapshots.resource_id",
            ],
            name="fk_resource_manifests_snapshot_scope",
        ),
        CheckConstraint("file_count >= 0", name="ck_resource_manifests_file_count_nonnegative"),
        CheckConstraint("total_bytes >= 0", name="ck_resource_manifests_total_bytes_nonnegative"),
        CheckConstraint(
            "parser_warning_count >= 0 AND parser_warning_count <= file_count",
            name="ck_resource_manifests_warning_count_bounds",
        ),
        CheckConstraint(
            "unsupported_file_count >= 0 AND unsupported_file_count <= file_count",
            name="ck_resource_manifests_unsupported_count_bounds",
        ),
        CheckConstraint(
            "manifest_hash LIKE 'sha256:%' AND length(manifest_hash) = 71",
            name="ck_resource_manifests_manifest_hash_format",
        ),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    parser_warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sections_reused_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sections_extracted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sections_from_deleted_files_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sections_absent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceManifestFile(Base):
    __tablename__ = "resource_manifest_files"
    __table_args__ = (
        UniqueConstraint(
            "resource_manifest_id",
            "normalized_path",
            name="uq_resource_manifest_files_manifest_path",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "resource_id",
            "resource_manifest_id",
            name="uq_resource_manifest_files_id_scope",
        ),
        ForeignKeyConstraint(
            ["resource_manifest_id", "workspace_id", "project_id", "resource_id"],
            [
                "resource_manifests.id",
                "resource_manifests.workspace_id",
                "resource_manifests.project_id",
                "resource_manifests.resource_id",
            ],
            name="fk_resource_manifest_files_manifest_scope",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_resource_manifest_files_size_nonnegative"),
        CheckConstraint("section_count >= 0", name="ck_resource_manifest_files_section_count_nonnegative"),
        CheckConstraint(
            "status IN ('pending', 'parsed', 'failed', 'unsupported', 'skipped')",
            name="ck_resource_manifest_files_status",
        ),
        CheckConstraint(
            "path_hash LIKE 'sha256:%' AND length(path_hash) = 71",
            name="ck_resource_manifest_files_path_hash_format",
        ),
        CheckConstraint(
            "content_hash LIKE 'sha256:%' AND length(content_hash) = 71",
            name="ck_resource_manifest_files_content_hash_format",
        ),
        CheckConstraint(
            "jsonb_typeof(warnings_json) = 'array'",
            name="ck_resource_manifest_files_warnings_array",
        ),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    resource_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifests.id"), nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    display_path: Mapped[str | None] = mapped_column(Text)
    path_hash: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mime_type: Mapped[str | None] = mapped_column(Text)
    mtime_client: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(Text)
    extraction_policy_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    section_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("project_id", "logical_key", name="uq_sections_project_logical_key"),
        UniqueConstraint("id", "workspace_id", "project_id", "section_family_resource_id", name="uq_sections_id_scope"),
        ForeignKeyConstraint(
            ["section_family_resource_id", "workspace_id", "project_id"],
            ["resources.id", "resources.workspace_id", "resources.project_id"],
            name="fk_sections_family_resource_scope",
        ),
        CheckConstraint("content_bytes >= 0", name="ck_sections_content_bytes_nonnegative"),
        CheckConstraint("ordinal >= 0", name="ck_sections_ordinal_nonnegative"),
        CheckConstraint("section_hash LIKE 'sha256:%' AND length(section_hash) = 71", name="ck_sections_section_hash_format"),
        CheckConstraint("content_hash LIKE 'sha256:%' AND length(content_hash) = 71", name="ck_sections_content_hash_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    section_family_resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_policy_hash: Mapped[str] = mapped_column(Text, nullable=False)
    section_hash: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_key: Mapped[str] = mapped_column(Text, nullable=False)
    logical_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SnapshotSection(Base):
    __tablename__ = "snapshot_sections"
    __table_args__ = (
        UniqueConstraint("source_snapshot_id", "resource_manifest_file_id", "ordinal", name="uq_snapshot_sections_snapshot_file_ordinal"),
        UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "version_resource_id",
            "section_family_resource_id",
            "source_snapshot_id",
            "resource_manifest_id",
            "resource_manifest_file_id",
            "normalized_path",
            name="uq_snapshot_sections_id_b0_scope",
        ),
        ForeignKeyConstraint(
            ["version_resource_id", "workspace_id", "project_id"],
            ["resources.id", "resources.workspace_id", "resources.project_id"],
            name="fk_snapshot_sections_version_resource_scope",
        ),
        ForeignKeyConstraint(
            ["section_family_resource_id", "workspace_id", "project_id"],
            ["resources.id", "resources.workspace_id", "resources.project_id"],
            name="fk_snapshot_sections_family_resource_scope",
        ),
        ForeignKeyConstraint(
            ["source_snapshot_id", "workspace_id", "project_id", "version_resource_id"],
            ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"],
            name="fk_snapshot_sections_snapshot_scope",
        ),
        ForeignKeyConstraint(
            ["resource_manifest_id", "workspace_id", "project_id", "version_resource_id", "source_snapshot_id"],
            [
                "resource_manifests.id",
                "resource_manifests.workspace_id",
                "resource_manifests.project_id",
                "resource_manifests.resource_id",
                "resource_manifests.source_snapshot_id",
            ],
            name="fk_snapshot_sections_manifest_scope",
        ),
        ForeignKeyConstraint(
            ["resource_manifest_file_id", "workspace_id", "project_id", "version_resource_id", "resource_manifest_id"],
            [
                "resource_manifest_files.id",
                "resource_manifest_files.workspace_id",
                "resource_manifest_files.project_id",
                "resource_manifest_files.resource_id",
                "resource_manifest_files.resource_manifest_id",
            ],
            name="fk_snapshot_sections_manifest_file_scope",
        ),
        ForeignKeyConstraint(
            ["section_id", "workspace_id", "project_id", "section_family_resource_id"],
            ["sections.id", "sections.workspace_id", "sections.project_id", "sections.section_family_resource_id"],
            name="fk_snapshot_sections_section_scope",
        ),
        CheckConstraint("ordinal >= 0", name="ck_snapshot_sections_ordinal_nonnegative"),
        CheckConstraint("reuse_status IN ('reused', 'extracted')", name="ck_snapshot_sections_reuse_status"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    version_resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    section_family_resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    resource_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifests.id"), nullable=False)
    resource_manifest_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifest_files.id"), nullable=False)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reused_from_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_snapshots.id"))
    reuse_status: Mapped[str] = mapped_column(Text, nullable=False, default="extracted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextArtifact(Base):
    __tablename__ = "context_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "resource_id",
            "source_snapshot_id",
            "resource_manifest_id",
            name="uq_context_artifacts_id_scope",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "resource_id",
            "source_snapshot_id",
            "artifact_type",
            "artifact_hash",
            "artifact_revision",
            name="uq_context_artifacts_hash_revision",
        ),
        ForeignKeyConstraint(
            ["resource_id", "workspace_id", "project_id"],
            ["resources.id", "resources.workspace_id", "resources.project_id"],
            name="fk_context_artifacts_resource_scope",
        ),
        ForeignKeyConstraint(
            ["source_snapshot_id", "workspace_id", "project_id", "resource_id"],
            ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"],
            name="fk_context_artifacts_snapshot_scope",
        ),
        ForeignKeyConstraint(
            ["resource_manifest_id", "workspace_id", "project_id", "resource_id", "source_snapshot_id"],
            [
                "resource_manifests.id",
                "resource_manifests.workspace_id",
                "resource_manifests.project_id",
                "resource_manifests.resource_id",
                "resource_manifests.source_snapshot_id",
            ],
            name="fk_context_artifacts_manifest_scope",
        ),
        CheckConstraint("status IN ('draft', 'approved', 'rejected', 'failed')", name="ck_context_artifacts_status"),
        CheckConstraint("artifact_revision >= 1", name="ck_context_artifacts_revision_positive"),
        CheckConstraint("artifact_hash LIKE 'sha256:%' AND length(artifact_hash) = 71", name="ck_context_artifacts_hash_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    resource_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifests.id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    artifact_hash: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    coverage_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    validation_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextArtifactSource(Base):
    __tablename__ = "context_artifact_sources"
    __table_args__ = (
        UniqueConstraint("context_artifact_id", "normalized_path", name="uq_context_artifact_sources_artifact_path"),
        UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "context_artifact_id",
            "resource_manifest_file_id",
            "resource_id",
            "source_snapshot_id",
            "resource_manifest_id",
            "normalized_path",
            name="uq_context_artifact_sources_id_scope",
        ),
        ForeignKeyConstraint(
            ["context_artifact_id", "workspace_id", "project_id", "resource_id", "source_snapshot_id", "resource_manifest_id"],
            [
                "context_artifacts.id",
                "context_artifacts.workspace_id",
                "context_artifacts.project_id",
                "context_artifacts.resource_id",
                "context_artifacts.source_snapshot_id",
                "context_artifacts.resource_manifest_id",
            ],
            name="fk_context_artifact_sources_artifact_scope",
        ),
        ForeignKeyConstraint(
            ["resource_manifest_file_id", "workspace_id", "project_id", "resource_id", "resource_manifest_id"],
            [
                "resource_manifest_files.id",
                "resource_manifest_files.workspace_id",
                "resource_manifest_files.project_id",
                "resource_manifest_files.resource_id",
                "resource_manifest_files.resource_manifest_id",
            ],
            name="fk_context_artifact_sources_manifest_file_scope",
        ),
        CheckConstraint("section_count >= 0", name="ck_context_artifact_sources_section_count_nonnegative"),
        CheckConstraint(
            "coverage_status IN ('covered', 'warning', 'empty', 'unsupported', 'failed', 'skipped')",
            name="ck_context_artifact_sources_coverage_status",
        ),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    context_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_artifacts.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    resource_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifests.id"), nullable=False)
    resource_manifest_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifest_files.id"), nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    section_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_status: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextArtifactCitation(Base):
    __tablename__ = "context_artifact_citations"
    __table_args__ = (
        UniqueConstraint("context_artifact_id", "snapshot_section_id", name="uq_context_artifact_citations_artifact_snapshot_section"),
        ForeignKeyConstraint(
            [
                "snapshot_section_id",
                "workspace_id",
                "project_id",
                "resource_id",
                "section_family_resource_id",
                "source_snapshot_id",
                "resource_manifest_id",
                "resource_manifest_file_id",
                "normalized_path",
            ],
            [
                "snapshot_sections.id",
                "snapshot_sections.workspace_id",
                "snapshot_sections.project_id",
                "snapshot_sections.version_resource_id",
                "snapshot_sections.section_family_resource_id",
                "snapshot_sections.source_snapshot_id",
                "snapshot_sections.resource_manifest_id",
                "snapshot_sections.resource_manifest_file_id",
                "snapshot_sections.normalized_path",
            ],
            name="fk_context_artifact_citations_snapshot_section_scope",
        ),
        ForeignKeyConstraint(
            ["section_id", "workspace_id", "project_id", "section_family_resource_id"],
            ["sections.id", "sections.workspace_id", "sections.project_id", "sections.section_family_resource_id"],
            name="fk_context_artifact_citations_section_scope",
        ),
        ForeignKeyConstraint(
            [
                "context_artifact_source_id",
                "workspace_id",
                "project_id",
                "context_artifact_id",
                "resource_manifest_file_id",
                "resource_id",
                "source_snapshot_id",
                "resource_manifest_id",
                "normalized_path",
            ],
            [
                "context_artifact_sources.id",
                "context_artifact_sources.workspace_id",
                "context_artifact_sources.project_id",
                "context_artifact_sources.context_artifact_id",
                "context_artifact_sources.resource_manifest_file_id",
                "context_artifact_sources.resource_id",
                "context_artifact_sources.source_snapshot_id",
                "context_artifact_sources.resource_manifest_id",
                "context_artifact_sources.normalized_path",
            ],
            name="fk_context_artifact_citations_source_scope",
        ),
        CheckConstraint("ordinal >= 0", name="ck_context_artifact_citations_ordinal_nonnegative"),
        CheckConstraint("content_hash LIKE 'sha256:%' AND length(content_hash) = 71", name="ck_context_artifact_citations_content_hash_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    context_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_artifacts.id"), nullable=False)
    context_artifact_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_artifact_sources.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    section_family_resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    resource_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifests.id"), nullable=False)
    resource_manifest_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifest_files.id"), nullable=False)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), nullable=False)
    snapshot_section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("snapshot_sections.id"), nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextPack(Base):
    __tablename__ = "context_packs"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", "project_id", name="uq_context_packs_id_scope"),
        UniqueConstraint("workspace_id", "project_id", "pack_key", name="uq_context_packs_project_key"),
        ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_context_packs_workspace"),
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_context_packs_project"),
        CheckConstraint("pack_key ~ '^[a-z0-9][a-z0-9._-]{0,62}$'", name="ck_context_packs_key_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    pack_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ContextPackVersion(Base):
    __tablename__ = "context_pack_versions"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", "project_id", name="uq_context_pack_versions_id_scope"),
        UniqueConstraint("workspace_id", "project_id", "pack_key", "version", name="uq_context_pack_versions_project_key_version"),
        Index("uq_context_pack_versions_one_published", "workspace_id", "project_id", "pack_key", unique=True, postgresql_where=text("status = 'published'")),
        Index("ix_context_pack_versions_project_key_status", "workspace_id", "project_id", "pack_key", "status"),
        Index("ix_context_pack_versions_project_status_created", "workspace_id", "project_id", "status", "created_at"),
        ForeignKeyConstraint(["context_pack_id", "workspace_id", "project_id"], ["context_packs.id", "context_packs.workspace_id", "context_packs.project_id"], name="fk_context_pack_versions_pack_scope"),
        CheckConstraint("status IN ('draft', 'published', 'superseded', 'rolled_back', 'invalidated', 'failed')", name="ck_context_pack_versions_status"),
        CheckConstraint("version >= 1", name="ck_context_pack_versions_version_positive"),
        CheckConstraint("pack_hash LIKE 'sha256:%' AND length(pack_hash) = 71", name="ck_context_pack_versions_hash_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    context_pack_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_packs.id"), nullable=False)
    pack_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    pack_hash: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    validation_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ContextPackArtifact(Base):
    __tablename__ = "context_pack_artifacts"
    __table_args__ = (
        UniqueConstraint("context_pack_version_id", "context_artifact_id", name="uq_context_pack_artifacts_version_artifact"),
        UniqueConstraint("context_pack_version_id", "ordinal", name="uq_context_pack_artifacts_version_ordinal"),
        ForeignKeyConstraint(["context_pack_version_id", "workspace_id", "project_id"], ["context_pack_versions.id", "context_pack_versions.workspace_id", "context_pack_versions.project_id"], name="fk_context_pack_artifacts_version_scope"),
        ForeignKeyConstraint(["context_artifact_id", "workspace_id", "project_id", "resource_id", "source_snapshot_id", "resource_manifest_id"], ["context_artifacts.id", "context_artifacts.workspace_id", "context_artifacts.project_id", "context_artifacts.resource_id", "context_artifacts.source_snapshot_id", "context_artifacts.resource_manifest_id"], name="fk_context_pack_artifacts_artifact_scope"),
        CheckConstraint("ordinal >= 0", name="ck_context_pack_artifacts_ordinal_nonnegative"),
        CheckConstraint("artifact_hash LIKE 'sha256:%' AND length(artifact_hash) = 71", name="ck_context_pack_artifacts_hash_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    context_pack_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_pack_versions.id"), nullable=False)
    context_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_artifacts.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    resource_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifests.id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextPackResourceCoverage(Base):
    __tablename__ = "context_pack_resource_coverage"
    __table_args__ = (
        UniqueConstraint("context_pack_version_id", "resource_id", "source_snapshot_id", "resource_manifest_id", name="uq_context_pack_coverage_version_resource_snapshot_manifest"),
        ForeignKeyConstraint(["context_pack_version_id", "workspace_id", "project_id"], ["context_pack_versions.id", "context_pack_versions.workspace_id", "context_pack_versions.project_id"], name="fk_context_pack_coverage_version_scope"),
        CheckConstraint("artifact_count >= 0", name="ck_context_pack_coverage_artifact_count_nonnegative"),
        CheckConstraint("citation_count >= 0", name="ck_context_pack_coverage_citation_count_nonnegative"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    context_pack_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_pack_versions.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    resource_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifests.id"), nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillExport(Base):
    __tablename__ = "skill_exports"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", "project_id", name="uq_skill_exports_id_scope"),
        UniqueConstraint("workspace_id", "project_id", "context_pack_version_id", "export_type", "package_hash", name="uq_skill_exports_pack_type_hash"),
        UniqueConstraint("workspace_id", "project_id", "context_pack_version_id", "export_type", "export_version", name="uq_skill_exports_pack_type_version"),
        Index("ix_skill_exports_pack_status", "workspace_id", "project_id", "context_pack_version_id", "status"),
        ForeignKeyConstraint(["context_pack_version_id", "workspace_id", "project_id"], ["context_pack_versions.id", "context_pack_versions.workspace_id", "context_pack_versions.project_id"], name="fk_skill_exports_pack_version_scope"),
        CheckConstraint("status IN ('draft', 'approved', 'rejected', 'invalidated', 'failed')", name="ck_skill_exports_status"),
        CheckConstraint("export_type IN ('hermes_skill')", name="ck_skill_exports_type"),
        CheckConstraint("export_version >= 1", name="ck_skill_exports_version_positive"),
        CheckConstraint("package_hash LIKE 'sha256:%' AND length(package_hash) = 71", name="ck_skill_exports_hash_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    context_pack_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_pack_versions.id"), nullable=False)
    pack_key: Mapped[str] = mapped_column(Text, nullable=False)
    pack_version: Mapped[int] = mapped_column(Integer, nullable=False)
    export_type: Mapped[str] = mapped_column(Text, nullable=False, default="hermes_skill")
    export_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    package_hash: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    files_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    validation_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    leak_scan_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RepoAgent(Base):
    __tablename__ = "repo_agents"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", "project_id", name="uq_repo_agents_id_scope"),
        UniqueConstraint("workspace_id", "project_id", "agent_key", name="uq_repo_agents_key"),
        Index("uq_repo_agents_resource_pack_active", "workspace_id", "project_id", "resource_id", "pack_key", unique=True, postgresql_where=text("resource_id IS NOT NULL")),
        CheckConstraint("status IN ('active', 'archived')", name="ck_repo_agents_status"),
        CheckConstraint("agent_key ~ '^[a-z0-9][a-z0-9-]{2,62}$'", name="ck_repo_agents_key_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resources.id"))
    agent_key: Mapped[str] = mapped_column(Text, nullable=False)
    pack_key: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    update_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RepoAgentVersion(Base):
    __tablename__ = "repo_agent_versions"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", "project_id", name="uq_repo_agent_versions_id_scope"),
        UniqueConstraint("repo_agent_id", "version", name="uq_repo_agent_versions_agent_version"),
        Index("ix_repo_agent_versions_agent_status", "repo_agent_id", "status"),
        Index("ix_repo_agent_versions_active_draft_hash", "repo_agent_id", "version_hash", unique=True, postgresql_where=text("status = 'draft'")),
        ForeignKeyConstraint(["repo_agent_id", "workspace_id", "project_id"], ["repo_agents.id", "repo_agents.workspace_id", "repo_agents.project_id"], name="fk_repo_agent_versions_agent_scope"),
        ForeignKeyConstraint(["resource_id", "workspace_id", "project_id"], ["resources.id", "resources.workspace_id", "resources.project_id"], name="fk_repo_agent_versions_resource_scope"),
        ForeignKeyConstraint(["source_snapshot_id", "workspace_id", "project_id", "resource_id"], ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"], name="fk_repo_agent_versions_snapshot_scope"),
        ForeignKeyConstraint(["resource_manifest_id", "workspace_id", "project_id", "resource_id"], ["resource_manifests.id", "resource_manifests.workspace_id", "resource_manifests.project_id", "resource_manifests.resource_id"], name="fk_repo_agent_versions_manifest_scope"),
        ForeignKeyConstraint(["context_pack_version_id", "workspace_id", "project_id"], ["context_pack_versions.id", "context_pack_versions.workspace_id", "context_pack_versions.project_id"], name="fk_repo_agent_versions_pack_scope"),
        ForeignKeyConstraint(["skill_export_id", "workspace_id", "project_id"], ["skill_exports.id", "skill_exports.workspace_id", "skill_exports.project_id"], name="fk_repo_agent_versions_skill_export_scope"),
        CheckConstraint("status IN ('draft', 'published', 'superseded', 'invalidated', 'failed')", name="ck_repo_agent_versions_status"),
        CheckConstraint("version >= 1", name="ck_repo_agent_versions_version_positive"),
        CheckConstraint("version_hash LIKE 'sha256:%' AND length(version_hash) = 71", name="ck_repo_agent_versions_hash_format"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    repo_agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repo_agents.id"), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resources.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_snapshots.id"))
    resource_manifest_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resource_manifests.id"))
    context_pack_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("context_pack_versions.id"))
    skill_export_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("skill_exports.id"))
    version_hash: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    diff_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    validation_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    install_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rollback_from_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scrubbed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
