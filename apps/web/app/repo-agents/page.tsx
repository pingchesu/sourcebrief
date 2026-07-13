'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, Metric, EmptyState, StatusChip, Field } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import { fmt, short } from '../../lib/api';
import type { RepoAgent, RepoAgentBundle, RepoAgentRefreshResponse, RepoAgentVersion } from '../../lib/types';

function jsonText(value: unknown) {
  function publicMetadata(item: unknown): unknown {
    if (Array.isArray(item)) return item.map(publicMetadata);
    if (item && typeof item === 'object') {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .filter(([key]) => key !== 'id' && !key.endsWith('_id'))
          .map(([key, nested]) => [key, publicMetadata(nested)]),
      );
    }
    return item;
  }
  return JSON.stringify(publicMetadata(value ?? {}), null, 2);
}

function warnings(version: RepoAgentVersion | null) {
  return version?.validation_json?.warnings ?? [];
}

const RUNTIME_STEPS = [
  ['Create + draft', 'Choose a Git source. SourceBrief creates a Repo Agent and immediately generates a draft from the latest index.'],
  ['Review draft', 'Read the generated summary/diff/install metadata. If it describes the repo correctly, add a review comment.'],
  ['Publish', 'Publish makes that draft the current runtime contract for this repo agent. It does not deploy code or mutate the repo.'],
  ['Install/validate later', 'Only when an approved Agent Pack exists do you copy the thin adapter and run doctor/smoke queries.'],
];

