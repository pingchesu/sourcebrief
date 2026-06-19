'use client';

import Link from 'next/link';
import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, SectionCard, Card, Metric, Chip, StatusChip, AttentionRow, EmptyState, Field, ReadinessBadge, type Tone } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import { fmt } from '../../lib/api';
import { freshnessLabel, isActive, isIndexFailed, isVisible, readiness } from '../../lib/lifecycle';
import type { AgentCardSummaryList, Resource, ReviewItem, RetrievalEvalQuestion, RetrievalEvalResponse, RetrievalEvalRunList, RetrievalProfilesResponse } from '../../lib/types';

function driftSeverityTone(severity?: string | null): Tone {
  const normalized = String(severity ?? '').toLowerCase();
  if (['blocker', 'critical', 'major', 'high'].includes(normalized)) return 'risk';
  if (['minor', 'medium', 'low', 'warn', 'warning'].includes(normalized)) return 'warn';
  return 'neutral';
}

// Attention-first ordering shared with /sources: failed → stale → not indexed → unreviewed → rest.
function attentionRank(resource: Resource, review?: ReviewItem): number {
  if (isIndexFailed(review?.last_index_status)) return 0;
  if (review?.freshness_status && review.freshness_status !== 'fresh') return 1;
  if (!resource.current_snapshot_id) return 2;
  if (resource.review_status !== 'approved') return 3;
  return 4;
}

type Gate = { key: string; tone: Tone; title: string; detail: string; status: string; action?: { label: string; href?: string; onClick?: () => void } };

