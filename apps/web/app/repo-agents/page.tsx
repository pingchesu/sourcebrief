'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, Metric, EmptyState, StatusChip, Field } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import { fmt, short } from '../../lib/api';
import type { RepoAgent, RepoAgentRefreshResponse, RepoAgentVersion } from '../../lib/types';

function jsonText(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function warnings(version: RepoAgentVersion | null) {
  return version?.validation_json?.warnings ?? [];
}

export default function RepoAgentsPage() {
  const { settings, client, resources, signedIn, loading, reload } = usePlatform();
  const [agents, setAgents] = useState<RepoAgent[]>([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [resourceId, setResourceId] = useState('');
  const [packKey, setPackKey] = useState('default');
  const [agentKey, setAgentKey] = useState('');
  const [title, setTitle] = useState('');
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const gitResources = useMemo(() => resources.filter((resource) => resource.type === 'git' && !resource.deleted_at), [resources]);
  const selected = useMemo(() => agents.find((agent) => agent.agent_key === selectedKey) ?? agents[0] ?? null, [agents, selectedKey]);
  const drafts = selected?.versions.filter((version) => version.status === 'draft') ?? [];
  const newestDraft = drafts[0] ?? null;
  const failed = selected?.versions.filter((version) => version.status === 'failed') ?? [];
  const activeCurrentVersion = selected?.status !== 'archived' ? selected?.current_version_id : null;

  async function loadAgents() {
    if (!settings.workspaceId || !settings.projectId || !settings.sessionToken) return;
    setError(null);
    const rows = await client<RepoAgent[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents`);
    setAgents(rows);
    setSelectedKey((current) => current && rows.some((row) => row.agent_key === current) ? current : rows[0]?.agent_key ?? '');
  }

  useEffect(() => { void loadAgents().catch((err) => setError(String(err))); }, [client, settings.workspaceId, settings.projectId, settings.sessionToken]);

  async function createAgent(event: FormEvent) {
    event.preventDefault();
    if (!resourceId) return;
    setBusy(true); setError(null);
    try {
      const created = await client<RepoAgent>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${resourceId}/repo-agent`, {
        method: 'POST',
        body: JSON.stringify({ agent_key: agentKey || null, pack_key: packKey, title: title || null }),
      });
      setSelectedKey(created.agent_key); setAgentKey(''); setTitle(''); setResourceId('');
      await loadAgents(); await reload();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function refreshAgent(agent: RepoAgent) {
    setBusy(true); setError(null);
    try {
      const response = await client<RepoAgentRefreshResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${agent.agent_key}/refresh`, { method: 'POST' });
      await loadAgents(); setSelectedKey(agent.agent_key);
      if (response.status === 'failed') setError('Refresh produced a failed draft. Open validation findings before publishing.');
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function action(path: string) {
    if (!selected) return;
    const trimmed = comment.trim();
    if (!trimmed) { setError('Enter a review comment / reason first.'); return; }
    setBusy(true); setError(null);
    try {
      await client<RepoAgent>(path, { method: 'POST', body: JSON.stringify({ comment: trimmed }) });
      setComment(''); await loadAgents();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  function versionActionButtons(version: RepoAgentVersion) {
    if (!selected) return null;
    const base = `/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selected.agent_key}/versions/${version.version}`;
    const isActiveCurrent = version.id === activeCurrentVersion;
    return <div className="toolbar">
      {['published', 'superseded'].includes(version.status) && selected.status !== 'archived' ? <button className="btn secondary" disabled={busy} onClick={() => void action(`${base}/rollback-draft`)}>Rollback draft</button> : null}
      {version.status !== 'invalidated' && !version.scrubbed_at ? <button className="btn secondary" disabled={busy || isActiveCurrent} title={isActiveCurrent ? 'Archive the Repo Agent or publish another version before invalidating current.' : undefined} onClick={() => void action(`${base}/invalidate`)}>{isActiveCurrent ? 'Archive before invalidate' : 'Invalidate'}</button> : null}
      {['invalidated', 'failed'].includes(version.status) && selected.status === 'archived' ? <button className="btn secondary" disabled={busy || Boolean(version.scrubbed_at)} onClick={() => void action(`${base}/scrub`)}>Scrub</button> : null}
    </div>;
  }

  return <main className="page"><PageHeader eyebrow="Repo Agents" title="Repository runtime profiles" description="Managed, read-only repo-agent views over Git sources. Refresh creates drafts; publish is always manual and review-gated." actions={<button className="btn secondary" disabled={busy || loading} onClick={() => void loadAgents()}>{busy ? 'Working…' : 'Reload agents'}</button>} />
    {error ? <div className="notice error">{error}</div> : null}
    <div className="grid three"><Metric label="Repo Agents" value={agents.length} /><Metric label="Pending drafts" value={agents.reduce((sum, agent) => sum + agent.versions.filter((version) => version.status === 'draft').length, 0)} /><Metric label="Pack-only capable" value={agents.filter((agent) => agent.current && !agent.current.skill_export_id).length} /></div>
    <div className="grid two">
      <Card><h2>Create Repo Agent</h2>{!signedIn ? <EmptyState text="Sign in to create Repo Agents." /> : gitResources.length === 0 ? <EmptyState text="Connect and index a Git source first. Repo Agent V0 is scoped to Git resources." /> : <form className="grid" onSubmit={createAgent}>
        <Field label="Git source"><select className="input" value={resourceId} onChange={(event) => setResourceId(event.target.value)} required><option value="">Choose Git source</option>{gitResources.map((resource) => <option key={resource.id} value={resource.id}>{resource.name}</option>)}</select></Field>
        <Field label="Context Pack stream"><input className="input" value={packKey} onChange={(event) => setPackKey(event.target.value)} placeholder="default" /></Field>
        <Field label="Agent key (optional)"><input className="input" value={agentKey} onChange={(event) => setAgentKey(event.target.value)} placeholder="derived from source name" /></Field>
        <Field label="Title (optional)"><input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Source Repo Agent" /></Field>
        <button className="btn" disabled={busy}>{busy ? 'Creating…' : 'Create Repo Agent'}</button>
      </form>}</Card>
      <Card><h2>Operating boundary</h2><ul className="muted"><li>Refresh compiles from the latest indexed Git snapshot; it does not clone by itself.</li><li>Publish, rollback, archive, invalidate, and scrub require review-gated comments.</li><li>Repo Agent V0 is read-only context. No production mutation permission is included.</li></ul></Card>
    </div>
    <div className="grid two">
      <Card><h2>Agents</h2>{agents.length === 0 ? <EmptyState text="No Repo Agents yet. Create one from a Git source." /> : <div className="table-wrap"><table><thead><tr><th>Agent</th><th>Pack</th><th>Current</th><th>Drafts</th><th>Action</th></tr></thead><tbody>{agents.map((agent) => <tr key={agent.id} className="clickable" onClick={() => setSelectedKey(agent.agent_key)}><td><strong>{agent.title}</strong><div className="muted">{agent.agent_key} · <StatusChip value={agent.status} /></div></td><td>{agent.pack_key}</td><td>{agent.current ? <span>v{agent.current.version} · <StatusChip value={agent.current.status} /></span> : <span className="muted">none</span>}</td><td>{agent.versions.filter((version) => version.status === 'draft').length}</td><td><button className="btn secondary" disabled={busy || agent.status === 'archived'} onClick={(event) => { event.stopPropagation(); void refreshAgent(agent); }}>Refresh draft</button></td></tr>)}</tbody></table></div>}</Card>
      <Card><h2>Selected Repo Agent</h2>{!selected ? <EmptyState text="Select or create a Repo Agent." /> : <div className="grid">
        <div className="section-card-head"><div><strong>{selected.title}</strong><div className="muted">{selected.agent_key} · pack {selected.pack_key}</div></div><StatusChip value={selected.status} /></div>
        {selected.current ? <div className="notice"><strong>Current published version v{selected.current.version}</strong><div className="muted">{short(selected.current.version_hash)} · published {fmt(selected.current.published_at)}</div><pre className="code-block">{jsonText(selected.current.install_json)}</pre></div> : <div className="empty">No current published runtime version. Refresh and publish a valid draft.</div>}
        <Field label="Review comment / reason"><input className="input" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Required for publish / rollback / archive / invalidate / scrub" /></Field>
        {newestDraft ? <div className="notice"><strong>Newest draft v{newestDraft.version}</strong><div className="muted">{short(newestDraft.version_hash)} · {fmt(newestDraft.created_at)}</div>{warnings(newestDraft).length ? <div className="notice">Warnings: <pre className="code-block">{jsonText(warnings(newestDraft))}</pre></div> : null}<div className="grid two"><div><h3>Draft summary</h3><pre className="code-block">{jsonText(newestDraft.summary_json)}</pre></div><div><h3>Draft diff</h3><pre className="code-block">{jsonText(newestDraft.diff_json)}</pre></div></div><h3>Install preview</h3><pre className="code-block">{jsonText(newestDraft.install_json)}</pre>{newestDraft.validation_json?.ok === false ? <pre className="code-block">{jsonText(newestDraft.validation_json)}</pre> : null}<button className="btn" disabled={busy || newestDraft.validation_json?.ok === false || selected.status === 'archived'} onClick={() => void action(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selected.agent_key}/versions/${newestDraft.version}/publish`)}>Publish newest draft</button></div> : null}
        {failed.length ? <div className="notice error"><strong>Failed drafts</strong><pre className="code-block">{jsonText(failed[0].validation_json)}</pre></div> : null}
        <div className="toolbar"><button className="btn secondary" disabled={busy || selected.status === 'archived'} onClick={() => void action(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selected.agent_key}/archive`)}>Archive</button></div>
        {selected.versions.length ? <div className="table-wrap"><table><thead><tr><th>Version</th><th>Status</th><th>Hash</th><th>Pack</th><th>Skill</th><th>Lifecycle</th></tr></thead><tbody>{selected.versions.map((version) => <tr key={version.id}><td>v{version.version}</td><td><StatusChip value={version.status} /></td><td><span className="code">{short(version.version_hash)}</span></td><td>{version.context_pack_version_id ? short(version.context_pack_version_id) : '—'}</td><td>{version.skill_export_id ? short(version.skill_export_id) : 'pack-only'}</td><td>{versionActionButtons(version)}</td></tr>)}</tbody></table></div> : null}
      </div>}</Card>
    </div>
  </main>;
}