function quoteShellArg(value: string) {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function workspaceProjectHint(workspaceName: string | null | undefined, projectName: string | null | undefined) {
  const workspaceFlag = workspaceName ? `--workspace ${quoteShellArg(workspaceName)}` : "--workspace '<workspace>'";
  const projectFlag = projectName ? `--project ${quoteShellArg(projectName)}` : "--project '<project>'";
  return `${workspaceFlag} ${projectFlag}`;
}

function hasApprovedAgentPack(version: RepoAgentVersion | null | undefined) {
  return Boolean(version?.skill_export_id);
}

export default function RepoAgentsPage() {
  const { settings, client, resources, workspace, project, signedIn, loading, reload } = usePlatform();
  const [agents, setAgents] = useState<RepoAgent[]>([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [resourceId, setResourceId] = useState('');
  const [packKey, setPackKey] = useState('default');
  const [agentKey, setAgentKey] = useState('');
  const [title, setTitle] = useState('');
  const [comment, setComment] = useState('');
  const [bundle, setBundle] = useState<RepoAgentBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const gitResources = useMemo(() => resources.filter((resource) => resource.type === 'git' && !resource.deleted_at), [resources]);
  const selected = useMemo(() => agents.find((agent) => agent.agent_key === selectedKey) ?? agents[0] ?? null, [agents, selectedKey]);
  const drafts = selected?.versions.filter((version) => version.status === 'draft') ?? [];
  const newestDraft = drafts[0] ?? null;
  const failed = selected?.versions.filter((version) => version.status === 'failed') ?? [];
  const previewVersion = newestDraft ?? selected?.current ?? null;
  const activeCurrentVersion = selected?.status !== 'archived' ? selected?.current_version_id : null;
  const selectedCurrentHasPackage = hasApprovedAgentPack(selected?.current);
  const doctorCommand = `sourcebrief agent-pack doctor --package ./sourcebrief-skill\nsourcebrief agent-pack doctor --package ./sourcebrief-skill ${workspaceProjectHint(workspace?.name, project?.name)} --query "What does this repo agent cover?"`;

  async function loadAgents() {
    if (!settings.workspaceId || !settings.projectId || !settings.sessionToken) return;
    setError(null);
    const rows = await client<RepoAgent[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents`);
    setAgents(rows);
    setSelectedKey((current) => current && rows.some((row) => row.agent_key === current) ? current : rows[0]?.agent_key ?? '');
  }

  useEffect(() => { void loadAgents().catch((err) => setError(String(err))); }, [client, settings.workspaceId, settings.projectId, settings.sessionToken]);
  useEffect(() => {
    setBundle(null);
    if (!selected || !previewVersion || !settings.workspaceId || !settings.projectId || !settings.sessionToken) return;
    void client<RepoAgentBundle>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selected.agent_key}/versions/${previewVersion.version}/bundle`)
      .then(setBundle)
      .catch((err) => setError(String(err)));
  }, [client, selected?.agent_key, previewVersion?.version, settings.workspaceId, settings.projectId, settings.sessionToken]);

  async function createAgent(event: FormEvent) {
    event.preventDefault();
    if (!resourceId) return;
    setBusy(true); setError(null);
    try {
      const created = await client<RepoAgent>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${resourceId}/repo-agent`, {
        method: 'POST',
        body: JSON.stringify({ agent_key: agentKey || null, pack_key: packKey, title: title || null }),
      });
      await client<RepoAgentRefreshResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${created.agent_key}/refresh`, { method: 'POST' });
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

  async function deleteAgent() {
    if (!selected) return;
    const trimmed = comment.trim();
    if (!trimmed) { setError('Enter a review comment / reason before deleting.'); return; }
    setBusy(true); setError(null);
    try {
      await client<Record<string, unknown>>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selected.agent_key}/delete`, { method: 'POST', body: JSON.stringify({ comment: trimmed }) });
      setComment(''); setSelectedKey(''); setBundle(null); await loadAgents();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  function downloadBundle() {
    if (!bundle) return;
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${bundle.agent_key}-v${bundle.version}-repo-agent.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
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

  return <main className="page"><PageHeader eyebrow="Repo Agents" title="Publish Agents & Agent Packs" description="Repo Agent is a packaging/publishing workflow for a source that is already indexed. Create makes a runtime contract draft; publish approves that contract for future agent/runtime use." actions={<button className="btn secondary" disabled={busy || loading} onClick={() => void loadAgents()}>{busy ? 'Working…' : 'Reload agents'}</button>} />
    {error ? <div className="notice error">{error}</div> : null}
    <div className="grid three"><Metric label="Repo Agents" value={agents.length} /><Metric label="Pending drafts" value={agents.reduce((sum, agent) => sum + agent.versions.filter((version) => version.status === 'draft').length, 0)} /><Metric label="Approved packages" value={agents.filter((agent) => hasApprovedAgentPack(agent.current)).length} /></div>
    <Card><h2>Runtime path</h2><p className="muted">Use this page only when you want to turn an indexed source into a named runtime contract / Agent Pack. For normal code search and source review, stay on Sources or Quality.</p><div className="grid four" style={{ marginTop: 12 }}>{RUNTIME_STEPS.map(([title, text], index) => <div key={title} className="notice"><div className="label">Step {index + 1}</div><strong>{title}</strong><div className="muted">{text}</div></div>)}</div></Card>
    <div className="grid two">
      <Card><h2>Create Repo Agent</h2>{!signedIn ? <EmptyState text="Sign in to create Repo Agents." /> : gitResources.length === 0 ? <EmptyState text="Connect and index a Git source first. Repo Agent V0 is scoped to Git resources." /> : <form className="grid" onSubmit={createAgent}>
        <div className="notice"><strong>What happens after create?</strong><div className="muted">SourceBrief creates the repo agent and immediately generates a draft. Next, read the draft summary/diff; if it looks right, enter a review comment and publish. Nothing is deployed by create/publish.</div></div>
        <Field label="Git source"><select className="input" value={resourceId} onChange={(event) => setResourceId(event.target.value)} required><option value="">Choose Git source</option>{gitResources.map((resource) => <option key={resource.id} value={resource.id}>{resource.name}</option>)}</select></Field>
        <Field label="Context Pack stream"><input className="input" value={packKey} onChange={(event) => setPackKey(event.target.value)} placeholder="default" /></Field>
        <Field label="Agent key (optional)"><input className="input" value={agentKey} onChange={(event) => setAgentKey(event.target.value)} placeholder="derived from source name" /></Field>
        <Field label="Title (optional)"><input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Source Repo Agent" /></Field>
        <button className="btn" disabled={busy}>{busy ? 'Creating draft…' : 'Create Repo Agent + draft'}</button>
      </form>}</Card>
      <Card><h2>Operating boundary</h2><ul className="muted"><li>Repo Agent is the product surface; Skill Export is one Agent Pack packaging format.</li><li>Refresh compiles from the latest indexed Git snapshot; it does not clone or sync the corpus locally.</li><li>Publish, rollback, archive, invalidate, and scrub require review-gated comments.</li><li>Repo Agent V0 is read-only context. No production mutation permission is included.</li></ul></Card>
    </div>
    <div className="grid two">
      <Card><h2>Agents</h2>{agents.length === 0 ? <EmptyState text="No Repo Agents yet. Create one from a Git source." /> : <div className="table-wrap"><table><thead><tr><th>Agent</th><th>Pack</th><th>Current</th><th>Drafts</th><th>Action</th></tr></thead><tbody>{agents.map((agent) => <tr key={agent.id} className="clickable" onClick={() => setSelectedKey(agent.agent_key)}><td><strong>{agent.title}</strong><div className="muted">{agent.agent_key} · <StatusChip value={agent.status} /></div></td><td>{agent.pack_key}</td><td>{agent.current ? <span>v{agent.current.version} · <StatusChip value={agent.current.status} /></span> : <span className="muted">none</span>}</td><td>{agent.versions.filter((version) => version.status === 'draft').length}</td><td><button className="btn secondary" disabled={busy || agent.status === 'archived'} onClick={(event) => { event.stopPropagation(); void refreshAgent(agent); }}>Refresh draft</button></td></tr>)}</tbody></table></div>}</Card>
      <Card><h2>Selected Repo Agent</h2>{!selected ? <EmptyState text="Select or create a Repo Agent." /> : <div className="grid">
        <div className="section-card-head"><div><strong>{selected.title}</strong><div className="muted">{selected.agent_key} · pack {selected.pack_key}</div></div><StatusChip value={selected.status} /></div>
        {selected.current ? <div className="notice"><strong>Current published version v{selected.current.version}</strong><div className="muted">{short(selected.current.version_hash)} · published {fmt(selected.current.published_at)}</div><div className="grid" style={{ marginTop: 8 }}>{selectedCurrentHasPackage ? <><div><h3>Install Agent Pack</h3><div className="muted">Install or copy the approved thin adapter only. It points runtimes back to SourceBrief for current cited evidence.</div></div><pre className="code-block">{doctorCommand}</pre></> : <div className="notice"><h3>Published agent, package not approved yet</h3><div className="muted">This version has remote-live Repo Agent metadata, but no approved Skill Export / Agent Pack package. Generate and approve the Agent Pack format before running local package doctor.</div></div>}<div><h3>Publish metadata</h3><pre className="code-block">{jsonText(selected.current.install_json)}</pre></div></div></div> : <div className="notice"><strong>No published version yet.</strong><div className="muted">Click Refresh draft if there is no draft. Review the newest draft below, enter a comment, then Publish newest draft only if the summary/diff describes the repo correctly.</div></div>}
        <Field label="Review comment / reason"><input className="input" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Required for publish / rollback / archive / invalidate / scrub" /></Field>
        {newestDraft ? <div className="notice"><strong>Newest draft v{newestDraft.version}</strong><div className="muted">{short(newestDraft.version_hash)} · {fmt(newestDraft.created_at)}</div><div className="notice"><strong>What to review</strong><ul className="muted" style={{ margin: '8px 0 0 18px' }}><li><strong>Generated Repo Agent content</strong> below: README, runtime instructions, evidence preview, and manifest.</li><li>README should describe the intended repo/snapshot and warnings.</li><li>Evidence preview should contain concrete indexed chunks/symbols from this repo, not just metadata.</li><li>Install preview is metadata for future runtime install; it is not executed by publishing.</li></ul></div>{warnings(newestDraft).length ? <div className="notice">Warnings: <pre className="code-block">{jsonText(warnings(newestDraft))}</pre></div> : null}<div className="grid two"><div><h3>Draft summary</h3><pre className="code-block">{jsonText(newestDraft.summary_json)}</pre></div><div><h3>Draft diff</h3><pre className="code-block">{jsonText(newestDraft.diff_json)}</pre></div></div><h3>Install preview</h3><pre className="code-block">{jsonText(newestDraft.install_json)}</pre>{newestDraft.validation_json?.ok === false ? <pre className="code-block">{jsonText(newestDraft.validation_json)}</pre> : null}<button className="btn" disabled={busy || newestDraft.validation_json?.ok === false || selected.status === 'archived'} onClick={() => void action(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selected.agent_key}/versions/${newestDraft.version}/publish`)}>Publish newest draft</button></div> : null}
        {bundle ? <div className="notice"><div className="section-card-head"><div><strong>Generated Repo Agent content</strong><div className="muted">{bundle.agent_key} v{bundle.version} · {short(bundle.package_hash)} · review these files before publishing</div></div><button className="btn secondary" type="button" onClick={downloadBundle}>Download JSON</button></div><div className="grid" style={{ marginTop: 12 }}>{bundle.files.map((file) => <div key={file.path}><h3>{file.path}</h3><pre className="code-block">{file.content}</pre></div>)}</div></div> : previewVersion ? <div className="notice">Loading generated Repo Agent content…</div> : null}
        {!newestDraft && failed.length ? <div className="notice error"><strong>No valid draft yet</strong><div className="muted">The newest refresh failed. Fix the validation errors below, then refresh again.</div><pre className="code-block">{jsonText(failed[0].validation_json)}</pre></div> : null}
        <div className="toolbar"><button className="btn secondary" disabled={busy || selected.status === 'archived'} onClick={() => void action(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selected.agent_key}/archive`)}>Archive</button><button className="btn secondary" disabled={busy || selected.versions.some((version) => ['published', 'superseded'].includes(version.status))} title={selected.versions.some((version) => ['published', 'superseded'].includes(version.status)) ? 'Published/superseded versions are retained; archive/invalidate/scrub instead.' : undefined} onClick={() => void deleteAgent()}>Delete Repo Agent</button></div>
        {selected.versions.length ? <div className="table-wrap"><table><thead><tr><th>Version</th><th>Status</th><th>Hash</th><th>Context source</th><th>Skill adapter</th><th>Lifecycle</th></tr></thead><tbody>{selected.versions.map((version) => { const summary = version.summary_json as { context_pack?: { version?: number } | null; skill_export?: { version?: number } | null }; return <tr key={version.id}><td>v{version.version}</td><td><StatusChip value={version.status} /></td><td><span className="code">{short(version.version_hash)}</span></td><td>{summary.context_pack?.version ? `Context Pack v${summary.context_pack.version}` : 'Live indexed source'}</td><td>{summary.skill_export?.version ? `v${summary.skill_export.version}` : 'none'}</td><td>{versionActionButtons(version)}</td></tr>; })}</tbody></table></div> : null}
      </div>}</Card>
    </div>
  </main>;
}
