'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, Metric, EmptyState, StatusChip, Field } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import { fmt, short } from '../../lib/api';
import type { GraphCompileResponse, GraphStream, GraphVersion } from '../../lib/types';

function jsonText(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

export default function GraphsPage() {
  const { settings, client, resources, signedIn, loading, reload } = usePlatform();
  const [graphs, setGraphs] = useState<GraphStream[]>([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [resourceId, setResourceId] = useState('');
  const [graphKey, setGraphKey] = useState('');
  const [title, setTitle] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [archiveArmed, setArchiveArmed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const indexedResources = useMemo(() => resources.filter((resource) => resource.current_snapshot_id && !resource.deleted_at), [resources]);
  const selected = useMemo(() => graphs.find((graph) => graph.graph_key === selectedKey) ?? graphs[0] ?? null, [graphs, selectedKey]);
  const newestDraft = selected?.versions.find((version) => version.status === 'draft') ?? null;
  const activeCurrentVersion = selected?.status !== 'archived' ? selected?.current_version_id : null;

  useEffect(() => { setArchiveArmed(false); }, [selected?.graph_key]);

  async function loadGraphs() {
    if (!settings.workspaceId || !settings.projectId || !settings.sessionToken) return;
    setError(null);
    const rows = await client<GraphStream[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graphs`);
    setGraphs(rows);
    setSelectedKey((current) => current && rows.some((row) => row.graph_key === current) ? current : rows[0]?.graph_key ?? '');
  }

  useEffect(() => { void loadGraphs().catch((err) => setError(String(err))); }, [client, settings.workspaceId, settings.projectId, settings.sessionToken]);

  async function compileGraph(event: FormEvent) {
    event.preventDefault();
    if (!resourceId) return;
    setBusy(true); setError(null);
    try {
      const response = await client<GraphCompileResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${resourceId}/graph/versions`, {
        method: 'POST',
        body: JSON.stringify({ graph_key: graphKey || null, title: title || null }),
      });
      setSelectedKey(response.graph.graph_key); setResourceId(''); setGraphKey(''); setTitle('');
      await loadGraphs(); await reload();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function action(path: string) {
    const trimmed = comment.trim();
    if (!trimmed) { setError('Enter a review comment / reason first.'); return; }
    setBusy(true); setError(null);
    try {
      const graph = await client<GraphStream>(path, { method: 'POST', body: JSON.stringify({ comment: trimmed }) });
      setComment(''); setArchiveArmed(false); setSelectedKey(graph.graph_key); await loadGraphs();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  function versionActions(version: GraphVersion) {
    if (!selected) return null;
    const base = `/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graphs/${selected.graph_key}/versions/${version.version}`;
    const isActiveCurrent = version.id === activeCurrentVersion;
    return <div className="toolbar">
      {version.status === 'draft' ? <button className="btn" disabled={busy || selected.status === 'archived' || version.validation_json?.ok === false} onClick={() => void action(`${base}/publish`)}>Publish</button> : null}
      {version.status !== 'invalidated' ? <button className="btn secondary" disabled={busy || isActiveCurrent} title={isActiveCurrent ? 'Archive the graph or publish another version before invalidating current.' : undefined} onClick={() => void action(`${base}/invalidate`)}>{isActiveCurrent ? 'Archive before invalidate' : 'Invalidate'}</button> : null}
    </div>;
  }

  return <main className="page"><PageHeader eyebrow="Graphs" title="Versioned resource graphs" description="Store graph snapshots as reviewable versions before cross-resource merge. E0 is resource-graph storage only; project and merged graphs arrive in the next graph merge stage." actions={<button className="btn secondary" disabled={busy || loading} onClick={() => void loadGraphs()}>{busy ? 'Working…' : 'Reload graphs'}</button>} />
    {error ? <div className="notice error">{error}</div> : null}
    <div className="grid three"><Metric label="Graph streams" value={graphs.length} /><Metric label="Draft versions" value={graphs.reduce((sum, graph) => sum + graph.versions.filter((version) => version.status === 'draft').length, 0)} /><Metric label="Published currents" value={graphs.filter((graph) => graph.current).length} /></div>
    <div className="grid two">
      <Card><h2>Compile graph version</h2>{!signedIn ? <EmptyState text="Sign in to compile graph versions." /> : indexedResources.length === 0 ? <EmptyState text="Index a source first. Graph versions compile from current snapshots." /> : <form className="grid" onSubmit={compileGraph}>
        <Field label="Indexed source"><select className="input" required value={resourceId} onChange={(event) => setResourceId(event.target.value)}><option value="">Choose indexed source</option>{indexedResources.map((resource) => <option key={resource.id} value={resource.id}>{resource.name}</option>)}</select></Field>
        <Field label="Graph key (optional)"><input className="input" value={graphKey} onChange={(event) => setGraphKey(event.target.value)} placeholder="derived from source name" /></Field>
        <Field label="Title (optional)"><input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Source graph" /></Field>
        <button className="btn" disabled={busy}>{busy ? 'Compiling…' : 'Compile graph version'}</button>
      </form>}</Card>
      <Card><h2>Boundary</h2><ul className="muted"><li>Resource graph storage only. No cross-source merge or equivalence inference in this stage.</li><li>Publishing requires review comments and pins the source snapshot used by the version.</li><li>Existing current-snapshot graph APIs remain compatible.</li></ul></Card>
    </div>
    <div className="grid two">
      <Card><h2>Graph streams</h2>{graphs.length === 0 ? <EmptyState text="No graph streams yet. Compile one from an indexed source." /> : <div className="table-wrap"><table><thead><tr><th>Graph</th><th>Current</th><th>Nodes</th><th>Edges</th><th>Drafts</th></tr></thead><tbody>{graphs.map((graph) => <tr key={graph.id} className="clickable" onClick={() => setSelectedKey(graph.graph_key)}><td><strong>{graph.title}</strong><div className="muted">{graph.graph_key} · <StatusChip value={graph.status} /></div></td><td>{graph.current ? <span>v{graph.current.version} · <StatusChip value={graph.current.status} /></span> : <span className="muted">none</span>}</td><td>{graph.current?.node_count ?? '—'}</td><td>{graph.current?.edge_count ?? '—'}</td><td>{graph.versions.filter((version) => version.status === 'draft').length}</td></tr>)}</tbody></table></div>}</Card>
      <Card><h2>Selected graph</h2>{!selected ? <EmptyState text="Select or compile a graph stream." /> : <div className="grid">
        <div className="section-card-head"><div><strong>{selected.title}</strong><div className="muted">{selected.graph_key} · resource graph</div></div><StatusChip value={selected.status} /></div>
        {selected.current ? <div className="notice"><strong>Current published graph v{selected.current.version}</strong><div className="muted">{short(selected.current.version_hash)} · published {fmt(selected.current.published_at)}</div>{selected.current.status_reason ? <div className="muted">Review note: {selected.current.status_reason}</div> : null}<pre className="code-block">{jsonText(selected.current.summary_json)}</pre></div> : <div className="empty">No current graph version. Compile and publish a valid draft.</div>}
        <Field label="Review comment / reason"><input className="input" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Required for publish / archive / invalidate" /></Field>
        {newestDraft ? <div className="notice"><strong>Newest draft v{newestDraft.version}</strong><div className="muted">{short(newestDraft.version_hash)} · {fmt(newestDraft.created_at)}</div>{newestDraft.validation_json?.warnings?.length ? <pre className="code-block">{jsonText(newestDraft.validation_json.warnings)}</pre> : null}<div className="grid two"><div><h3>Summary</h3><pre className="code-block">{jsonText(newestDraft.summary_json)}</pre></div><div><h3>Membership</h3><pre className="code-block">{jsonText(newestDraft.membership_json)}</pre></div></div>{versionActions(newestDraft)}</div> : null}
        <div className="notice"><strong>Archive impact</strong><div className="muted">Archiving blocks future graph compile and publish for this stream. Use it only when retiring the source graph; there is no unarchive action in this milestone.</div></div>
        <div className="toolbar"><button className="btn secondary" disabled={busy || selected.status === 'archived'} onClick={() => { if (!archiveArmed) { setArchiveArmed(true); setError('Archive impact armed. Review the warning and click Confirm archive graph to proceed.'); return; } void action(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graphs/${selected.graph_key}/archive`); }}>{archiveArmed ? 'Confirm archive graph' : 'Review archive impact'}</button></div>
        {selected.versions.length ? <div className="table-wrap"><table><thead><tr><th>Version</th><th>Status</th><th>Hash</th><th>Nodes</th><th>Edges</th><th>Lifecycle</th></tr></thead><tbody>{selected.versions.map((version) => <tr key={version.id}><td>v{version.version}</td><td><StatusChip value={version.status} /></td><td><span className="code">{short(version.version_hash)}</span></td><td>{version.node_count}</td><td>{version.edge_count}</td><td>{versionActions(version)}</td></tr>)}</tbody></table></div> : null}
      </div>}</Card>
    </div>
  </main>;
}
