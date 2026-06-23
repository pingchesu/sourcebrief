from types import SimpleNamespace
from uuid import uuid4

from sourcebrief_api.schemas import ResourceRead


def _resource(**overrides):
    base = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "project_id": uuid4(),
        "type": "git",
        "name": "Large Repo",
        "uri": "https://github.com/example/large.git",
        "status": "active",
        "retrieval_enabled": True,
        "update_frequency": "manual",
        "current_snapshot_id": uuid4(),
        "review_status": "unreviewed",
        "review_note": None,
        "last_reviewed_at": None,
        "last_reviewed_by": None,
        "archived_at": None,
        "deleted_at": None,
        "next_refresh_at": None,
        "last_refresh_started_at": None,
        "last_refresh_finished_at": None,
        "stale_after_days": 30,
        "source_config": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_resource_read_marks_enabled_no_snapshot_as_not_queryable():
    resource = ResourceRead.model_validate(_resource(current_snapshot_id=None), from_attributes=True)

    assert resource.queryable is False
    assert resource.coverage_status == "not_queryable"
    assert "no current snapshot" in " ".join(resource.coverage_warnings)
    assert "retrieval is enabled" in " ".join(resource.coverage_warnings)


def test_resource_read_marks_explicit_limited_budget_as_partial():
    resource = ResourceRead.model_validate(_resource(source_config={"max_repo_files": 500}), from_attributes=True)

    assert resource.queryable is True
    assert resource.coverage_status == "partial"
    assert resource.index_diagnostics["configured_budgets"] == {"max_repo_files": 500}
    assert "evidence may be partial" in " ".join(resource.coverage_warnings)


def test_resource_read_failed_status_with_current_snapshot_remains_queryable_but_warns():
    resource = ResourceRead.model_validate(_resource(status="failed"), from_attributes=True)

    assert resource.queryable is True
    assert resource.coverage_status == "partial"
    assert "existing snapshot remains queryable" in " ".join(resource.coverage_warnings)
