import type { Resource, ReviewItem } from './types';
import type { Tone } from '../components/ui';

// Single source of truth for source lifecycle derivation. Pure functions only —
// no React, no API calls — so both /sources and (future) other surfaces can
// reuse identical lifecycle logic without drift. The `readiness()` ladder here
// is kept equivalent to the inline version in /repo-agents.

export type Readiness = 'inactive' | 'retrieval-off' | 'not-indexed' | 'needs-review' | 'ready';

export const READINESS_LABEL: Record<Readiness, string> = {
  inactive: 'inactive',
  'retrieval-off': 'retrieval off',
  'not-indexed': 'not indexed',
  'needs-review': 'needs review',
  ready: 'ready',
};

const FAILED_INDEX_STATUSES = new Set(['failed', 'error', 'errored', 'cancelled', 'canceled']);

/** True when the latest index run for a source ended in failure. */
export function isIndexFailed(status?: string | null): boolean {
  return Boolean(status) && FAILED_INDEX_STATUSES.has(String(status).trim().toLowerCase());
}

/** A source is visible in the hub unless it has been deleted. */
export function isVisible(resource: Resource): boolean {
  return !resource.deleted_at;
}

/** A source is active (counts toward lifecycle) when live and not archived/deleted. */
export function isActive(resource: Resource): boolean {
  return resource.status === 'active' && !resource.deleted_at && !resource.archived_at;
}

/**
 * Combined readiness lamp. Equivalent to the inline `readiness()` in
 * /repo-agents — keep the two in lockstep if either changes.
 */
export function readiness(resource: Resource, review?: ReviewItem): Readiness {
  if (resource.status !== 'active') return 'inactive';
  if (!resource.retrieval_enabled) return 'retrieval-off';
  if (!resource.current_snapshot_id) return 'not-indexed';
  if (review?.freshness_status && review.freshness_status !== 'fresh') return 'needs-review';
  return 'ready';
}

/** Map readiness (and a failed index run) onto a PR1 tone. */
export function readinessTone(state: Readiness, lastIndexStatus?: string | null): Tone {
  if (isIndexFailed(lastIndexStatus)) return 'risk';
  switch (state) {
    case 'ready':
      return 'ready';
    case 'inactive':
      return 'neutral';
    default:
      return 'warn';
  }
}

export type FreshnessLabel = { label: string; ageDays: number | null; tone: Tone };

const FRESHNESS_TONE: Record<string, Tone> = { fresh: 'ready', stale: 'warn' };

/** Human freshness label + tone derived from the batched review item. */
export function freshnessLabel(review?: ReviewItem): FreshnessLabel {
  if (!review || !review.freshness_status) return { label: '—', ageDays: null, tone: 'neutral' };
  return {
    label: review.freshness_status,
    ageDays: review.freshness_age_days,
    tone: FRESHNESS_TONE[review.freshness_status.trim().toLowerCase()] ?? 'warn',
  };
}

export type LifecycleStage = { key: string; label: string; reached: boolean; failed: boolean };

/**
 * The five product lifecycle stages from the spec:
 * connected → indexed → reviewed → retrieval-ready → serving/fresh.
 * `lastIndexStatus` comes from the batched review item (list) or latest run (detail).
 */
export function lifecycleStages(resource: Resource, review?: ReviewItem, lastIndexStatus?: string | null): LifecycleStage[] {
  const connected = isActive(resource);
  const indexFailed = isIndexFailed(lastIndexStatus);
  const indexed = Boolean(resource.current_snapshot_id) && !indexFailed;
  const reviewed = resource.review_status === 'approved';
  const retrievalReady = resource.retrieval_enabled && indexed;
  const fresh = review?.freshness_status === 'fresh';
  const serving = connected && indexed && reviewed && retrievalReady && fresh;
  return [
    { key: 'connected', label: 'Connected', reached: connected, failed: false },
    { key: 'indexed', label: 'Indexed', reached: indexed, failed: indexFailed },
    { key: 'reviewed', label: 'Reviewed', reached: reviewed, failed: false },
    { key: 'retrieval-ready', label: 'Retrieval-ready', reached: retrievalReady, failed: false },
    { key: 'serving', label: 'Serving', reached: serving, failed: false },
  ];
}
