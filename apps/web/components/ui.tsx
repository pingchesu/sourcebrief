import Link from 'next/link';
import type { ReactNode } from 'react';
import type { LifecycleStage, Readiness } from '../lib/lifecycle';
import { isIndexFailed, READINESS_LABEL, readinessTone } from '../lib/lifecycle';

export type Tone = 'ready' | 'warn' | 'risk' | 'neutral';

/**
 * Explicit semantic mapping from a backend status string to a UI tone.
 * Replaces the previous `includes()` heuristic so status classification is
 * predictable and easy to extend without accidental substring drift.
 */
const STATUS_TONES: Record<string, Tone> = {
  // ready / healthy
  active: 'ready', ok: 'ready', ready: 'ready', healthy: 'ready', enabled: 'ready',
  approved: 'ready', succeeded: 'ready', success: 'ready', completed: 'ready',
  fresh: 'ready', indexed: 'ready', serving: 'ready', current: 'ready', running: 'ready',
  // needs attention
  pending: 'warn', queued: 'warn', processing: 'warn', degraded: 'warn',
  stale: 'warn', warn: 'warn', warning: 'warn', review: 'warn', needs_review: 'warn',
  needs_update: 'warn', unreviewed: 'warn', ignored: 'warn', unknown: 'warn', loading: 'warn',
  archived: 'warn', disabled: 'warn', paused: 'warn', skipped: 'warn',
  // failure / risk
  failed: 'risk', error: 'risk', errored: 'risk', revoked: 'risk',
  deleted: 'risk', danger: 'risk', cancelled: 'risk', canceled: 'risk', expired: 'risk',
};

const TONE_CHIP: Record<Tone, string> = { ready: 'ok', warn: 'warn', risk: 'bad', neutral: '' };

export function statusTone(value?: string | null): Tone {
  if (!value) return 'neutral';
  return STATUS_TONES[value.trim().toLowerCase()] ?? 'neutral';
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) {
  return <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description ? <p className="muted">{description}</p> : null}</div>{actions ? <div className="toolbar">{actions}</div> : null}</div>;
}

export function Card({ children }: { children: ReactNode }) { return <section className="card">{children}</section>; }

export function SectionCard({ title, description, action, children }: { title: string; description?: ReactNode; action?: ReactNode; children: ReactNode }) {
  return <section className="card section-card">
    <div className="section-card-head">
      <div><h2 className="section-card-title">{title}</h2>{description ? <p className="muted section-card-desc">{description}</p> : null}</div>
      {action ? <div className="section-card-action">{action}</div> : null}
    </div>
    {children}
  </section>;
}

export function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return <div className="metric"><div className="metric-label">{label}</div><div className="metric-value">{value}</div>{hint ? <div className="metric-hint">{hint}</div> : null}</div>;
}

export function Chip({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`chip ${TONE_CHIP[tone]}`.trim()}>{children}</span>;
}

export function StatusChip({ value }: { value?: string | null }) {
  const v = value ?? 'unknown';
  return <span className={`chip ${TONE_CHIP[statusTone(value)]}`.trim()}>{v}</span>;
}

export function ActionLink({ href, label, description, tone = 'default' }: { href: string; label: string; description?: string; tone?: 'default' | 'primary' }) {
  return <Link href={href} className={`action-link ${tone === 'primary' ? 'primary' : ''}`.trim()}>
    <span className="action-link-label">{label}</span>
    {description ? <span className="action-link-desc">{description}</span> : null}
  </Link>;
}

export function AttentionRow({ tone, title, detail, meta, action }: { tone: Tone; title: ReactNode; detail?: ReactNode; meta?: ReactNode; action?: ReactNode }) {
  return <div className={`attention-row tone-${tone}`}>
    <div className="attention-row-main"><div className="attention-row-title">{title}</div>{detail ? <div className="attention-row-detail muted">{detail}</div> : null}</div>
    {meta ? <div className="attention-row-meta">{meta}</div> : null}
    {action ? <div className="attention-row-action">{action}</div> : null}
  </div>;
}

export function EmptyState({ text }: { text: string }) { return <div className="empty">{text}</div>; }

export function Field({ label, children }: { label: string; children: ReactNode }) { return <label><span className="label">{label}</span>{children}</label>; }

// --- PR2 lifecycle primitives (additive; presentational, logic lives in lib/lifecycle.ts) ---

/** Combined readiness lamp, mapping a readiness string to its tone + label. */
export function ReadinessBadge({ state, lastIndexStatus }: { state: Readiness; lastIndexStatus?: string | null }) {
  const failed = isIndexFailed(lastIndexStatus);
  return <Chip tone={readinessTone(state, lastIndexStatus)}>{failed ? 'index failed' : READINESS_LABEL[state]}</Chip>;
}

/** Stepper rendering the five lifecycle stages; tone/state come from props only. */
export function LifecyclePipeline({ stages }: { stages: LifecycleStage[] }) {
  return <ol className="lifecycle-pipeline">
    {stages.map((stage) => {
      const variant = stage.failed ? 'is-failed' : stage.reached ? 'is-reached' : 'is-pending';
      return <li key={stage.key} className={`lifecycle-stage ${variant}`}>
        <span className="lifecycle-stage-dot" aria-hidden="true" />
        <span className="lifecycle-stage-label">{stage.label}</span>
        <span className="lifecycle-stage-state">{stage.failed ? 'failed' : stage.reached ? 'done' : 'pending'}</span>
      </li>;
    })}
  </ol>;
}
