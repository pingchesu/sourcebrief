'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, SectionCard, Metric, Chip, StatusChip, EmptyState, Field, LifecyclePipeline, ReadinessBadge } from '../../components/ui';
import { AgentContextPreview } from '../../components/AgentContextPreview';
import { usePlatform } from '../../lib/platform-context';
import { ApiError, fmt, short } from '../../lib/api';
import { freshnessLabel, isActive, isIndexFailed, isVisible, lifecycleStages, readiness } from '../../lib/lifecycle';
import type { AgentContextResponse, FolderBundleUploadResponse, GitResourceEnv, IndexRun, ManifestDiff, Resource, ResourceManifest, ReviewItem } from '../../lib/types';

type ResourceType = 'git' | 'url' | 'markdown' | 'upload' | 'folder_bundle';
type GitDraft = { branch: string; clone_timeout: string; max_file_bytes: string; max_repo_files: string; max_repo_bytes: string; update_frequency: string };

function defaultUri(type: ResourceType) {
  if (type === 'git') return 'https://github.com/owner/repo.git';
  if (type === 'url') return 'https://example.com/docs';
  if (type === 'markdown') return 'doc://runbook.md';
  if (type === 'folder_bundle') return 'folder-bundle://upload.zip';
  return 'upload://notes.txt';
}

function defaultName(type: ResourceType) {
  return type === 'git' ? 'New repo source' : type === 'url' ? 'New URL source' : type === 'markdown' ? 'New markdown source' : type === 'folder_bundle' ? 'New folder bundle' : 'New upload source';
}

function toGitDraft(env: GitResourceEnv | null): GitDraft {
  return {
    branch: env?.branch ?? '',
    clone_timeout: env?.clone_timeout?.toString() ?? '',
    max_file_bytes: env?.max_file_bytes?.toString() ?? '',
    max_repo_files: env?.max_repo_files?.toString() ?? '',
    max_repo_bytes: env?.max_repo_bytes?.toString() ?? '',
    update_frequency: env?.update_frequency ?? 'daily',
  };
}

function optionalNumber(value: string) { return value.trim() ? Number(value.trim()) : null; }
function sizeDelta(base: number | null, head: number | null) {
  if (base == null && head == null) return '—';
  if (base == null && head != null) return `+${head.toLocaleString()}`;
  if (base != null && head == null) return `-${base.toLocaleString()}`;
  const delta = (head ?? 0) - (base ?? 0);
  return delta > 0 ? `+${delta.toLocaleString()}` : delta.toLocaleString();
}

// Attention-first ordering: failed → stale → not indexed → needs review → rest, then by name.
function attentionRank(resource: Resource, review?: ReviewItem): number {
  if (isIndexFailed(review?.last_index_status)) return 0;
  if (review?.freshness_status && review.freshness_status !== 'fresh') return 1;
  if (!resource.current_snapshot_id) return 2;
  if (resource.review_status !== 'approved') return 3;
  return 4;
}

