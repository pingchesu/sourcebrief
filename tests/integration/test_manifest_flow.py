"""Integration tests for Milestone A1 — ResourceManifest and ResourceManifestFile ORM rows.

Requires a real Postgres instance with migrations applied (alembic upgrade head).
No HTTP endpoints, no workers, no Redis — ORM only.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from sourcebrief_api.main import _purge_resource_artifacts
from sourcebrief_shared.db import get_engine, get_sessionmaker
from sourcebrief_shared.models import (
    AuditEvent,
    Project,
    Resource,
    ResourceManifest,
    ResourceManifestFile,
    SourceSnapshot,
    User,
    Workspace,
)
from sourcebrief_worker.manifest import compute_manifest_hash
from sourcebrief_worker.manifest_store import ManifestFileInput, create_resource_manifest

pytestmark = pytest.mark.integration


def require_real_services() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"real Postgres services are not available: {exc}")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _make_hierarchy(session):
    """Create minimal Workspace/User/Project/Resource/SourceSnapshot rows."""
    ws = Workspace(name=_unique("ws"), slug=_unique("ws"))
    session.add(ws)

    user = User(email=f"{_unique('user')}@example.com")
    session.add(user)
    session.flush()

    project = Project(
        workspace_id=ws.id,
        name=_unique("project"),
        visibility="workspace",
        created_by=user.id,
    )
    session.add(project)
    session.flush()

    resource = Resource(
        workspace_id=ws.id,
        project_id=project.id,
        type="folder_bundle",
        name=_unique("bundle"),
        uri=f"bundle://{_unique('bundle')}",
        source_config={},
        created_by=user.id,
    )
    session.add(resource)
    session.flush()

    snapshot = SourceSnapshot(
        workspace_id=ws.id,
        project_id=project.id,
        resource_id=resource.id,
        version=_unique("v"),
        version_kind="content_hash",
    )
    session.add(snapshot)
    session.flush()

    return ws, project, resource, snapshot


# ---------------------------------------------------------------------------
# Table existence (alembic upgrade check)
# ---------------------------------------------------------------------------


def test_alembic_upgrade_creates_tables() -> None:
    require_real_services()
    engine = get_engine()
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "resource_manifests" in tables, (
        "resource_manifests table not found; run: alembic upgrade head"
    )
    assert "resource_manifest_files" in tables, (
        "resource_manifest_files table not found; run: alembic upgrade head"
    )


# ---------------------------------------------------------------------------
# Basic row creation
# ---------------------------------------------------------------------------


def test_create_manifest_row() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws, project, resource, snapshot = _make_hierarchy(session)
        manifest_hash = compute_manifest_hash([])
        manifest = ResourceManifest(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            manifest_hash=manifest_hash,
            file_count=3,
            total_bytes=1024,
        )
        session.add(manifest)
        session.commit()

        fetched = session.get(ResourceManifest, manifest.id)
        assert fetched is not None
        assert fetched.manifest_hash == manifest_hash
        assert fetched.file_count == 3
        assert fetched.total_bytes == 1024
        assert fetched.parser_warning_count == 0
        assert fetched.unsupported_file_count == 0
        assert fetched.created_at is not None
    finally:
        session.rollback()
        session.close()


def test_create_manifest_file_rows() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws, project, resource, snapshot = _make_hierarchy(session)
        manifest = ResourceManifest(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            manifest_hash=compute_manifest_hash([]),
        )
        session.add(manifest)
        session.flush()

        paths = ["docs/a.md", "src/b.py", "README.md"]
        for path in paths:
            session.add(
                ResourceManifestFile(
                    workspace_id=ws.id,
                    project_id=project.id,
                    resource_id=resource.id,
                    resource_manifest_id=manifest.id,
                    normalized_path=path,
                    path_hash=_sha256(path),
                    content_hash=_sha256(f"content:{path}"),
                    size_bytes=512,
                    status="pending",
                )
            )
        session.commit()

        rows = (
            session.query(ResourceManifestFile)
            .filter_by(resource_manifest_id=manifest.id)
            .all()
        )
        assert len(rows) == 3
        found_paths = {r.normalized_path for r in rows}
        assert found_paths == set(paths)
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Unique constraint — one manifest per snapshot
# ---------------------------------------------------------------------------


def test_unique_constraint_snapshot() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws, project, resource, snapshot = _make_hierarchy(session)
        h = compute_manifest_hash([])
        m1 = ResourceManifest(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            manifest_hash=h,
        )
        session.add(m1)
        session.commit()

        m2 = ResourceManifest(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,  # same snapshot_id → violation
            manifest_hash=h,
        )
        session.add(m2)
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Unique constraint — one row per (manifest, normalized_path)
# ---------------------------------------------------------------------------


def test_unique_constraint_manifest_path() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws, project, resource, snapshot = _make_hierarchy(session)
        manifest = ResourceManifest(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            manifest_hash=compute_manifest_hash([]),
        )
        session.add(manifest)
        session.flush()

        common = dict(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            resource_manifest_id=manifest.id,
            normalized_path="docs/guide.md",
            path_hash=_sha256("docs/guide.md"),
            content_hash=_sha256("content:docs/guide.md"),
            size_bytes=100,
        )
        session.add(ResourceManifestFile(**common))
        session.commit()

        session.add(ResourceManifestFile(**{**common, "path_hash": _sha256("docs/guide.md")}))
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Workspace scoping
# ---------------------------------------------------------------------------


def test_workspace_scoping() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws_a, proj_a, res_a, snap_a = _make_hierarchy(session)
        ws_b, proj_b, res_b, snap_b = _make_hierarchy(session)

        h = compute_manifest_hash([])
        manifest_a = ResourceManifest(
            workspace_id=ws_a.id,
            project_id=proj_a.id,
            resource_id=res_a.id,
            source_snapshot_id=snap_a.id,
            manifest_hash=h,
        )
        manifest_b = ResourceManifest(
            workspace_id=ws_b.id,
            project_id=proj_b.id,
            resource_id=res_b.id,
            source_snapshot_id=snap_b.id,
            manifest_hash=h,
        )
        session.add(manifest_a)
        session.add(manifest_b)
        session.commit()

        rows_a = (
            session.query(ResourceManifest).filter_by(workspace_id=ws_a.id).all()
        )
        rows_b = (
            session.query(ResourceManifest).filter_by(workspace_id=ws_b.id).all()
        )
        assert all(r.workspace_id == ws_a.id for r in rows_a)
        assert all(r.workspace_id == ws_b.id for r in rows_b)
        # workspace A rows don't appear in workspace B query
        ids_a = {r.id for r in rows_a}
        ids_b = {r.id for r in rows_b}
        assert ids_a.isdisjoint(ids_b)
    finally:
        session.rollback()
        session.close()


def test_manifest_scope_mismatch_rejected() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        _ws_a, _proj_a, _res_a, snap_a = _make_hierarchy(session)
        ws_b, proj_b, res_b, _snap_b = _make_hierarchy(session)
        session.add(
            ResourceManifest(
                workspace_id=ws_b.id,
                project_id=proj_b.id,
                resource_id=res_b.id,
                source_snapshot_id=snap_a.id,
                manifest_hash=compute_manifest_hash([]),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_manifest_file_scope_mismatch_rejected() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws_a, proj_a, res_a, snap_a = _make_hierarchy(session)
        ws_b, proj_b, res_b, _snap_b = _make_hierarchy(session)
        manifest = ResourceManifest(
            workspace_id=ws_a.id,
            project_id=proj_a.id,
            resource_id=res_a.id,
            source_snapshot_id=snap_a.id,
            manifest_hash=compute_manifest_hash([]),
        )
        session.add(manifest)
        session.flush()

        session.add(
            ResourceManifestFile(
                workspace_id=ws_b.id,
                project_id=proj_b.id,
                resource_id=res_b.id,
                resource_manifest_id=manifest.id,
                normalized_path="docs/mismatch.md",
                path_hash=_sha256("docs/mismatch.md"),
                content_hash=_sha256("content:docs/mismatch.md"),
                size_bytes=10,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_manifest_check_constraints_reject_corrupt_values() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws, project, resource, snapshot = _make_hierarchy(session)
        session.add(
            ResourceManifest(
                workspace_id=ws.id,
                project_id=project.id,
                resource_id=resource.id,
                source_snapshot_id=snapshot.id,
                manifest_hash=compute_manifest_hash([]),
                file_count=-1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        ws, project, resource, snapshot = _make_hierarchy(session)
        manifest = ResourceManifest(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            manifest_hash=compute_manifest_hash([]),
        )
        session.add(manifest)
        session.flush()
        session.add(
            ResourceManifestFile(
                workspace_id=ws.id,
                project_id=project.id,
                resource_id=resource.id,
                resource_manifest_id=manifest.id,
                normalized_path="docs/bad.md",
                path_hash="not-a-sha256",
                content_hash=_sha256("content:docs/bad.md"),
                size_bytes=-1,
                status="not-a-valid-status",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Audit event evidence
# ---------------------------------------------------------------------------


def test_audit_event_on_manifest_create() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws, project, resource, snapshot = _make_hierarchy(session)
        manifest = create_resource_manifest(
            session,
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            files=[
                ManifestFileInput(
                    normalized_path="docs/guide.md",
                    content_hash=_sha256("content:docs/guide.md"),
                    size_bytes=128,
                    parser="markdown",
                    parser_version="1",
                )
            ],
        )
        session.commit()

        fetched = (
            session.query(AuditEvent)
            .filter_by(target_id=manifest.id, action="manifest.created")
            .first()
        )
        assert fetched is not None
        assert fetched.target_type == "resource_manifest"
        assert fetched.target_ref["resource_id"] == str(resource.id)
        assert fetched.target_ref["snapshot_id"] == str(snapshot.id)
        assert fetched.meta["manifest_hash"] == manifest.manifest_hash
        assert fetched.meta["file_count"] == 1
        assert fetched.meta["total_bytes"] == 128
    finally:
        session.rollback()
        session.close()


def test_resource_purge_removes_manifest_rows() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws, project, resource, snapshot = _make_hierarchy(session)
        manifest = create_resource_manifest(
            session,
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            files=[
                ManifestFileInput(
                    normalized_path="docs/delete-me.md",
                    content_hash=_sha256("content:docs/delete-me.md"),
                    size_bytes=64,
                )
            ],
        )
        manifest_id = manifest.id
        session.flush()

        counts = _purge_resource_artifacts(session, resource)
        session.commit()

        assert counts["resource_manifest_files"] == 1
        assert counts["resource_manifests"] == 1
        assert counts["resources"] == 1
        session.expire_all()
        assert session.get(ResourceManifest, manifest_id) is None
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Content hash index lookup
# ---------------------------------------------------------------------------


def test_content_hash_index_lookup() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws, project, resource, snapshot = _make_hierarchy(session)
        manifest = ResourceManifest(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            manifest_hash=compute_manifest_hash([]),
        )
        session.add(manifest)
        session.flush()

        unique_hash = _sha256("data/report.csv content")
        file_row = ResourceManifestFile(
            workspace_id=ws.id,
            project_id=project.id,
            resource_id=resource.id,
            resource_manifest_id=manifest.id,
            normalized_path="data/report.csv",
            path_hash=_sha256("data/report.csv"),
            content_hash=unique_hash,
            size_bytes=9999,
        )
        session.add(file_row)
        session.commit()

        found = (
            session.query(ResourceManifestFile)
            .filter_by(content_hash=unique_hash)
            .first()
        )
        assert found is not None
        assert found.normalized_path == "data/report.csv"
        assert found.size_bytes == 9999

        indexes = inspect(get_engine()).get_indexes("resource_manifest_files")
        assert "ix_resource_manifest_files_content_hash" in {index["name"] for index in indexes}
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Project and resource scoping
# ---------------------------------------------------------------------------


def test_project_scoping() -> None:
    require_real_services()
    session = get_sessionmaker()()
    try:
        ws_a, proj_a, res_a, snap_a = _make_hierarchy(session)
        ws_b, proj_b, res_b, snap_b = _make_hierarchy(session)

        h = compute_manifest_hash([])
        session.add(
            ResourceManifest(
                workspace_id=ws_a.id, project_id=proj_a.id, resource_id=res_a.id,
                source_snapshot_id=snap_a.id, manifest_hash=h,
            )
        )
        session.add(
            ResourceManifest(
                workspace_id=ws_b.id, project_id=proj_b.id, resource_id=res_b.id,
                source_snapshot_id=snap_b.id, manifest_hash=h,
            )
        )
        session.commit()

        proj_a_rows = session.query(ResourceManifest).filter_by(project_id=proj_a.id).all()
        proj_b_rows = session.query(ResourceManifest).filter_by(project_id=proj_b.id).all()
        assert all(r.project_id == proj_a.id for r in proj_a_rows)
        assert all(r.project_id == proj_b.id for r in proj_b_rows)
    finally:
        session.rollback()
        session.close()
