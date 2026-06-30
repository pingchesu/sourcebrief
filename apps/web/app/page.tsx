'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import { PageHeader, SectionCard, Metric, Chip, StatusChip, ActionLink, AttentionRow, EmptyState, type Tone } from '../components/ui';
import { usePlatform } from '../lib/platform-context';
import { fmt } from '../lib/api';
import type { ReviewItem, UsageItem } from '../lib/types';

type Readiness = 'ready' | 'attention' | 'setup';
type AttentionEntry = { key: string; tone: Tone; title: string; detail?: string; meta?: string; href: string; action: string };

const READINESS_COPY: Record<Readiness, { state: string; tone: Tone; title: string }> = {
  ready: { state: 'Ready', tone: 'ready', title: 'Agent is serving cited context' },
  attention: { state: 'Needs attention', tone: 'warn', title: 'Agent is running with open issues' },
  setup: { state: 'Setup required', tone: 'risk', title: 'Finish setup to bring the agent online' },
};

export default function CommandCenterPage() {
  const { agent, provider, workspace, project, settings, signedIn, resources, reviewItems, usageItems, loading, error, reload } = usePlatform();

  const initialLoading = loading && signedIn && !workspace && !project && !agent && resources.length === 0;
  const providerOk = provider?.status === 'ok';

  // --- Derived source/quality state (transparent, real-data only). ---
  const visibleResources = useMemo(() => resources.filter((r) => !r.deleted_at), [resources]);
  const activeResources = useMemo(() => visibleResources.filter((r) => r.status === 'active'), [visibleResources]);
  const gitResources = useMemo(() => activeResources.filter((r) => r.type === 'git'), [activeResources]);
  const retrievalEnabled = useMemo(() => activeResources.filter((r) => r.retrieval_enabled), [activeResources]);
  const failedResources = useMemo(() => visibleResources.filter((r) => ['failed', 'error'].includes(r.status.toLowerCase())), [visibleResources]);
  const reviewRisks = useMemo(() => reviewItems.filter((item) => item.freshness_status !== 'fresh' || item.stale_reasons.length > 0), [reviewItems]);
  const staleResources = useMemo(() => reviewItems.filter((item) => item.freshness_status !== 'fresh'), [reviewItems]);

  const usageQueries = usageItems.reduce((sum, item) => sum + item.query_count, 0);
  const usageHits = usageItems.reduce((sum, item) => sum + item.hit_count, 0);
  const contextPackets = usageItems.reduce((sum, item) => sum + item.context_packet_count, 0);

  const hasActiveSource = activeResources.length > 0;

  const readiness: Readiness = initialLoading
    ? 'setup'
    : !signedIn || !workspace || !project || !agent || !hasActiveSource
      ? 'setup'
      : (!providerOk || failedResources.length > 0 || reviewRisks.length > 0)
        ? 'attention'
        : 'ready';

  // --- Attention queue, built only from real signals. ---
  const attention = useMemo<AttentionEntry[]>(() => {
    const items: AttentionEntry[] = [];
    if (initialLoading) {
      items.push({ key: 'loading', tone: 'warn', title: 'Loading workspace context', detail: 'Fetching workspace, project, agent, and source state from the API.', href: '/config', action: 'View config' });
      return items;
    }
    if (!signedIn) {
      items.push({ key: 'session', tone: 'risk', title: 'No active session', detail: 'Sign in with your SourceBrief account to load this workspace.', href: '/login', action: 'Sign in' });
      return items;
    }
    if (!workspace || !project) items.push({ key: 'scope', tone: 'risk', title: 'Workspace or project not loaded', detail: 'Choose your workspace and project in Settings.', href: '/config', action: 'Open settings' });
    if (!agent) items.push({ key: 'agent', tone: 'warn', title: 'Project agent not generated', detail: 'Generate the project agent once sources are indexed.', href: '/agent-profile', action: 'Project agent' });
    if (!hasActiveSource) items.push({ key: 'sources', tone: 'warn', title: 'No active sources connected', detail: 'Connect a git repo, URL, or document to start building context.', href: '/sources', action: 'Connect' });
    if (provider && !providerOk) items.push({ key: 'provider', tone: 'warn', title: `Embedding provider ${provider.status}`, detail: `${provider.embedding.provider}/${provider.embedding.model} · ${provider.embedding.namespace}`, href: '/config', action: 'Diagnose' });
    if (failedResources.length > 0) items.push({ key: 'failed', tone: 'risk', title: `${failedResources.length} source${failedResources.length > 1 ? 's' : ''} failed to index`, detail: failedResources.map((r) => r.name).slice(0, 3).join(', '), href: '/sources', action: 'Open sources' });
    for (const item of reviewRisks.slice(0, 4)) {
      const reason = item.stale_reasons[0] ?? `${item.freshness_status}${item.freshness_age_days != null ? ` · ${item.freshness_age_days}d old` : ''}`;
      items.push({ key: `review-${item.resource.id}`, tone: 'warn', title: item.resource.name, detail: reason, meta: `${item.usage_count} uses`, href: '/quality', action: 'Open quality' });
    }
    return items;
  }, [initialLoading, signedIn, workspace, project, agent, hasActiveSource, provider, providerOk, failedResources, reviewRisks]);

  const nextAction = useMemo<{ label: string; href: string }>(() => {
    if (initialLoading) return { label: 'Loading workspace…', href: '/config' };
    if (!signedIn) return { label: 'Sign in', href: '/login' };
    if (!workspace || !project) return { label: 'Open configuration', href: '/config' };
    if (!hasActiveSource) return { label: 'Connect a source', href: '/sources' };
    if (!agent) return { label: 'Generate project agent', href: '/agent-profile' };
    if (readiness === 'attention') return { label: 'Open quality gate', href: '/quality' };
    return { label: 'Open Workbench', href: '/workbench' };
  }, [initialLoading, signedIn, workspace, project, hasActiveSource, agent, readiness]);

  // --- Source map preview: stale first, then by usage. ---
  const usageByResource = useMemo(() => {
    const map = new Map<string, UsageItem>();
    for (const item of usageItems) map.set(item.resource_id, item);
    return map;
  }, [usageItems]);

  const sourcePreview = useMemo<ReviewItem[]>(() => {
    return [...reviewItems].sort((a, b) => {
      const aStale = a.freshness_status !== 'fresh' ? 1 : 0;
      const bStale = b.freshness_status !== 'fresh' ? 1 : 0;
      if (aStale !== bStale) return bStale - aStale;
      return b.usage_count - a.usage_count;
    }).slice(0, 6);
  }, [reviewItems]);

  const copy = READINESS_COPY[readiness];

  return <main className="page">
    <PageHeader
      eyebrow="Command Center"
      title={project?.name ?? 'Command Center'}
      description={workspace ? `Agent context console for ${workspace.name}. Connect sources, watch context freshness, and ship a cited agent pack.` : 'Connect sources, watch context freshness, and ship a cited agent pack for Hermes, Codex, and Claude.'}
      actions={<>
        <Link className="btn" href={nextAction.href}>{nextAction.label}</Link>
        <button className="btn secondary" onClick={() => reload()} disabled={loading}>{loading ? 'Loading…' : 'Reload'}</button>
      </>}
    />

    {error ? <div className="notice error">Could not load platform data: {error}</div> : null}

    <section className={`card readiness tone-${copy.tone}`}>
      <div className="readiness-main">
        <span className="readiness-state">{copy.state}</span>
        <span className="readiness-title">{copy.title}</span>
        <span className="muted">
          {initialLoading && 'Loading workspace, project, agent, and source state from the API.'}
          {!initialLoading && readiness === 'ready' && 'Signed in, provider healthy, sources active, no open review risks.'}
          {!initialLoading && readiness === 'attention' && `${[!providerOk && provider ? 'provider degraded' : null, failedResources.length ? `${failedResources.length} failed source(s)` : null, reviewRisks.length ? `${reviewRisks.length} review risk(s)` : null].filter(Boolean).join(' · ') || 'Open issues need attention.'}`}
          {!initialLoading && readiness === 'setup' && 'Complete the highlighted steps in the attention queue to bring the agent online.'}
        </span>
      </div>
      <Link className="btn" href={nextAction.href}>{nextAction.label}</Link>
    </section>

    <section className="card">
      <div className="health-strip">
        <div className="health-item"><span className="label">Session</span><span className="health-item-value">{signedIn ? <Chip tone="ready">Signed in</Chip> : <Chip tone="risk">Signed out</Chip>}</span></div>
        <div className="health-item"><span className="label">Provider</span><span className="health-item-value"><StatusChip value={provider?.status ?? (signedIn ? 'loading' : 'signed out')} /></span></div>
        <div className="health-item"><span className="label">Embedding</span><span className="health-item-value code">{provider ? `${provider.embedding.provider}/${provider.embedding.model}` : '—'}</span></div>
        <div className="health-item"><span className="label">Namespace</span><span className="health-item-value code">{provider?.embedding.namespace ?? '—'}</span></div>
        <div className="health-item"><span className="label">Agent</span><span className="health-item-value">{agent ? <Chip tone="ready">online</Chip> : <Chip tone="warn">not generated</Chip>}</span></div>
      </div>
    </section>

    <div className="grid four">
      <Metric label="Active sources" value={activeResources.length} hint={`${gitResources.length} git`} />
      <Metric label="Retrieval enabled" value={retrievalEnabled.length} hint={`of ${activeResources.length} active`} />
      <Metric label="Review risks" value={reviewRisks.length} hint={`${staleResources.length} stale`} />
      <Metric label="Context packets" value={contextPackets} hint={`${usageHits} hits`} />
    </div>

    <div className="grid two">
      <SectionCard
        title="Agent readiness"
        description="Project agent backed by indexed repo and document sources."
        action={<Link className="btn secondary" href="/agent-profile">Project agent</Link>}
      >
        {agent ? <>
          <div className="grid three">
            <Metric label="Runtime" value={agent.default_runtime} />
            <Metric label="Snapshots" value={agent.current_snapshot_count} />
            <Metric label="Graph" value={`${agent.graph_node_count}/${agent.graph_edge_count}`} hint="nodes / edges" />
          </div>
          <p className="muted">{agent.description || 'Generated project agent composed from active repo and document sources.'}</p>
          <div className="muted">Last indexed {fmt(agent.last_index_finished_at)} · {agent.resource_count} resources</div>
        </> : <EmptyState text={signedIn ? 'No project agent yet. Connect and index sources, then generate the agent.' : 'Sign in to load the project agent.'} />}
      </SectionCard>

      <SectionCard
        title="Source coverage"
        description="Lifecycle of connected context sources."
        action={<Link className="btn secondary" href="/sources">All sources</Link>}
      >
        {hasActiveSource ? <>
          <div className="grid three">
            <Metric label="Git" value={gitResources.length} />
            <Metric label="Retrieval" value={retrievalEnabled.length} />
            <Metric label="Failed" value={failedResources.length} />
          </div>
          <div className="toolbar">
            <Chip tone="ready">{activeResources.length} active</Chip>
            {staleResources.length > 0 ? <Chip tone="warn">{staleResources.length} stale</Chip> : null}
            {failedResources.length > 0 ? <Chip tone="risk">{failedResources.length} failed</Chip> : null}
          </div>
        </> : <EmptyState text={signedIn ? 'No active sources connected. Connect a git repo, URL, or document to start.' : 'Sign in to load sources.'} />}
      </SectionCard>
    </div>

    <SectionCard
      title="Attention queue"
      description="What needs action right now, derived from live source and review state."
      action={<Link className="btn secondary" href="/quality">Quality gate</Link>}
    >
      {attention.length === 0
        ? <EmptyState text="Nothing needs attention. Provider healthy, sources active, no open review risks." />
        : <div className="attention-list">
          {attention.map((entry) => (
            <AttentionRow
              key={entry.key}
              tone={entry.tone}
              title={entry.title}
              detail={entry.detail}
              meta={entry.meta}
              action={<Link className="btn secondary" href={entry.href}>{entry.action}</Link>}
            />
          ))}
        </div>}
    </SectionCard>

    <div className="grid two">
      <SectionCard
        title="Source map"
        description="Top sources by attention priority (stale first, then most used)."
        action={<Link className="btn secondary" href="/sources">Open sources</Link>}
      >
        {sourcePreview.length === 0
          ? <EmptyState text={signedIn ? 'No sources to map yet.' : 'Sign in to load the source map.'} />
          : <div className="table-wrap"><table>
            <thead><tr><th>Source</th><th>Type</th><th>Freshness</th><th>Uses</th></tr></thead>
            <tbody>
              {sourcePreview.map((item) => (
                <tr key={item.resource.id}>
                  <td><strong>{item.resource.name}</strong><div className="muted">{item.last_index_status ? `index ${item.last_index_status}` : 'not indexed'}</div></td>
                  <td>{item.resource.type}</td>
                  <td><StatusChip value={item.freshness_status} /></td>
                  <td>{usageByResource.get(item.resource.id)?.query_count ?? item.usage_count}</td>
                </tr>
              ))}
            </tbody>
          </table></div>}
      </SectionCard>

      <SectionCard
        title="Retrieval usage"
        description="Real query activity served from indexed context."
        action={<Link className="btn secondary" href="/workbench">Open Workbench</Link>}
      >
        {usageItems.length === 0
          ? <EmptyState text="No retrieval usage recorded yet. Usage appears here once the agent answers queries." />
          : <>
            <div className="grid three">
              <Metric label="Queries" value={usageQueries} />
              <Metric label="Hits" value={usageHits} />
              <Metric label="Packets" value={contextPackets} />
            </div>
            <div className="action-grid">
              <ActionLink href="/workbench" label="Try a query in Workbench" description="Preview the cited context packet for a query." tone="primary" />
              <ActionLink href="/self-improvement" label="Review self-improvement artifacts" description="Inspect bundles, reports, proposals, gates, and staged receipts." />
              <ActionLink href="/agent-profile" label="Prepare agent" description="Review the generated project agent before sharing it." />
            </div>
          </>}
      </SectionCard>
    </div>
  </main>;
}
