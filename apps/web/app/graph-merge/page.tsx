'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, SectionCard, Metric, EmptyState, StatusChip, Field } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import { fmt, short } from '../../lib/api';
import type { GraphStream, GraphMerge, GraphMergeData, GraphMergePath } from '../../lib/types';

function text(value: unknown) { return typeof value === 'string' ? value : ''; }
function num(value: unknown) { return typeof value === 'number' ? value : 0; }
function reviewHash(value: unknown) {
  const raw = text(value);
  if (raw.startsWith('sha256:')) return `sha256:${raw.slice(7, 19)}`;
  return short(raw);
}

export default function GraphMergePage() {
  const { settings, client, signedIn } = usePlatform();
  const [graphs, setGraphs] = useState<GraphStream[]>([]);
  const [merges, setMerges] = useState<GraphMerge[]>([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [selectedInputs, setSelectedInputs] = useState<string[]>([]);
  const [title, setTitle] = useState('Project knowledge merge');
  const [strategy, setStrategy] = useState('union');
  const [comment, setComment] = useState('');
  const [allowUnresolved, setAllowUnresolved] = useState(false);
  const [nodes, setNodes] = useState<GraphMergeData | null>(null);
  const [inputs, setInputs] = useState<GraphMergeData | null>(null);
  const [candidates, setCandidates] = useState<GraphMergeData | null>(null);
  const [candidateReason, setCandidateReason] = useState('');
  const [nodeSearch, setNodeSearch] = useState('');
  const [pathFrom, setPathFrom] = useState('');
  const [pathTo, setPathTo] = useState('');
  const [pathResult, setPathResult] = useState<GraphMergePath | null>(null);
  const [archiveArmed, setArchiveArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const publishedGraphs = useMemo(() => graphs.filter((graph) => graph.current && graph.status !== 'archived'), [graphs]);
  const selected = useMemo(() => merges.find((merge) => merge.merge_key === selectedKey) ?? merges[0] ?? null, [merges, selectedKey]);
  const latest = selected?.versions[0] ?? null;
  const reviewVersion = latest?.status === 'draft' ? latest.version : selected?.current?.version ?? latest?.version ?? null;

  async function load() {
    if (!settings.workspaceId || !settings.projectId || !settings.sessionToken) return;
    setError(null);
    const [graphRows, mergeRows] = await Promise.all([
      client<GraphStream[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graphs`),
      client<GraphMerge[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graph-merges`),
    ]);
    setGraphs(graphRows);
    setMerges(mergeRows);
    setSelectedKey((current) => current && mergeRows.some((row) => row.merge_key === current) ? current : mergeRows[0]?.merge_key ?? '');
  }

  useEffect(() => { void load().catch((err) => setError(String(err))); }, [client, settings.workspaceId, settings.projectId, settings.sessionToken]);
  useEffect(() => { setArchiveArmed(false); setPathResult(null); }, [selected?.merge_key]);

  async function compile(event: FormEvent) {
    event.preventDefault();
    if (selectedInputs.length < 2) return;
    setBusy(true); setError(null);
    try {
      const chosen = publishedGraphs.filter((graph) => selectedInputs.includes(graph.graph_key) && graph.current);
      const merge = await client<GraphMerge>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graph-merges`, {
        method: 'POST',
        body: JSON.stringify({ title, strategy, inputs: chosen.map((graph) => ({ graph_key: graph.graph_key, version: graph.current?.version })) }),
      });
      setSelectedKey(merge.merge_key); await load();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function lifecycle(path: string, body: Record<string, unknown>) {
    const trimmed = comment.trim();
    if (!trimmed) { setError('Enter a review comment before lifecycle changes.'); return; }
    setBusy(true); setError(null);
    try {
      const merge = await client<GraphMerge>(path, { method: 'POST', body: JSON.stringify({ ...body, comment: trimmed }) });
      setSelectedKey(merge.merge_key); setComment(''); setArchiveArmed(false); await load();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function loadData(kind: 'nodes' | 'candidates' | 'inputs') {
    if (!selected || !reviewVersion) return;
    const data = await client<GraphMergeData>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graph-merges/${selected.merge_key}/versions/${reviewVersion}/data?kind=${kind}&limit=100`);
    if (kind === 'nodes') setNodes(data);
    else if (kind === 'inputs') setInputs(data);
    else setCandidates(data);
  }

  async function reviewCandidate(candidateKey: string, status: 'accepted' | 'rejected') {
    if (!selected || !reviewVersion) return;
    const reason = candidateReason.trim();
    if (!reason) { setError('Enter a candidate review reason before accepting or rejecting.'); return; }
    setBusy(true); setError(null);
    try {
      await client<GraphMerge>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graph-merges/${selected.merge_key}/versions/${reviewVersion}/candidates/${candidateKey}/review`, {
        method: 'POST',
        body: JSON.stringify({ status, reason }),
      });
      await loadData('candidates'); await load();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function queryPath(event: FormEvent) {
    event.preventDefault();
    if (!selected || !reviewVersion) return;
    setPathResult(await client<GraphMergePath>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graph-merges/${selected.merge_key}/versions/${reviewVersion}/path?from_node_key=${encodeURIComponent(pathFrom)}&to_node_key=${encodeURIComponent(pathTo)}&max_depth=4`));
  }

  if (!signedIn) return <main className="page"><PageHeader eyebrow="Cross-source context" title="Graph merge" description="Sign in to compile and review graph merges." /></main>;

  const filteredNodes = (nodes?.items ?? []).filter((node) => {
    const haystack = `${text(node.label)} ${text(node.path)} ${text(node.node_type)} ${text(node.key)}`.toLowerCase();
    return !nodeSearch.trim() || haystack.includes(nodeSearch.trim().toLowerCase());
  });

  return <main className="page">
    <PageHeader eyebrow="Cross-source context" title="Graph merge" description="Merge published resource graphs with reviewable provenance. Union keeps sources distinct; Overlay is a layered view, not unreviewed semantic collapse." actions={<button className="btn secondary" disabled={busy} onClick={() => void load()}>{busy ? 'Working…' : 'Reload'}</button>} />
    {error ? <div className="notice error">{error}</div> : null}
    <div className="grid three"><Metric label="Published resource graphs" value={publishedGraphs.length} /><Metric label="Merge streams" value={merges.length} /><Metric label="Open candidates" value={merges.reduce((sum, merge) => sum + (merge.versions[0]?.unresolved_candidate_count ?? 0), 0)} /></div>
    <div className="grid two">
      <SectionCard title="Compile merge draft" description="Select two or more current resource graph versions. E1 rejects multi-version same-resource merges.">
        <form onSubmit={compile} className="stack">
          <Field label="Merge title"><input value={title} onChange={(event) => setTitle(event.target.value)} /></Field>
          <Field label="Strategy"><select value={strategy} onChange={(event) => setStrategy(event.target.value)}><option value="union">Union — keep every source node distinct</option><option value="overlay">Overlay — layered same-path view; no auto-equivalence</option></select></Field>
          <Field label="Published source graphs"><div className="stack compact">{publishedGraphs.map((graph) => <label key={graph.graph_key} className="checkline"><input type="checkbox" checked={selectedInputs.includes(graph.graph_key)} onChange={(event) => setSelectedInputs((prev) => event.target.checked ? [...prev, graph.graph_key] : prev.filter((key) => key !== graph.graph_key))} /> <span><strong>{graph.title}</strong><span className="muted"> · {graph.graph_key} · v{graph.current?.version}</span></span></label>)}</div></Field>
          <button className="btn primary" disabled={busy || selectedInputs.length < 2}>Compile draft</button>
        </form>
      </SectionCard>
      <SectionCard title="Merge streams">
        {merges.length ? <div className="stack compact">{merges.map((merge) => <button key={merge.merge_key} className={`list-row ${selected?.merge_key === merge.merge_key ? 'active' : ''}`} onClick={() => setSelectedKey(merge.merge_key)}><span><strong>{merge.title}</strong><span className="muted">{merge.merge_key}</span></span><StatusChip value={merge.current ? `current v${merge.current.version}` : merge.status} /></button>)}</div> : <EmptyState text="No graph merge yet. Select at least two published graphs and compile a draft." />}
      </SectionCard>
    </div>
    {selected ? <div className="grid two">
      <SectionCard title="Selected merge" action={<StatusChip value={selected.status} />}>
        <div className="metrics"><Metric label="Current" value={selected.current ? `v${selected.current.version}` : '—'} /><Metric label="Latest" value={latest ? `v${latest.version}` : '—'} /><Metric label="Open candidates" value={String(latest?.unresolved_candidate_count ?? 0)} /></div>
        {latest ? <div className="notice"><strong>Latest {latest.status} v{latest.version}</strong><div className="muted">{latest.merge_strategy} · {latest.node_count} nodes · {latest.edge_count} edges · {latest.candidate_count} candidates · {short(latest.version_hash)}</div>{latest.status_reason ? <p>{latest.status_reason}</p> : null}<div className="muted">Created {fmt(latest.created_at)}</div></div> : null}
        <Field label="Review comment"><textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} placeholder="Why is this merge ready or being retired?" /></Field>
        <label className="checkline"><input type="checkbox" checked={allowUnresolved} onChange={(event) => setAllowUnresolved(event.target.checked)} /> <span>Override unresolved/truncated candidates — comment must include “acknowledge unresolved”</span></label>
        <div className="toolbar"><button className="btn primary" disabled={!latest || latest.status !== 'draft' || busy} onClick={() => void lifecycle(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graph-merges/${selected.merge_key}/versions/${latest?.version}/publish`, { allow_unresolved_candidates: allowUnresolved })}>Publish draft</button><button className="btn secondary" disabled={!latest || latest.status === 'invalidated' || busy} onClick={() => void lifecycle(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graph-merges/${selected.merge_key}/versions/${latest?.version}/invalidate`, {})}>Invalidate latest</button></div>
        <div className="notice"><strong>Archive impact</strong><div className="muted">Archive retires this merge stream. Retained merge provenance still blocks hard purge of input resources until a future scrub/delete lifecycle.</div></div>
        <button className="btn secondary" disabled={busy || selected.status === 'archived'} onClick={() => archiveArmed ? void lifecycle(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/graph-merges/${selected.merge_key}/archive`, {}) : setArchiveArmed(true)}>{archiveArmed ? 'Confirm archive merge' : 'Archive merge'}</button>
      </SectionCard>
      <SectionCard title="Review data" action={<div className="toolbar"><button className="btn secondary" onClick={() => void loadData('inputs')}>Load inputs</button><button className="btn secondary" onClick={() => void loadData('nodes')}>Load nodes</button><button className="btn secondary" onClick={() => void loadData('candidates')}>Load candidates</button></div>}>
        {inputs?.items?.length ? <div className="stack compact"><strong>Input provenance</strong>{inputs.items.map((input) => <div key={`${text(input.graph_key)}-${text(input.graph_version)}`} className="notice"><strong>{text(input.resource_name)} · {text(input.graph_title)}</strong><div className="muted">{text(input.graph_key)} v{String(input.graph_version)} · {text(input.graph_version_status)} · {reviewHash(input.version_hash)}</div></div>)}</div> : <EmptyState text="Load inputs to review source graph/resource/version provenance before publish." />}
        <Field label="Candidate review reason"><input value={candidateReason} onChange={(event) => setCandidateReason(event.target.value)} /></Field>
        {candidates?.items?.length ? <div className="stack compact">{candidates.items.slice(0, 8).map((candidate) => <div key={text(candidate.candidate_key)} className="notice"><strong>{text(candidate.candidate_type)} · {Math.round(num(candidate.confidence) * 100)}%</strong><div className="muted">{text((candidate.left as Record<string, unknown>)?.label)} ↔ {text((candidate.right as Record<string, unknown>)?.label)} · {text(candidate.status)}</div><div className="toolbar"><button className="btn secondary" disabled={busy || !candidateReason.trim() || text(candidate.status) !== 'open'} onClick={() => void reviewCandidate(text(candidate.candidate_key), 'accepted')}>Accept</button><button className="btn secondary" disabled={busy || !candidateReason.trim() || text(candidate.status) !== 'open'} onClick={() => void reviewCandidate(text(candidate.candidate_key), 'rejected')}>Reject</button></div></div>)}</div> : <EmptyState text="Load candidates. Candidate review stays separate from materialized merge structure." />}
        {nodes?.items?.length ? <div className="stack compact"><Field label="Search nodes"><input value={nodeSearch} onChange={(event) => setNodeSearch(event.target.value)} placeholder="label, path, type, or source" /></Field><strong>Path node picker</strong>{filteredNodes.slice(0, 30).map((node) => <button key={text(node.key)} className="list-row" onClick={() => !pathFrom ? setPathFrom(text(node.key)) : setPathTo(text(node.key))}><span>{text(node.label)}<span className="muted">{text(node.path)} · {text(node.node_type)} · {text(node.key)}</span></span></button>)}</div> : null}
      </SectionCard>
    </div> : null}
    {selected && reviewVersion ? <SectionCard title="Path query" description="Select nodes by human label/path above; technical merge keys stay visible only as secondary evidence.">
      <form onSubmit={queryPath} className="grid three"><Field label="From node"><input value={pathFrom} onChange={(event) => setPathFrom(event.target.value)} placeholder="Pick from node list" /></Field><Field label="To node"><input value={pathTo} onChange={(event) => setPathTo(event.target.value)} placeholder="Pick from node list" /></Field><div className="form-actions"><button className="btn primary">Find path</button></div></form>
      {pathResult ? <div className="notice"><strong>{pathResult.found ? 'Path found' : 'No path found'}</strong><div className="muted">{pathResult.nodes.length} nodes · {pathResult.edges.length} edges</div>{pathResult.nodes.length ? <ol>{pathResult.nodes.map((node, index) => <li key={`${text(node.key)}-${index}`}><strong>{text(node.label)}</strong><span className="muted"> · {text(node.key)}</span></li>)}</ol> : null}</div> : null}
    </SectionCard> : null}
  </main>;
}
