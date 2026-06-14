from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
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


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_resource_name_per_project"),)
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
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
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
    rerank_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    score: Mapped[float] = mapped_column(nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
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