export default function SourcesPage() {
  const { resources, reviewItems, usageItems, selectedResource, selectedResourceId, selectResource, snapshots, indexRuns, graph, loading, error, reload, client, settings, agent, provider } = usePlatform();

  const reviewByResource = useMemo(() => new Map(reviewItems.map((item) => [item.resource.id, item])), [reviewItems]);
  const usageByResource = useMemo(() => new Map(usageItems.map((item) => [item.resource_id, item])), [usageItems]);

  const visibleResources = useMemo(() => resources.filter(isVisible), [resources]);
  const sortedResources = useMemo(() => [...visibleResources].sort((a, b) => {
    const rankA = attentionRank(a, reviewByResource.get(a.id));
    const rankB = attentionRank(b, reviewByResource.get(b.id));
    return rankA !== rankB ? rankA - rankB : a.name.localeCompare(b.name);
  }), [visibleResources, reviewByResource]);

  const activeResources = useMemo(() => visibleResources.filter(isActive), [visibleResources]);
  const summary = useMemo(() => ({
    total: activeResources.length,
    retrievalReady: activeResources.filter((r) => r.retrieval_enabled && r.current_snapshot_id && !isIndexFailed(reviewByResource.get(r.id)?.last_index_status)).length,
    needsReview: activeResources.filter((r) => r.review_status !== 'approved').length,
    notIndexed: activeResources.filter((r) => !r.current_snapshot_id).length,
    indexFailed: visibleResources.filter((r) => isIndexFailed(reviewByResource.get(r.id)?.last_index_status)).length,
    stale: activeResources.filter((r) => { const f = reviewByResource.get(r.id)?.freshness_status; return f && f !== 'fresh'; }).length,
  }), [activeResources, visibleResources, reviewByResource]);

  // Connect panel state.
  const [connectOpen, setConnectOpen] = useState(false);
  const [type, setType] = useState<ResourceType>('git');
  const [name, setName] = useState(defaultName('git'));
  const [uri, setUri] = useState(defaultUri('git'));
  const [branch, setBranch] = useState('main');
  const [frequency, setFrequency] = useState('daily');
  const [content, setContent] = useState('');
  const [filename, setFilename] = useState('notes.txt');
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [supersedesResourceId, setSupersedesResourceId] = useState<string | null>(null);
  const [refreshNow, setRefreshNow] = useState(true);
  const [connectBusy, setConnectBusy] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [connectResult, setConnectResult] = useState<Resource | null>(null);

  // Detail action state.
  const [refreshing, setRefreshing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [preview, setPreview] = useState<AgentContextResponse | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ResourceManifest | null>(null);
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [manifestDiff, setManifestDiff] = useState<ManifestDiff | null>(null);
  const [manifestDiffError, setManifestDiffError] = useState<string | null>(null);
  const [manifestDiffLimit, setManifestDiffLimit] = useState(25);

  // Git environment state.
  const [gitEnv, setGitEnv] = useState<GitResourceEnv | null>(null);
  const [gitDraft, setGitDraft] = useState<GitDraft>(toGitDraft(null));
  const [gitEnvLoading, setGitEnvLoading] = useState(false);
  const [gitEnvBusy, setGitEnvBusy] = useState(false);
  const [gitEnvError, setGitEnvError] = useState<string | null>(null);
  const [gitEnvSaved, setGitEnvSaved] = useState(false);

  const selectedReview = selectedResource ? reviewByResource.get(selectedResource.id) : undefined;
  const lastIndexStatus = indexRuns[0]?.status ?? selectedReview?.last_index_status ?? null;
  const isGit = selectedResource?.type === 'git';
  const isFolderBundle = selectedResource?.type === 'folder_bundle';

  // Reset detail-scoped state when selection changes.
  useEffect(() => { setPreview(null); setPreviewError(null); setActionError(null); setGitEnvSaved(false); setManifest(null); setManifestError(null); setManifestDiff(null); setManifestDiffError(null); setManifestDiffLimit(25); }, [selectedResourceId]);

  // Load git env for the selected git source.
  useEffect(() => {
    if (!selectedResource || selectedResource.type !== 'git') { setGitEnv(null); setGitDraft(toGitDraft(null)); return; }
    let cancelled = false;
    setGitEnvLoading(true); setGitEnvError(null);
    client<GitResourceEnv[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/git-env`)
      .then((list) => { if (cancelled) return; const found = list.find((env) => env.resource_id === selectedResource.id) ?? null; setGitEnv(found); setGitDraft(toGitDraft(found)); })
      .catch((err) => { if (!cancelled) setGitEnvError(String(err)); })
      .finally(() => { if (!cancelled) setGitEnvLoading(false); });
    return () => { cancelled = true; };
  }, [client, selectedResource, settings.workspaceId, settings.projectId]);

  useEffect(() => {
    if (!selectedResource || selectedResource.type !== 'folder_bundle' || !selectedResource.current_snapshot_id) { setManifest(null); return; }
    let cancelled = false;
    setManifestError(null);
    client<ResourceManifest>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/manifest`)
      .then((value) => { if (!cancelled) setManifest(value); })
      .catch((err) => { if (!cancelled) { setManifest(null); setManifestError(String(err)); } });
    return () => { cancelled = true; };
  }, [client, selectedResource, settings.workspaceId, settings.projectId]);

  useEffect(() => {
    if (!selectedResource || selectedResource.type !== 'folder_bundle' || !selectedResource.current_snapshot_id) { setManifestDiff(null); return; }
    let cancelled = false;
    setManifestDiffError(null);
    client<ManifestDiff>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/manifest-diff?limit=${manifestDiffLimit}`)
      .then((value) => { if (!cancelled) setManifestDiff(value); })
      .catch((err) => {
        if (cancelled) return;
        setManifestDiff(null);
        if (err instanceof ApiError && err.status === 409) setManifestDiffError(null);
        else setManifestDiffError(String(err));
      });
    return () => { cancelled = true; };
  }, [client, selectedResource, settings.workspaceId, settings.projectId, manifestDiffLimit]);

  function changeType(next: ResourceType) {
    setType(next);
    setUri(defaultUri(next));
    setName(defaultName(next));
    setSupersedesResourceId(null);
    if (next === 'folder_bundle') setFrequency('manual');
  }

  function openConnectSource() {
    setConnectOpen((open) => !open);
    setType('git');
    setName(defaultName('git'));
    setUri(defaultUri('git'));
    setFrequency('daily');
    setZipFile(null);
    setSupersedesResourceId(null);
    setConnectResult(null);
    setConnectError(null);
  }

  function startFolderBundleVersion(resource: Resource) {
    setConnectOpen(true);
    setType('folder_bundle');
    setFrequency('manual');
    setName(resource.source_family_label || resource.name);
    setSupersedesResourceId(resource.id);
    setZipFile(null);
    setConnectResult(null);
    setConnectError(null);
  }

  async function submitConnect(event: FormEvent) {
    event.preventDefault();
    setConnectBusy(true); setConnectError(null); setConnectResult(null);
    try {
      if (type === 'folder_bundle') {
        if (!zipFile) throw new Error('Choose a .zip folder bundle first.');
        const formData = new FormData();
        if (!supersedesResourceId) formData.append('name', name);
        formData.append('update_frequency', frequency);
        if (supersedesResourceId) formData.append('supersedes_resource_id', supersedesResourceId);
        formData.append('zip_file', zipFile);
        const response = await fetch(`${settings.apiBaseUrl}/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/upload-folder-bundle`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${settings.sessionToken}` },
          body: formData,
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({ detail: 'upload failed' }));
          throw new Error(typeof body.detail === 'string' ? body.detail : 'upload failed');
        }
        const data = await response.json() as FolderBundleUploadResponse;
        setConnectResult(data.resource);
        setSupersedesResourceId(null);
        setZipFile(null);
        await reload();
        await selectResource(data.resource.id);
        return;
      }
      const source_config = type === 'git'
        ? { url: uri, branch }
        : type === 'url'
          ? { url: uri }
          : type === 'upload'
            ? { content, filename, content_type: 'text/plain' }
            : { content, path: uri, title: name };
      const resource = await client<Resource>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources`, {
        method: 'POST',
        body: JSON.stringify({ type, name, uri, update_frequency: frequency, source_config }),
      });
      if (refreshNow) {
        await client<IndexRun>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${resource.id}/refresh`, { method: 'POST' });
      }
      setConnectResult(resource);
      await reload();
      await selectResource(resource.id);
    } catch (err) { setConnectError(String(err)); }
    finally { setConnectBusy(false); }
  }

  async function reindexSelected() {
    if (!selectedResource) return;
    setRefreshing(true); setActionError(null);
    try {
      await client(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/refresh`, { method: 'POST' });
      await reload();
      await selectResource(selectedResource.id);
    } catch (err) { setActionError(String(err)); }
    finally { setRefreshing(false); }
  }

  async function previewSelected() {
    if (!selectedResource) return;
    setPreviewBusy(true); setPreviewError(null);
    try {
      setPreview(await client<AgentContextResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-context`, {
        method: 'POST',
        body: JSON.stringify({ query: `Summarize what ${selectedResource.name} contributes to this generated agent. Include important files, concepts, operational boundaries, and what a reviewer should inspect. Cite exact context.`, runtime: agent?.default_runtime ?? 'hermes', resource_ids: [selectedResource.id], top_k: 10, max_chars: 18000, include_code_symbols: true }),
      }));
    } catch (err) { setPreviewError(String(err)); }
    finally { setPreviewBusy(false); }
  }

  async function saveGitEnv(event: FormEvent) {
    event.preventDefault();
    if (!selectedResource) return;
    setGitEnvBusy(true); setGitEnvError(null); setGitEnvSaved(false);
    try {
      const updated = await client<GitResourceEnv>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/git-env`, {
        method: 'PATCH',
        body: JSON.stringify({
          branch: gitDraft.branch.trim() || null,
          clone_timeout: optionalNumber(gitDraft.clone_timeout),
          max_file_bytes: optionalNumber(gitDraft.max_file_bytes),
          max_repo_files: optionalNumber(gitDraft.max_repo_files),
          max_repo_bytes: optionalNumber(gitDraft.max_repo_bytes),
          update_frequency: gitDraft.update_frequency,
        }),
      });
      setGitEnv(updated);
      setGitDraft(toGitDraft(updated));
      setGitEnvSaved(true);
      await reload();
    } catch (err) { setGitEnvError(String(err)); }
    finally { setGitEnvBusy(false); }
  }

  const stages = selectedResource ? lifecycleStages(selectedResource, selectedReview, lastIndexStatus) : [];
  const freshness = selectedResource ? freshnessLabel(selectedReview) : null;
  const reindexLabel = isGit ? 'Update repo & reindex' : isFolderBundle ? 'Upload new zip to update' : 'Reindex';

  return <main className="page">
    <PageHeader
      eyebrow="Sources"
      title="Connected sources and lifecycle"
      description="Every context source from connect through indexing, review, and retrieval. Select a source to inspect its evidence and run maintenance in place."
      actions={<>
        <button className="btn" onClick={openConnectSource}>{connectOpen ? 'Close connect' : 'Connect source'}</button>
        <button className="btn secondary" onClick={() => reload()} disabled={loading}>{loading ? 'Loading…' : 'Reload'}</button>
      </>}
    />

    {error ? <div className="notice error">Could not load source data: {error}</div> : null}
    {provider && provider.status !== 'ok' ? <div className="notice">Embedding provider {provider.status} · {provider.embedding.provider}/{provider.embedding.model}. Indexing and retrieval may be degraded.</div> : null}

    <section className="card">
      <div className="health-strip">
        <div className="health-item"><span className="label">Active</span><span className="health-item-value">{summary.total}</span></div>
        <div className="health-item"><span className="label">Retrieval-ready</span><span className="health-item-value"><Chip tone={summary.retrievalReady > 0 ? 'ready' : 'neutral'}>{summary.retrievalReady}</Chip></span></div>
        <div className="health-item"><span className="label">Needs review</span><span className="health-item-value"><Chip tone={summary.needsReview > 0 ? 'warn' : 'neutral'}>{summary.needsReview}</Chip></span></div>
        <div className="health-item"><span className="label">Not indexed</span><span className="health-item-value"><Chip tone={summary.notIndexed > 0 ? 'warn' : 'neutral'}>{summary.notIndexed}</Chip></span></div>
        <div className="health-item"><span className="label">Index failed</span><span className="health-item-value"><Chip tone={summary.indexFailed > 0 ? 'risk' : 'neutral'}>{summary.indexFailed}</Chip></span></div>
        <div className="health-item"><span className="label">Stale</span><span className="health-item-value"><Chip tone={summary.stale > 0 ? 'warn' : 'neutral'}>{summary.stale}</Chip></span></div>
      </div>
    </section>

    {connectOpen ? <section className="card connect-panel">
      <div className="section-card-head"><div><h2 className="section-card-title">Connect a source</h2><p className="muted section-card-desc">Pick a source type — only the fields it needs are shown. New sources appear in the list and are selected automatically.</p></div></div>
      <form className="grid two" onSubmit={submitConnect}>
        <div className="grid">
          <Field label="Source type"><select className="input" value={type} onChange={(event) => changeType(event.target.value as ResourceType)}><option value="git">Git repository</option><option value="folder_bundle">Folder bundle (.zip)</option><option value="url">URL / web page</option><option value="markdown">Markdown / inline doc</option><option value="upload">Upload text</option></select></Field>
          {supersedesResourceId ? <div className="notice">Uploading a new version of {name}. ContextSmith keeps the same family label and compares it to the previous manifest.</div> : <Field label="Name"><input className="input" value={name} onChange={(event) => setName(event.target.value)} /></Field>}
          {type !== 'folder_bundle' ? <Field label={type === 'git' ? 'Git URL' : type === 'url' ? 'URL' : 'URI / path'}><input className="input" value={uri} onChange={(event) => setUri(event.target.value)} /></Field> : null}
          {type === 'git' ? <div className="grid two"><Field label="Branch"><input className="input" value={branch} onChange={(event) => setBranch(event.target.value)} /></Field></div> : null}
          {type === 'folder_bundle' ? <Field label="Folder bundle zip"><input className="input" type="file" accept=".zip,application/zip" onChange={(event) => setZipFile(event.target.files?.[0] ?? null)} /><div className="muted">Upload a zipped folder. ContextSmith validates paths and archives before indexing.</div></Field> : null}
          {type === 'upload' ? <Field label="Filename"><input className="input" value={filename} onChange={(event) => setFilename(event.target.value)} /></Field> : null}
          {type === 'markdown' || type === 'upload' ? <Field label="Content"><textarea className="input" rows={8} value={content} onChange={(event) => setContent(event.target.value)} /></Field> : null}
          {type === 'folder_bundle'
            ? <div className="notice">Folder bundles are manual in this milestone. Upload a new zip when the folder changes.</div>
            : <div className="grid two"><Field label="Update frequency"><select className="input" value={frequency} onChange={(event) => setFrequency(event.target.value)}><option value="manual">manual</option><option value="hourly">hourly</option><option value="daily">daily</option><option value="weekly">weekly</option></select></Field><label className={`scope-pill ${refreshNow ? 'active' : ''}`}><input type="checkbox" checked={refreshNow} onChange={(event) => setRefreshNow(event.target.checked)} /> Create index immediately</label></div>}
          <button className="btn" disabled={connectBusy}>{connectBusy ? 'Connecting…' : 'Connect source'}</button>
        </div>
        <div className="grid">
          {connectError ? <div className="notice error">{connectError}</div> : null}
          {connectResult ? <div className="notice">Source connected — {refreshNow ? 'now indexing' : 'not yet indexed'}. <strong>{connectResult.name}</strong> is selected in the list.</div> : <div className="empty">Connected sources are added to the list and indexed when requested. Private-source credentials will be handled by named connections in Settings.</div>}
        </div>
      </form>
    </section> : null}

    <div className="grid two">
      <SectionCard title="Sources" description="Attention-first: failed, stale, not indexed, and unreviewed sources lead.">
        {sortedResources.length === 0
          ? <div className="grid"><EmptyState text="No sources connected yet. Connect a git repo, URL, or document to start building context." /><button className="btn" onClick={openConnectSource}>Connect source</button></div>
          : <div className="table-wrap"><table>
            <thead><tr><th>Source</th><th>Readiness</th><th>Freshness</th><th>Index</th><th>Review</th><th>Uses</th><th>Action</th></tr></thead>
            <tbody>
              {sortedResources.map((resource) => {
                const review = reviewByResource.get(resource.id);
                const usage = usageByResource.get(resource.id);
                const fresh = freshnessLabel(review);
                const lastIndex = review?.last_index_status ?? null;
                const uses = usage ? (usage.hit_count || usage.query_count) : null;
                return <tr key={resource.id} className={`clickable ${resource.id === selectedResourceId ? 'selected' : ''}`} onClick={() => void selectResource(resource.id)}>
                  <td><strong>{resource.source_family_label || resource.name}</strong>{resource.version_label ? <div className="muted">{resource.version_label}</div> : null}<div className="toolbar" style={{ gap: 6, marginTop: 4 }}><Chip>{resource.type}</Chip>{resource.status !== 'active' ? <StatusChip value={resource.status} /> : null}</div></td>
                  <td><ReadinessBadge state={readiness(resource, review)} lastIndexStatus={lastIndex} /></td>
                  <td>{fresh.label === '—' ? <span className="muted">—</span> : <span><StatusChip value={fresh.label} />{fresh.ageDays != null ? <div className="code">{fresh.ageDays}d</div> : null}</span>}</td>
                  <td>{lastIndex ? <StatusChip value={lastIndex} /> : <span className="muted">not indexed</span>}</td>
                  <td><StatusChip value={resource.review_status} /></td>
                  <td>{uses != null ? uses : <span className="muted">—</span>}</td>
                  <td><button className="btn secondary" onClick={(event) => { event.stopPropagation(); void selectResource(resource.id); }}>Inspect</button></td>
                </tr>;
              })}
            </tbody>
          </table></div>}
      </SectionCard>

      <SectionCard title="Source detail" description="Evidence and in-place maintenance for the selected source." action={selectedResource ? <div className="toolbar"><button className="btn" disabled={refreshing || loading || isFolderBundle} onClick={() => void reindexSelected()}>{refreshing ? 'Working…' : reindexLabel}</button>{isFolderBundle ? <button className="btn secondary" onClick={() => startFolderBundleVersion(selectedResource)}>Upload new version</button> : null}</div> : undefined}>
        {!selectedResource
          ? <EmptyState text="Select a source from the list to inspect its lifecycle, snapshots, index runs, graph, and generated context." />
          : <div className="grid">
            <LifecyclePipeline stages={stages} />
            <div className="grid three">
              <Metric label="Readiness" value={<ReadinessBadge state={readiness(selectedResource, selectedReview)} lastIndexStatus={lastIndexStatus} />} />
              <Metric label="Freshness" value={freshness && freshness.label !== '—' ? <StatusChip value={freshness.label} /> : '—'} hint={freshness?.ageDays != null ? `${freshness.ageDays}d old` : undefined} />
              <Metric label="Graph" value={graph ? `${graph.node_count}/${graph.edge_count}` : '—'} hint="nodes / edges" />
            </div>
            <div className="grid two">
              <div><div className="label">Type</div><Chip>{selectedResource.type}</Chip></div>
              <div><div className="label">Retrieval</div><Chip tone={selectedResource.retrieval_enabled ? 'ready' : 'warn'}>{selectedResource.retrieval_enabled ? 'enabled' : 'off'}</Chip></div>
            </div>
            <div><div className="label">Source location</div><div className="muted">{selectedResource.uri}</div></div>
            {selectedResource.type === 'folder_bundle' ? <div className="notice">
              <strong>Folder manifest</strong>
              {manifest ? <div className="grid three" style={{ marginTop: 8 }}>
                <Metric label="Files" value={manifest.file_count} />
                <Metric label="Unsupported" value={manifest.unsupported_file_count} />
                <Metric label="Warnings" value={manifest.parser_warning_count} />
              </div> : <div className="muted" style={{ marginTop: 8 }}>{manifestError ? `Manifest unavailable: ${manifestError}` : 'Manifest will appear after indexing completes.'}</div>}
              {manifest ? <div className="muted" style={{ marginTop: 6 }}>{manifest.total_bytes.toLocaleString()} bytes scanned from the uploaded zip.</div> : null}
              {manifest ? <div className="table-wrap" style={{ marginTop: 8 }}><table><thead><tr><th>Path</th><th>Status</th><th>Warnings</th><th>Size</th></tr></thead><tbody>{manifest.files.slice(0, 8).map((file) => <tr key={file.id}><td><span className="code">{file.normalized_path}</span></td><td><StatusChip value={file.status} /></td><td>{file.warnings_json.length ? file.warnings_json.join('; ') : <span className="muted">—</span>}</td><td>{file.size_bytes.toLocaleString()}</td></tr>)}</tbody></table></div> : null}
            </div> : null}
            {selectedResource.type === 'folder_bundle' ? <div className="notice">
              <strong>Manifest diff</strong>
              {manifestDiff ? <>
                <div className="grid five" style={{ marginTop: 8 }}>
                  <Metric label="Added" value={manifestDiff.added_count} />
                  <Metric label="Changed" value={manifestDiff.changed_count} />
                  <Metric label="Deleted" value={manifestDiff.deleted_count} />
                  <Metric label="Unchanged" value={manifestDiff.unchanged_count} />
                  <Metric label="Warnings" value={manifestDiff.warning_changed_count} />
                </div>
                <div className="muted" style={{ marginTop: 6 }}>{manifestDiff.deleted_file_impact.message}</div>
                <div className="muted" style={{ marginTop: 4 }}>Showing {manifestDiff.row_count_returned.toLocaleString()} of {manifestDiff.total_row_count.toLocaleString()} changed rows.</div>
                <div className="table-wrap" style={{ marginTop: 8 }}><table><thead><tr><th>Path</th><th>Change</th><th>Size delta</th><th>Base</th><th>Head</th><th>Reason</th></tr></thead><tbody>{manifestDiff.rows.map((row) => <tr key={`${row.change_type}-${row.normalized_path}`}><td><span className="code">{row.normalized_path}</span></td><td><StatusChip value={row.change_type} /></td><td>{sizeDelta(row.base_size_bytes, row.head_size_bytes)}</td><td>{row.base_status ?? <span className="muted">—</span>}</td><td>{row.head_status ?? <span className="muted">—</span>}</td><td>{row.reason}</td></tr>)}</tbody></table></div>
                {manifestDiff.next_cursor ? <button className="btn secondary" style={{ marginTop: 8 }} onClick={() => setManifestDiffLimit((value) => value + 25)}>Show more diff rows</button> : null}
              </> : manifestDiffError ? <div className="notice error" style={{ marginTop: 8 }}>Manifest diff unavailable: {manifestDiffError}</div> : <div className="muted" style={{ marginTop: 8 }}>Manifest diff will appear after a second uploaded version.</div>}
            </div> : null}
            <div><div className="label">Last refresh</div><div className="muted">{fmt(selectedResource.last_refresh_finished_at)}</div></div>
            {actionError ? <div className="notice error">{actionError}</div> : null}
          </div>}
      </SectionCard>
    </div>

    {selectedResource ? <div className="grid two">
      <Card><h2>Refresh history</h2>{snapshots.length === 0 ? <EmptyState text="No refresh history yet. Reindex to build the first reviewed snapshot." /> : <div className="table-wrap"><table><thead><tr><th>Status</th><th>Indexed</th></tr></thead><tbody>{snapshots.map((s) => <tr key={s.id}><td>{s.is_current ? <StatusChip value="current" /> : <StatusChip value={s.status} />}</td><td>{fmt(s.indexed_at)}</td></tr>)}</tbody></table></div>}</Card>
      <Card><h2>Index activity</h2>{indexRuns.length === 0 ? <EmptyState text="No index runs yet." /> : <div className="table-wrap"><table><thead><tr><th>Status</th><th>Trigger</th><th>Chunks</th><th>Symbols</th><th>Finished</th></tr></thead><tbody>{indexRuns.slice(0, 10).map((run) => <tr key={run.id}><td><StatusChip value={run.status} />{run.error_message ? <div className="muted" style={{ color: 'var(--risk)' }}>{run.error_message}</div> : null}</td><td>{run.trigger}</td><td>{run.chunks_created}</td><td>{run.symbols_created}</td><td>{fmt(run.finished_at)}</td></tr>)}</tbody></table></div>}</Card>
    </div> : null}

    {selectedResource ? <Card>
      <div className="section-card-head"><div><h2 className="section-card-title">Generated context preview</h2><p className="muted section-card-desc">The actual context this source contributes to the agent — citations and code symbols included.</p></div><button className="btn secondary" disabled={previewBusy} onClick={() => void previewSelected()}>{previewBusy ? 'Generating…' : 'Generate preview'}</button></div>
      {previewError ? <div className="notice error">{previewError}</div> : null}
      <AgentContextPreview result={preview} resources={resources} title={`What ${selectedResource.name} contributes`} />
    </Card> : null}
  </main>;
}
