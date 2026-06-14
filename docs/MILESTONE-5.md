# Milestone 5: Review and Lifecycle

Milestone 5 adds resource governance so ContextSmith can control drift instead
of only ingesting more context.

## Scope

Implemented in this milestone:

- Resource review state: `review_status`, `review_note`, reviewer, review time,
  stale threshold, and archive timestamp.
- Cleanup operations:
  - review/update lifecycle metadata
  - archive resources, disabling retrieval
  - soft-delete resources, hiding them from lists and retrieval
- Review dashboard API:
  - freshness status
  - stale reasons
  - last index status/time
  - usage count and last used time
- Usage analytics API:
  - per-resource query count
  - retrieval hit count
  - context packet count
  - last used time

## Operational guarantees

- Archived/deleted resources are disabled for retrieval.
- Deleted resources remain as historical rows for auditability but are hidden from
  resource lists and review dashboards.
- Review and cleanup mutations require project membership.
- Read-only review/usage endpoints require project access and remain tenant scoped.

## Non-goals

- No automatic deletion policy yet.
- No scheduled stale-resource notification yet.
- No UI table beyond endpoint discoverability in the shell.

## Verification gate

```bash
make lint test
make compose-up migrate test-integration
make verify
```

Integration coverage must prove resource review, usage analytics, archive,
soft-delete, retrieval disabling, and unauthorized access denial.
