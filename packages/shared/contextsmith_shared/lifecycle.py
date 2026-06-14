from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from contextsmith_shared.models import Resource

_FREQUENCY_RE = re.compile(r"^every[-_ ]?(?P<count>\d+)[-_ ]?(?P<unit>minute|minutes|min|mins|m|hour|hours|h|day|days|d|week|weeks|w)$")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def parse_update_frequency(value: str | None) -> timedelta | None:
    """Convert alpha update_frequency strings into an interval.

    Supported values intentionally stay conservative for open-source alpha:
    manual/none/disabled, hourly, daily, weekly, and `every N minutes|hours|days|weeks`.
    Invalid values are treated as manual by scheduler callers; API validation may
    reject them separately when it wants stricter UX.
    """
    normalized = (value or "manual").strip().lower().replace("_", "-")
    if normalized in {"", "manual", "none", "disabled", "off", "never"}:
        return None
    if normalized in {"hourly", "hour"}:
        return timedelta(hours=1)
    if normalized in {"daily", "day"}:
        return timedelta(days=1)
    if normalized in {"weekly", "week"}:
        return timedelta(weeks=1)
    match = _FREQUENCY_RE.match(normalized)
    if not match:
        return None
    count = int(match.group("count"))
    unit = match.group("unit")
    if count <= 0:
        return None
    if unit in {"minute", "minutes", "min", "mins", "m"}:
        return timedelta(minutes=count)
    if unit in {"hour", "hours", "h"}:
        return timedelta(hours=count)
    if unit in {"day", "days", "d"}:
        return timedelta(days=count)
    if unit in {"week", "weeks", "w"}:
        return timedelta(weeks=count)
    return None


def compute_next_refresh_at(resource: Resource, *, now: datetime | None = None) -> datetime | None:
    interval = parse_update_frequency(resource.update_frequency)
    if interval is None:
        return None
    now = now or datetime.now(UTC)
    base = _aware(resource.last_refresh_finished_at) or _aware(resource.created_at) or now
    candidate = base + interval
    return candidate if candidate > now else now


def is_refresh_due(resource: Resource, *, now: datetime | None = None) -> bool:
    if resource.deleted_at is not None or resource.archived_at is not None:
        return False
    if resource.status in {"deleted", "archived"}:
        return False
    if not resource.retrieval_enabled:
        return False
    if parse_update_frequency(resource.update_frequency) is None:
        return False
    now = now or datetime.now(UTC)
    next_refresh_at = _aware(resource.next_refresh_at) or compute_next_refresh_at(resource, now=now)
    return next_refresh_at is not None and next_refresh_at <= now
