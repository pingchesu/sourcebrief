from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sourcebrief_shared.lifecycle import (
    compute_next_refresh_at,
    is_refresh_due,
    parse_update_frequency,
)


def resource(**overrides):
    defaults = {
        "update_frequency": "manual",
        "deleted_at": None,
        "archived_at": None,
        "status": "active",
        "retrieval_enabled": True,
        "next_refresh_at": None,
        "last_refresh_finished_at": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_parse_update_frequency_supported_values():
    assert parse_update_frequency("manual") is None
    assert parse_update_frequency("disabled") is None
    assert parse_update_frequency("hourly") == timedelta(hours=1)
    assert parse_update_frequency("daily") == timedelta(days=1)
    assert parse_update_frequency("weekly") == timedelta(weeks=1)
    assert parse_update_frequency("every 6 hours") == timedelta(hours=6)
    assert parse_update_frequency("every-2-days") == timedelta(days=2)
    assert parse_update_frequency("nonsense") is None


def test_compute_next_refresh_and_due_logic():
    now = datetime(2026, 1, 2, 12, tzinfo=UTC)
    scheduled = resource(update_frequency="daily", last_refresh_finished_at=datetime(2026, 1, 2, 0, tzinfo=UTC))
    assert compute_next_refresh_at(scheduled, now=now) == datetime(2026, 1, 3, 0, tzinfo=UTC)

    due = resource(update_frequency="daily", next_refresh_at=datetime(2026, 1, 2, 11, tzinfo=UTC))
    assert is_refresh_due(due, now=now) is True

    future = resource(update_frequency="daily", next_refresh_at=datetime(2026, 1, 2, 13, tzinfo=UTC))
    assert is_refresh_due(future, now=now) is False

    archived = resource(update_frequency="daily", archived_at=now, next_refresh_at=datetime(2026, 1, 2, 11, tzinfo=UTC))
    assert is_refresh_due(archived, now=now) is False

    disabled = resource(update_frequency="daily", retrieval_enabled=False, next_refresh_at=datetime(2026, 1, 2, 11, tzinfo=UTC))
    assert is_refresh_due(disabled, now=now) is False