export default function QualityPage() {
  const { settings, client, resources, reviewItems, usageItems, provider, agent, workspace, project, selectedResource, selectedResourceId, selectResource, loading, error, reload } = usePlatform();

  const signedIn = Boolean(settings.sessionToken.trim());
  const platformEvidenceUnavailable = loading || Boolean(error);

  const reviewByResource = useMemo(() => new Map(reviewItems.map((item) => [item.resource.id, item])), [reviewItems]);
  const usageByResource = useMemo(() => new Map(usageItems.map((item) => [item.resource_id, item])), [usageItems]);

  const visibleResources = useMemo(() => resources.filter(isVisible), [resources]);
  const activeResources = useMemo(() => visibleResources.filter(isActive), [visibleResources]);

  const sortedReview = useMemo(() => [...reviewItems].sort((a, b) => {
    const rankA = attentionRank(a.resource, a);
    const rankB = attentionRank(b.resource, b);
    return rankA !== rankB ? rankA - rankB : a.resource.name.localeCompare(b.resource.name);
  }), [reviewItems]);

  const counts = useMemo(() => {
    const reviewable = activeResources.filter((r) => r.retrieval_enabled);
    return {
      active: activeResources.length,
      approved: activeResources.filter((r) => r.review_status === 'approved').length,
      unreviewed: reviewable.filter((r) => r.review_status !== 'approved').length,
      stale: reviewItems.filter((item) => item.freshness_status && item.freshness_status !== 'fresh').length,
      indexFailed: visibleResources.filter((r) => isIndexFailed(reviewByResource.get(r.id)?.last_index_status)).length,
      reviewable: reviewable.length,
    };
  }, [activeResources, reviewItems, visibleResources, reviewByResource]);

  // --- Review decision form (ported from /review). ---
  const [decision, setDecision] = useState('approved');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const selectedReview = selectedResource ? reviewByResource.get(selectedResource.id) : undefined;

  useEffect(() => {
    if (!selectedResource) return;
    setDecision(selectedResource.review_status || 'approved');
    setNote(selectedResource.review_note || '');
    setSaveError(null);
    setSaved(false);
  }, [selectedResourceId, selectedResource]);

  async function saveReview(event: FormEvent) {
    event.preventDefault();
    if (!selectedResource) return;
    setSaving(true); setSaveError(null); setSaved(false);
    try {
      await client(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/review`, {
        method: 'POST',
        body: JSON.stringify({ review_status: decision, review_note: note, stale_after_days: 30 }),
      });
      setSaved(true);
      await reload();
    } catch (err) { setSaveError(String(err)); }
    finally { setSaving(false); }
  }

  // --- Drift findings (agent-card-summaries; read + dry-run audit, read-only). ---
  const [drift, setDrift] = useState<AgentCardSummaryList | null>(null);
  const [driftOpen, setDriftOpen] = useState(false);
  const [driftBusy, setDriftBusy] = useState(false);
  const [driftError, setDriftError] = useState<string | null>(null);

  async function loadDrift() {
    if (!signedIn) return;
    try {
      setDrift(await client<AgentCardSummaryList>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-card-summaries?latest_only=true`));
    } catch (err) { setDriftError(String(err)); }
  }

  async function runDriftScan() {
    setDriftBusy(true); setDriftError(null);
    try {
      setDrift(await client<AgentCardSummaryList>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-card-summaries/run?dry_run=true`, { method: 'POST' }));
      setDriftOpen(true);
    } catch (err) { setDriftError(String(err)); }
    finally { setDriftBusy(false); }
  }

  const driftFindings = useMemo(() => (drift?.summaries ?? []).filter((s) => s.status !== 'healthy'), [drift]);

  // --- Retrieval evidence (ported from /evals). ---
  const indexedResources = useMemo(() => resources.filter((r) => r.current_snapshot_id && r.retrieval_enabled && r.status === 'active'), [resources]);
  const [history, setHistory] = useState<RetrievalEvalRunList | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [profileCatalog, setProfileCatalog] = useState<RetrievalProfilesResponse | null>(null);
  const [selectedProfile, setSelectedProfile] = useState('hybrid');
  const [result, setResult] = useState<RetrievalEvalResponse | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [evalBusy, setEvalBusy] = useState(false);
  const [runOpen, setRunOpen] = useState(false);
  const [seedId, setSeedId] = useState('');
  const [questionsJson, setQuestionsJson] = useState('');
  const seedResource = indexedResources.find((r) => r.id === seedId) ?? indexedResources[0] ?? null;
  const activeProfile = profileCatalog?.profiles.find((p) => p.name === selectedProfile);
  const lastEvalRun = history?.runs[0] ?? null;

  async function loadHistory() {
    if (!signedIn) return;
    setHistoryBusy(true);
    try {
      setHistory(await client<RetrievalEvalRunList>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/retrieval-evals?limit=20`));
    } catch (err) { setEvalError(String(err)); }
    finally { setHistoryBusy(false); }
  }

  async function loadProfiles() {
    if (!signedIn) return;
    try {
      const response = await client<RetrievalProfilesResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/retrieval-profiles`);
      setProfileCatalog(response);
      setSelectedProfile(response.default);
    } catch (err) { setEvalError(String(err)); }
  }

  useEffect(() => { void loadHistory(); void loadProfiles(); void loadDrift(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [settings.workspaceId, settings.projectId, signedIn]);

  function defaultQuestions(): RetrievalEvalQuestion[] {
    if (!seedResource) return [];
    return [
      { id: 'source-responsibility', query: `What is ${seedResource.name} responsible for? Cite exact files.`, expected_resource_ids: [seedResource.id], resource_ids: [seedResource.id], min_citations: 1, top_k: 8, include_code_symbols: true },
      { id: 'source-boundaries', query: `Show ${seedResource.name}'s main entrypoints, config files, and runtime boundaries.`, expected_resource_ids: [seedResource.id], resource_ids: [seedResource.id], min_citations: 1, top_k: 10, include_code_symbols: true },
    ];
  }

  async function runEval(event?: FormEvent) {
    event?.preventDefault();
    setEvalBusy(true); setEvalError(null);
    try {
      const questions = questionsJson ? JSON.parse(questionsJson) as RetrievalEvalQuestion[] : defaultQuestions();
      const response = await client<RetrievalEvalResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/retrieval-evals`, {
        method: 'POST',
        body: JSON.stringify({ runtime: 'hermes', profile: selectedProfile, max_chars: 10000, questions }),
      });
      setResult(response);
      await loadHistory();
    } catch (err) { setEvalError(String(err)); }
    finally { setEvalBusy(false); }
  }

  async function loadRun(runId: string) {
    setEvalBusy(true); setEvalError(null);
    try {
      const response = await client<RetrievalEvalResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/retrieval-evals/${runId}`);
      setResult(response);
      setSelectedProfile(response.profile);
    } catch (err) { setEvalError(String(err)); }
    finally { setEvalBusy(false); }
  }

  // --- Quality gates, derived only from real signals. ---
  const gates = useMemo<Gate[]>(() => {
    if (!signedIn) return [];
    const list: Gate[] = [];
    // Source review
    list.push(counts.reviewable === 0
      ? { key: 'review', tone: 'neutral', title: 'Source review', detail: 'No retrieval-enabled sources to review yet.', status: 'no sources' }
      : counts.unreviewed === 0
        ? { key: 'review', tone: 'ready', title: 'Source review', detail: `All ${counts.reviewable} retrieval-enabled source(s) approved.`, status: 'approved' }
        : { key: 'review', tone: 'warn', title: 'Source review', detail: `${counts.unreviewed} retrieval-enabled source(s) not approved.`, status: `${counts.unreviewed} open` });
    // Freshness
    list.push(reviewItems.length === 0
      ? { key: 'freshness', tone: 'neutral', title: 'Freshness', detail: 'No freshness data yet.', status: 'no data' }
      : counts.stale === 0
        ? { key: 'freshness', tone: 'ready', title: 'Freshness', detail: 'All sources are fresh.', status: 'fresh' }
        : { key: 'freshness', tone: 'warn', title: 'Freshness', detail: `${counts.stale} stale source(s) may have drifted from their indexed snapshot.`, status: `${counts.stale} stale` });
    // Index health
    list.push(platformEvidenceUnavailable
      ? { key: 'index', tone: 'neutral', title: 'Index health', detail: loading ? 'Platform evidence is still loading.' : 'Platform data failed to load; index health is unknown.', status: 'unknown', action: { label: 'Reload', onClick: () => void reload() } }
      : reviewItems.length === 0 && activeResources.length === 0
        ? { key: 'index', tone: 'neutral', title: 'Index health', detail: 'No source/index evidence loaded yet.', status: 'no data', action: { label: 'Sources', href: '/sources' } }
        : counts.indexFailed === 0
          ? { key: 'index', tone: 'ready', title: 'Index health', detail: 'No failed index runs.', status: 'ok', action: { label: 'Sources', href: '/sources' } }
          : { key: 'index', tone: 'risk', title: 'Index health', detail: `${counts.indexFailed} source(s) failed to index.`, status: `${counts.indexFailed} failed`, action: { label: 'Reindex', href: '/maintenance' } });
    // Drift
    list.push(!drift
      ? { key: 'drift', tone: 'neutral', title: 'Drift audit', detail: 'Run a drift scan to evaluate source health.', status: 'not run', action: { label: 'Show findings', onClick: () => setDriftOpen(true) } }
      : driftFindings.length === 0
        ? { key: 'drift', tone: 'ready', title: 'Drift audit', detail: `${drift.summaries.length} source summary(ies), none degraded.`, status: 'healthy', action: { label: 'Show findings', onClick: () => setDriftOpen(true) } }
        : (() => {
          const tone: Tone = driftFindings.some((summary) => driftSeverityTone(summary.severity) === 'risk') ? 'risk' : 'warn';
          return { key: 'drift', tone, title: 'Drift audit', detail: `${driftFindings.length} source(s) flagged by drift audit.`, status: `${driftFindings.length} flagged`, action: { label: 'Show findings', onClick: () => setDriftOpen(true) } };
        })());
    // Retrieval eval
    list.push(!lastEvalRun
      ? { key: 'eval', tone: 'neutral', title: 'Retrieval eval', detail: 'No golden-question eval has been run for this project.', status: 'not run', action: { label: 'Run eval', onClick: () => setRunOpen(true) } }
      : lastEvalRun.status === 'passed'
        ? { key: 'eval', tone: 'ready', title: 'Retrieval eval', detail: `Last run passed (${Math.round(lastEvalRun.pass_rate * 100)}% pass rate, ${lastEvalRun.profile}).`, status: 'passed' }
        : { key: 'eval', tone: lastEvalRun.pass_rate >= 0.5 ? 'warn' : 'risk', title: 'Retrieval eval', detail: `Last run ${lastEvalRun.status} (${Math.round(lastEvalRun.pass_rate * 100)}% pass rate, ${lastEvalRun.profile}).`, status: lastEvalRun.status });
    // Provider
    list.push(provider?.status === 'ok'
      ? { key: 'provider', tone: 'ready', title: 'Embedding provider', detail: `${provider.embedding.provider}/${provider.embedding.model} healthy.`, status: 'ok', action: { label: 'Config', href: '/config' } }
      : { key: 'provider', tone: 'warn', title: 'Embedding provider', detail: provider ? `${provider.embedding.provider}/${provider.embedding.model} · ${provider.embedding.namespace}` : 'Provider not loaded.', status: provider?.status ?? 'unknown', action: { label: 'Diagnose', href: '/config' } });
    return list;
  }, [signedIn, counts, reviewItems.length, activeResources.length, drift, driftFindings.length, lastEvalRun, provider, platformEvidenceUnavailable, loading, error, reload]);

  const openGates = gates.filter((g) => g.tone === 'warn' || g.tone === 'risk');
  const unevidencedGates = gates.filter((g) => g.tone === 'neutral');
  const gateState: { tone: Tone; label: string } = !signedIn
    ? { tone: 'risk', label: 'Sign in to evaluate quality gates' }
    : openGates.some((g) => g.tone === 'risk')
      ? { tone: 'risk', label: `${openGates.length} quality gate(s) failing` }
      : openGates.length > 0
        ? { tone: 'warn', label: `${openGates.length} quality gate(s) need attention` }
        : unevidencedGates.length > 0
          ? { tone: 'warn', label: `${unevidencedGates.length} quality gate(s) missing evidence` }
          : { tone: 'ready', label: 'All quality gates passing' };

  // --- Attention queue: source-level signals, attention-first. ---
  const attention = useMemo(() => {
    const items: { key: string; tone: Tone; title: string; detail: string; meta?: string; resourceId?: string }[] = [];
    for (const summary of driftFindings) {
      const resource = resources.find((r) => r.id === summary.resource_id);
      items.push({
        key: `drift-${summary.resource_id}`,
        tone: driftSeverityTone(summary.severity) === 'risk' ? 'risk' : 'warn',
        title: resource?.name ?? 'Unknown source',
        detail: `Drift audit: ${summary.summary}`,
        meta: `${summary.severity} · ${summary.findings.length} finding(s)`,
        resourceId: resource?.id,
      });
    }
    for (const item of sortedReview) {
      const rank = attentionRank(item.resource, item);
      if (rank === 4) continue;
      const tone: Tone = rank === 0 ? 'risk' : 'warn';
      const detail = rank === 0
        ? `Index ${item.last_index_status}`
        : rank === 1
          ? (item.stale_reasons[0] ?? `${item.freshness_status}${item.freshness_age_days != null ? ` · ${item.freshness_age_days}d old` : ''}`)
          : rank === 2
            ? 'Not indexed yet'
            : `Review status ${item.resource.review_status}`;
      items.push({ key: item.resource.id, tone, title: item.resource.name, detail, meta: `${item.usage_count} uses`, resourceId: item.resource.id });
    }
    return items.slice(0, 8);
  }, [sortedReview, driftFindings, resources]);

  return <main className="page">
    <PageHeader
      eyebrow="Quality"
      title="Quality gate"
      description={workspace ? `Pre-flight quality for ${project?.name ?? 'this project'}: source review, freshness, drift, and retrieval-eval evidence before the agent serves context.` : 'Source review, freshness, drift, and retrieval-eval evidence before the agent serves context.'}
      actions={<>
        <button className="btn secondary" disabled={driftBusy || !signedIn} onClick={() => void runDriftScan()}>{driftBusy ? 'Scanning…' : 'Run drift scan'}</button>
        <button className="btn secondary" onClick={() => reload()} disabled={loading}>{loading ? 'Loading…' : 'Reload'}</button>
      </>}
    />

    {error ? <div className="notice error">Could not load platform data: {error}</div> : null}
    {provider && provider.status !== 'ok' ? <div className="notice">Embedding provider {provider.status} · {provider.embedding.provider}/{provider.embedding.model}. Retrieval quality may be degraded.</div> : null}

    <section className={`card readiness tone-${gateState.tone}`}>
      <div className="readiness-main">
        <span className="readiness-state">{gateState.tone === 'ready' ? 'Pass' : gateState.tone === 'warn' ? 'Attention' : 'Blocked'}</span>
        <span className="readiness-title">{gateState.label}</span>
        <span className="muted">{signedIn ? 'Gates are derived from live source review, freshness, drift audit, retrieval eval, and provider health.' : 'No active session.'}</span>
      </div>
    </section>

    <section className="card">
      <div className="health-strip">
        <div className="health-item"><span className="label">Active sources</span><span className="health-item-value">{counts.active}</span></div>
        <div className="health-item"><span className="label">Approved</span><span className="health-item-value"><Chip tone={counts.approved > 0 ? 'ready' : 'neutral'}>{counts.approved}</Chip></span></div>
        <div className="health-item"><span className="label">Stale</span><span className="health-item-value"><Chip tone={counts.stale > 0 ? 'warn' : 'neutral'}>{counts.stale}</Chip></span></div>
        <div className="health-item"><span className="label">Index failed</span><span className="health-item-value"><Chip tone={counts.indexFailed > 0 ? 'risk' : 'neutral'}>{counts.indexFailed}</Chip></span></div>
        <div className="health-item"><span className="label">Drift flagged</span><span className="health-item-value"><Chip tone={driftFindings.length > 0 ? 'warn' : 'neutral'}>{drift ? driftFindings.length : '—'}</Chip></span></div>
        <div className="health-item"><span className="label">Last eval</span><span className="health-item-value">{lastEvalRun ? <StatusChip value={lastEvalRun.status} /> : <Chip tone="neutral">not run</Chip>}</span></div>
      </div>
    </section>

    <SectionCard title="Quality gates" description="Each gate must clear before the agent is trusted to serve context. Neutral means no evidence yet — not a pass.">
      {gates.length === 0
        ? <EmptyState text="Sign in to evaluate quality gates." />
        : <div className="attention-list">
          {gates.map((gate) => (
            <AttentionRow
              key={gate.key}
              tone={gate.tone}
              title={gate.title}
              detail={gate.detail}
              meta={<StatusChip value={gate.status} />}
              action={gate.action ? (gate.action.href
                ? <Link className="btn secondary" href={gate.action.href}>{gate.action.label}</Link>
                : <button className="btn secondary" onClick={gate.action.onClick}>{gate.action.label}</button>) : undefined}
            />
          ))}
        </div>}
    </SectionCard>

    <SectionCard title="Attention queue" description="Sources that need action now, attention-first: failed index → stale → not indexed → unreviewed.">
      {attention.length === 0
        ? <EmptyState text={!signedIn ? 'Sign in to load the attention queue.' : platformEvidenceUnavailable ? 'Platform evidence is unavailable, so attention health is unknown. Reload before treating the queue as clear.' : 'No sources need attention. Index healthy, nothing stale or unreviewed.'} />
        : <div className="attention-list">
          {attention.map((entry) => (
            <AttentionRow
              key={entry.key}
              tone={entry.tone}
              title={entry.title}
              detail={entry.detail}
              meta={entry.meta}
              action={entry.resourceId ? <button className="btn secondary" onClick={() => void selectResource(entry.resourceId!)}>Review</button> : undefined}
            />
          ))}
        </div>}
    </SectionCard>

    <div className="grid two">
      <SectionCard title="Review queue" description="Every source feeding the agent — freshness, usage, index, and review state. Select one to record a decision.">
        {sortedReview.length === 0
          ? <EmptyState text={signedIn ? 'No review rows loaded.' : 'Sign in to load the review queue.'} />
          : <div className="table-wrap"><table>
            <thead><tr><th>Source</th><th>Readiness</th><th>Freshness</th><th>Index</th><th>Review</th><th>Uses</th><th>Reasons</th></tr></thead>
            <tbody>
              {sortedReview.map((item) => {
                const fresh = freshnessLabel(item);
                const usage = usageByResource.get(item.resource.id);
                const uses = usage ? (usage.hit_count || usage.query_count) : item.usage_count;
                return <tr key={item.resource.id} className={`clickable ${item.resource.id === selectedResourceId ? 'selected' : ''}`} onClick={() => void selectResource(item.resource.id)}>
                  <td><strong>{item.resource.name}</strong><div className="toolbar" style={{ gap: 6, marginTop: 4 }}><Chip>{item.resource.type}</Chip>{item.resource.status !== 'active' ? <StatusChip value={item.resource.status} /> : null}</div></td>
                  <td><ReadinessBadge state={readiness(item.resource, item)} lastIndexStatus={item.last_index_status} /></td>
                  <td>{fresh.label === '—' ? <span className="muted">—</span> : <span><StatusChip value={fresh.label} />{fresh.ageDays != null ? <div className="code">{fresh.ageDays}d</div> : null}</span>}</td>
                  <td>{item.last_index_status ? <StatusChip value={item.last_index_status} /> : <span className="muted">not indexed</span>}</td>
                  <td><StatusChip value={item.resource.review_status} /></td>
                  <td>{uses}</td>
                  <td>{item.stale_reasons.length ? <span className="muted">{item.stale_reasons.join(', ')}</span> : <span className="muted">none</span>}</td>
                </tr>;
              })}
            </tbody>
          </table></div>}
      </SectionCard>

      <SectionCard title="Review decision" description="Record whether the selected source is current, useful, and safe to keep enabled for agent retrieval.">
        {!selectedResource
          ? <EmptyState text="Select a source from the queue to record a review decision." />
          : <form className="grid" onSubmit={saveReview}>
            <div>
              <div className="label">Source</div>
              <strong>{selectedResource.name}</strong>
              <div className="code">{selectedResource.uri}</div>
            </div>
            <div className="grid three">
              <Metric label="Readiness" value={<ReadinessBadge state={readiness(selectedResource, selectedReview)} lastIndexStatus={selectedReview?.last_index_status} />} />
              <Metric label="Freshness" value={selectedReview && selectedReview.freshness_status ? <StatusChip value={selectedReview.freshness_status} /> : '—'} hint={selectedReview?.freshness_age_days != null ? `${selectedReview.freshness_age_days}d old` : undefined} />
              <Metric label="Uses" value={selectedReview?.usage_count ?? usageByResource.get(selectedResource.id)?.query_count ?? 0} hint={`last ${fmt(selectedReview?.last_used_at)}`} />
            </div>
            {selectedReview?.stale_reasons.length ? <div className="notice">Stale reasons: {selectedReview.stale_reasons.join(', ')}</div> : null}
            <Field label="Decision"><select className="input" value={decision} onChange={(event) => setDecision(event.target.value)}><option value="approved">approved</option><option value="needs_update">needs_update</option><option value="stale">stale</option><option value="ignored">ignored</option><option value="unreviewed">unreviewed</option></select></Field>
            <Field label="Review note"><textarea className="input" rows={4} value={note} onChange={(event) => setNote(event.target.value)} /></Field>
            <button className="btn" disabled={saving}>{saving ? 'Saving…' : 'Save review'}</button>
            {saveError ? <div className="notice error">{saveError}</div> : null}
            {saved ? <div className="notice">Review decision saved. Stale window 30 days.</div> : null}
          </form>}
      </SectionCard>
    </div>

    <SectionCard
      title="Retrieval evidence"
      description="Golden-question evals run against the real agent-context path. Last run sets the retrieval gate; load a run to inspect per-question evidence."
      action={<button className="btn secondary" onClick={() => setRunOpen((open) => !open)} disabled={!signedIn}>{runOpen ? 'Close eval runner' : 'Run new eval'}</button>}
    >
      <div className="grid four">
        <Metric label="Indexed resources" value={indexedResources.length} />
        <Metric label="Last status" value={lastEvalRun ? lastEvalRun.status : (result?.summary.status ?? 'not run')} />
        <Metric label="Last pass rate" value={lastEvalRun ? `${Math.round(lastEvalRun.pass_rate * 100)}%` : '—'} />
        <Metric label="Provider" value={provider ? `${provider.embedding.provider}/${provider.embedding.model}` : '—'} />
      </div>

      {evalError ? <div className="notice error">{evalError}</div> : null}

      {runOpen ? <div className="advanced-section" style={{ marginTop: 16 }}>
        {indexedResources.length === 0
          ? <EmptyState text="Index at least one retrieval-enabled source before running evals." />
          : <form className="grid" onSubmit={runEval}>
            <div className="grid two">
              <Field label="Seed source"><select className="input" value={seedResource?.id ?? ''} onChange={(event) => setSeedId(event.target.value)}>{indexedResources.map((r) => <option key={r.id} value={r.id}>{r.name} — {r.type}</option>)}</select></Field>
              <Field label="Evaluation style"><select className="input" value={selectedProfile} onChange={(event) => setSelectedProfile(event.target.value)}>{(profileCatalog?.profiles ?? []).map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</select></Field>
            </div>
            {activeProfile ? <div className="notice"><strong>{activeProfile.name}</strong>: {activeProfile.description}</div> : null}
            <button className="btn" disabled={evalBusy || !seedResource}>{evalBusy ? 'Running…' : `Run ${selectedProfile} evaluation`}</button>
          </form>}
      </div> : null}

      <div className="grid two" style={{ marginTop: 16 }}>
        <Card>
          <h2>Eval history</h2>
          {historyBusy ? <EmptyState text="Loading historical eval runs…" /> : !history?.runs.length ? <EmptyState text="No persisted eval runs yet." /> : <div className="table-wrap"><table><thead><tr><th>Status</th><th>Profile</th><th>Created</th><th>Pass rate</th><th>Scope</th><th></th></tr></thead><tbody>{history.runs.map((run) => <tr key={run.id} className={result?.run_id === run.id ? 'selected' : ''}><td><StatusChip value={run.status} /></td><td>{run.profile}</td><td>{new Date(run.created_at).toLocaleString()}</td><td>{Math.round(run.pass_rate * 100)}%</td><td>{run.project_wide ? 'project-wide' : `${run.resource_ids.length} resource(s)`}</td><td><button className="btn secondary" onClick={() => void loadRun(run.id)} disabled={evalBusy}>Load</button></td></tr>)}</tbody></table></div>}
        </Card>
        <Card>
          <h2>Run summary</h2>
          {!result ? <EmptyState text="No eval run selected. Load a historical run or run a new eval." /> : <div className="grid">
            <div className="grid four"><Metric label="Status" value={<StatusChip value={result.summary.status} />} /><Metric label="Profile" value={result.profile} /><Metric label="Pass rate" value={`${Math.round(result.summary.pass_rate * 100)}%`} /><Metric label="Avg latency" value={`${result.summary.avg_latency_ms}ms`} /></div>
            <div className="notice">{result.provider}/{result.model} · vector {(result.diagnostics.vector_status as string) ?? 'unknown'}.</div>
            {result.summary.failure_reasons.length ? <div className="notice error">{result.summary.failure_reasons.join('\n')}</div> : null}
          </div>}
        </Card>
      </div>

      {result ? <div style={{ marginTop: 16 }} className="table-wrap"><table><thead><tr><th>Status</th><th>Question</th><th>Citations</th><th>Symbols</th><th>Latency</th><th>Failures</th></tr></thead><tbody>{result.results.map((row) => <tr key={row.id}><td><StatusChip value={row.passed ? 'passed' : 'failed'} /></td><td>{row.id}</td><td>{row.citation_count}</td><td>{row.symbol_count}</td><td>{row.latency_ms}ms</td><td>{row.failure_reasons.join(', ') || '—'}</td></tr>)}</tbody></table></div> : null}
    </SectionCard>

    <section className="card">
      <div className="advanced-section">
        <button type="button" className="advanced-toggle" aria-expanded={driftOpen} onClick={() => setDriftOpen((open) => !open)}>
          <span>Drift findings{drift ? ` (${driftFindings.length} flagged of ${drift.summaries.length})` : ''}</span><span className="code">{driftOpen ? 'hide' : 'show'}</span>
        </button>
        {driftOpen ? <div className="grid" style={{ marginTop: 12 }}>
          <p className="muted">Read-only drift audit over source agent cards (stale runbooks, missing entrypoints, orphaned files). Scanning records only a ContextSmith audit summary — it never modifies your sources.</p>
          <div className="toolbar"><button className="btn secondary" disabled={driftBusy || !signedIn} onClick={() => void runDriftScan()}>{driftBusy ? 'Scanning…' : 'Run drift scan (dry run)'}</button></div>
          {driftError ? <div className="notice error">{driftError}</div> : null}
          {!drift
            ? <EmptyState text="No drift summaries loaded. Run a drift scan to evaluate source health." />
            : drift.summaries.length === 0
              ? <EmptyState text="No agent card summaries for this project yet." />
              : <div className="table-wrap"><table><thead><tr><th>Source</th><th>Status</th><th>Severity</th><th>Findings</th><th>Summary</th><th>Updated</th></tr></thead><tbody>{drift.summaries.map((summary) => { const resource = resources.find((r) => r.id === summary.resource_id); return <tr key={summary.id}><td><strong>{resource?.name ?? 'Unknown source'}</strong></td><td><StatusChip value={summary.status} /></td><td><StatusChip value={summary.severity} /></td><td>{summary.findings.length}</td><td className="muted">{summary.summary}</td><td className="code">{fmt(summary.created_at)}</td></tr>; })}</tbody></table></div>}
        </div> : null}
      </div>
    </section>
  </main>;
}
