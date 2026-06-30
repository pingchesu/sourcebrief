'use client';

import { useEffect, useMemo, useState } from 'react';
import { Card, Chip, EmptyState, Field, Metric, PageHeader, SectionCard, StatusChip, type Tone } from '../../components/ui';
import { fmt } from '../../lib/api';
import { usePlatform } from '../../lib/platform-context';
import type { SelfImprovementArtifact, SelfImprovementHistoryRecord, SelfImprovementOverview, SelfImprovementRun } from '../../lib/types';

function jsonText(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function kindTone(kind: string): Tone {
  if (kind === 'staged_adoption') return 'ready';
  if (kind === 'gate_result' || kind === 'proposal') return 'warn';
  if (kind === 'report') return 'risk';
  return 'neutral';
}

function artifactTitle(record: SelfImprovementHistoryRecord): string {
  return record.artifact_id || record.path;
}

function artifactState(record: SelfImprovementHistoryRecord): string {
  return record.verdict || record.decision || record.status || record.kind;
}

export default function SelfImprovementPage() {
  const { settings, signedIn, client } = usePlatform();
  const [overview, setOverview] = useState<SelfImprovementOverview | null>(null);
  const [artifact, setArtifact] = useState<SelfImprovementArtifact | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<string>('');
  const [owner, setOwner] = useState('qa');
  const [findingId, setFindingId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<SelfImprovementRun | null>(null);

  const basePath = `/workspaces/${settings.workspaceId}/projects/${settings.projectId}/self-improvement`;

  async function loadOverview() {
    if (!signedIn || !settings.workspaceId || !settings.projectId) return;
    setError(null);
    try {
      setOverview(await client<SelfImprovementOverview>(basePath));
    } catch (err) {
      setError(String(err));
    }
  }

  async function loadArtifact(artifactId: string) {
    if (!artifactId) return;
    setSelectedArtifact(artifactId);
    setError(null);
    try {
      setArtifact(await client<SelfImprovementArtifact>(`${basePath}/artifacts/${encodeURIComponent(artifactId)}`));
    } catch (err) {
      setError(String(err));
    }
  }

  async function runMvpSmoke() {
    setBusy(true); setError(null); setLastRun(null);
    try {
      const response = await client<SelfImprovementRun>(`${basePath}/mvp-smoke`, {
        method: 'POST',
        body: JSON.stringify({ owner, finding_id: findingId.trim() || null }),
      });
      setLastRun(response);
      setOverview((current) => current ? { ...current, history: response.history } : current);
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function runSleepDryRun() {
    setBusy(true); setError(null); setLastRun(null);
    try {
      const response = await client<SelfImprovementRun>(`${basePath}/sleep`, {
        method: 'POST',
        body: JSON.stringify({ min_occurrences: 2, max_artifacts: 100 }),
      });
      setLastRun(response);
      setOverview((current) => current ? { ...current, history: response.history } : current);
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  useEffect(() => { void loadOverview(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [signedIn, settings.workspaceId, settings.projectId]);

  const records = overview?.history.records ?? [];
  const metrics = overview?.history.metrics ?? {};
  const byKind = useMemo(() => records.reduce<Record<string, number>>((acc, record) => {
    acc[record.kind] = (acc[record.kind] ?? 0) + 1;
    return acc;
  }, {}), [records]);
  const latestRun = useMemo(() => records.find((record) => record.kind === 'staged_adoption') ?? records[0] ?? null, [records]);
  const blockerMajor = metrics.blocker_major_count ?? 0;

  return <main className="page">
    <PageHeader
      eyebrow="Self-improvement"
      title="Evidence-backed improvement loop"
      description="Product surface for review bundles, reviewer reports, regression proposals, validation gates, staged receipts, and sleep/replay dry-runs. Nothing here applies product changes silently."
      actions={<div className="toolbar"><button className="btn secondary" onClick={() => void loadOverview()} disabled={busy}>{busy ? 'Working…' : 'Reload'}</button></div>}
    />
    {!signedIn ? <div className="notice error">Sign in to inspect self-improvement artifacts.</div> : null}
    {error ? <div className="notice error">{error}</div> : null}

    <div className="grid three">
      <Metric label="Artifacts" value={metrics.record_count ?? records.length} hint="Bundle/report/proposal/gate/stage records" />
      <Metric label="Accepted gates" value={metrics.gate_accept_count ?? 0} hint="Accepted or new-best validation results" />
      <Metric label="Blocker/major findings" value={blockerMajor} hint={blockerMajor ? 'Needs review before adoption' : 'No blocking findings in scanned artifacts'} />
    </div>

    <div className="grid two">
      <SectionCard title="Operating boundary" description="The UI runs artifact-producing workflows only; staged patches still require a separate explicit developer/PR action.">
        <div className="notice"><strong>No silent mutation:</strong> {overview?.no_silent_mutation ? 'enforced by product contract' : 'unknown'}</div>
        <h3>Shipped surfaces</h3>
        <div className="toolbar">{(overview?.shipped_surfaces ?? []).map((item) => <Chip key={item}>{item}</Chip>)}</div>
        <h3>Safe next actions</h3>
        <ul className="muted">{(overview?.next_safe_actions ?? []).map((item) => <li key={item}>{item}</li>)}</ul>
        <div className="muted">Artifact root: <code>{overview?.root ?? 'not loaded'}</code></div>
      </SectionCard>

      <SectionCard title="Run controlled proof paths" description="MVP smoke creates a full artifact chain. Sleep/replay is dry-run only and mines bounded proposal artifacts.">
        <div className="grid two">
          <Field label="Owner"><input className="input" value={owner} onChange={(event) => setOwner(event.target.value)} placeholder="qa" /></Field>
          <Field label="Finding id (optional)"><input className="input" value={findingId} onChange={(event) => setFindingId(event.target.value)} placeholder="default first candidate" /></Field>
        </div>
        <div className="toolbar">
          <button className="btn" disabled={busy || !signedIn} onClick={() => void runMvpSmoke()}>{busy ? 'Running…' : 'Run MVP smoke'}</button>
          <button className="btn secondary" disabled={busy || !signedIn} onClick={() => void runSleepDryRun()}>Run sleep dry-run</button>
        </div>
        {lastRun ? <div className="notice"><strong>Last run: {lastRun.status}</strong><div className="muted">{lastRun.out_dir}</div><pre className="code-block">{jsonText(lastRun.summary)}</pre></div> : null}
      </SectionCard>
    </div>

    <div className="grid two">
      <SectionCard title="Review history" description="Redacted artifact inventory and provenance. Select a record to inspect the redacted payload.">
        {records.length === 0 ? <EmptyState text="No self-improvement artifacts yet. Run MVP smoke to generate the first proof chain." /> : <div className="table-wrap"><table className="table"><thead><tr><th>Artifact</th><th>Kind</th><th>Status</th><th>Findings</th><th>Created</th><th /></tr></thead><tbody>{records.map((record) => <tr key={`${record.kind}:${record.artifact_id}:${record.path}`} className={selectedArtifact === record.artifact_id ? 'selected' : ''}><td><strong>{artifactTitle(record)}</strong><div className="muted">{record.path}</div></td><td><Chip tone={kindTone(record.kind)}>{record.kind}</Chip></td><td><StatusChip value={artifactState(record)} /></td><td>{record.finding_count}{record.blocker_major_count ? <span className="muted"> · {record.blocker_major_count} major+</span> : null}</td><td>{fmt(record.created_at)}</td><td><button className="btn secondary" onClick={() => void loadArtifact(record.artifact_id)}>Inspect</button></td></tr>)}</tbody></table></div>}
      </SectionCard>

      <SectionCard title="Artifact detail" description="Payloads are redacted through the same self-improvement security path used by CLI history.">
        {artifact ? <>
          <div className="toolbar"><Chip tone={kindTone(artifact.record.kind)}>{artifact.record.kind}</Chip><StatusChip value={artifactState(artifact.record)} /></div>
          <h3>{artifact.record.artifact_id}</h3>
          <div className="muted">{artifact.record.path}</div>
          <pre className="code-block">{jsonText(artifact.payload)}</pre>
        </> : latestRun ? <EmptyState text="Select an artifact from review history to inspect it." /> : <EmptyState text="No artifact selected." />}
      </SectionCard>
    </div>

    <SectionCard title="Artifact mix" description="Quick inventory by artifact kind.">
      <div className="grid three">{Object.entries(byKind).length ? Object.entries(byKind).map(([kind, count]) => <Metric key={kind} label={kind} value={count} />) : <Card><EmptyState text="No artifacts yet." /></Card>}</div>
    </SectionCard>
  </main>;
}
