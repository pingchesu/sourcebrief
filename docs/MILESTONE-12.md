# M12 — Scheduled Refresh / Reindex / Restore / Purge Lifecycle

## Goal

Make resource lifecycle operationally usable: resources can refresh on a schedule, be restored after archive/soft delete, and be hard-purged when intentionally removed.

## Delivered behavior

- `update_frequency` drives `next_refresh_at` for active resources.
- Worker maintenance scheduler scans due resources and enqueues `scheduled` index runs.
- Project API can enqueue due scheduled refreshes with a dry-run mode.
- Scheduler uses row locks for non-dry-run scans and skips resources with active `enqueueing`/`queued`/`running` runs.
- Archive/delete clears `next_refresh_at` and disables retrieval.
- Restore reactivates archived or soft-deleted resources and recomputes `next_refresh_at`.
- Purge requires a prior soft delete, refuses active index runs, and removes resource artifacts in FK-safe order.
- CLI exposes `resource schedule-due`, `resource restore`, and `resource purge`.

## Supported update frequencies

Alpha scheduler recognizes:

- `manual`, `none`, `disabled`, `off`, `never` — no scheduled refresh.
- `hourly`
- `daily`
- `weekly`
- `every N minutes|hours|days|weeks`, e.g. `every 6 hours`.

Invalid/unknown values behave as manual for scheduling. Future UI should validate these values before save.

## API examples

```bash
# Find due refreshes without enqueuing jobs
curl -X POST \
  "$SOURCEBRIEF_API/workspaces/$WS/projects/$PROJECT/scheduled-refreshes?dry_run=true" \
  -H "Authorization: Bearer TOKEN"

# Enqueue due refreshes for a project
curl -X POST \
  "$SOURCEBRIEF_API/workspaces/$WS/projects/$PROJECT/scheduled-refreshes" \
  -H "Authorization: Bearer TOKEN"

# Restore archived or soft-deleted resource
curl -X POST \
  "$SOURCEBRIEF_API/workspaces/$WS/projects/$PROJECT/resources/$RESOURCE/restore" \
  -H "Authorization: Bearer TOKEN"

# Hard purge after soft delete
curl -X POST \
  "$SOURCEBRIEF_API/workspaces/$WS/projects/$PROJECT/resources/$RESOURCE/purge" \
  -H "Authorization: Bearer TOKEN"
```

## CLI examples

```bash
sourcebrief resource schedule-due --workspace-id $WS --project-id $PROJECT --dry-run
sourcebrief resource schedule-due --workspace-id $WS --project-id $PROJECT
sourcebrief resource restore --workspace-id $WS --project-id $PROJECT --resource-id $RESOURCE
sourcebrief resource purge --workspace-id $WS --project-id $PROJECT --resource-id $RESOURCE
```

## Safety and boundaries

- Scheduled refresh requires `resource:refresh` scope and project membership.
- Resource-scoped tokens only schedule their allowed resources.
- Restore/purge require `resource:write` and project membership.
- Purge refuses active resources and active index runs; callers must soft-delete first and wait for active jobs to finish or fail.
- Worker-triggered scheduled refreshes are represented by `index_runs.trigger='scheduled'` and a system `resource.scheduled_refresh` audit event.
- API-triggered scheduled refreshes also write a project-level actor audit event when not dry-run.

## Verification

Required gate for M12:

```bash
make lint
.venv/bin/pytest tests/unit tests/integration -q
make qa-smoke
```

Integration coverage includes:

- scheduled due detection and enqueue
- scheduled run execution through real ingestion worker code
- `next_refresh_at` advancement after successful refresh
- archive → restore → retrieval works
- soft delete → restore → soft delete → hard purge
- purge denied while an active index run exists
- resource-scoped token scheduling/restore denial boundaries
- membership denial for lifecycle/scheduler endpoints
