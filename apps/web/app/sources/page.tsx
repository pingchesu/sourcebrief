'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, SectionCard, Metric, Chip, StatusChip, EmptyState, Field, LifecyclePipeline, ReadinessBadge } from '../../components/ui';
import { AgentContextPreview } from '../../components/AgentContextPreview';
import { usePlatform } from '../../lib/platform-context';
import { ApiError, apiFetchBlob, fmt, short } from '../../lib/api';
import { freshnessLabel, isActive, isIndexFailed, isVisible, lifecycleStages, readiness } from '../../lib/lifecycle';
import type { AgentContextResponse, ContextArtifact, ContextPackSummary, ContextPackVersion, FolderBundleUploadResponse, GitResourceEnv, IndexRun, ManifestDiff, Resource, ResourceManifest, SectionImpact, SkillExport, SnapshotSections, ReviewItem } from '../../lib/types';

type ResourceType = 'git' | 'url' | 'markdown' | 'upload' | 'folder_bundle';
type GitDraft = { branch: string; clone_timeout: string; max_file_bytes: string; max_repo_files: string; max_repo_bytes: string; update_frequency: string };

const SAMPLE_MARKDOWN = `# SourceBrief sample runbook

This deterministic sample proves that SourceBrief can connect a source, index it, and return cited context.

## First question to ask
What does this sample runbook prove, and which section should a reviewer inspect first?

## Operational boundary
This sample is public, local to the SourceBrief project, and safe for first-run demos.`;

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
function numberMetric(record: Record<string, unknown>, key: string, fallback: number) {
  const value = record[key];
  return typeof value === 'number' ? value : fallback;
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
    retrievalReady: activeResources.filter((r) => r.queryable ?? (r.retrieval_enabled && r.current_snapshot_id && !isIndexFailed(reviewByResource.get(r.id)?.last_index_status))).length,
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
  const [snapshotSections, setSnapshotSections] = useState<SnapshotSections | null>(null);
  const [snapshotSectionsError, setSnapshotSectionsError] = useState<string | null>(null);
  const [sectionImpact, setSectionImpact] = useState<SectionImpact | null>(null);
  const [sectionImpactError, setSectionImpactError] = useState<string | null>(null);
  const [snapshotSectionsLimit, setSnapshotSectionsLimit] = useState(8);
  const [contextArtifacts, setContextArtifacts] = useState<ContextArtifact[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<ContextArtifact | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [artifactBusy, setArtifactBusy] = useState(false);
  const [artifactSourceLimit, setArtifactSourceLimit] = useState(8);
  const [artifactCitationLimit, setArtifactCitationLimit] = useState(8);
  const [ackArtifactWarnings, setAckArtifactWarnings] = useState(false);
  const [rejectArtifactReason, setRejectArtifactReason] = useState('');
  const [contextPacks, setContextPacks] = useState<ContextPackSummary[]>([]);
  const [selectedPack, setSelectedPack] = useState<ContextPackVersion | null>(null);
  const [packError, setPackError] = useState<string | null>(null);
  const [packBusy, setPackBusy] = useState(false);
  const [packComment, setPackComment] = useState('');
  const [packArtifactIds, setPackArtifactIds] = useState<string[]>([]);
  const [skillExports, setSkillExports] = useState<SkillExport[]>([]);
  const [selectedSkillExport, setSelectedSkillExport] = useState<SkillExport | null>(null);
  const [skillExportError, setSkillExportError] = useState<string | null>(null);
  const [skillExportBusy, setSkillExportBusy] = useState(false);
  const [skillExportComment, setSkillExportComment] = useState('');
  const [selectedSkillExportFilePath, setSelectedSkillExportFilePath] = useState<string | null>(null);

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
  useEffect(() => { setPreview(null); setPreviewError(null); setActionError(null); setGitEnvSaved(false); setManifest(null); setManifestError(null); setManifestDiff(null); setManifestDiffError(null); setManifestDiffLimit(25); setSnapshotSections(null); setSnapshotSectionsError(null); setSnapshotSectionsLimit(8); setSectionImpact(null); setSectionImpactError(null); setContextArtifacts([]); setSelectedArtifact(null); setArtifactError(null); setArtifactBusy(false); setArtifactSourceLimit(8); setArtifactCitationLimit(8); setAckArtifactWarnings(false); setRejectArtifactReason(''); setSelectedPack(null); setPackError(null); setPackComment(''); setPackArtifactIds([]); setSkillExports([]); setSelectedSkillExport(null); setSkillExportError(null); setSkillExportComment(''); setSelectedSkillExportFilePath(null); }, [selectedResourceId]);

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

  useEffect(() => {
    if (!selectedResource || selectedResource.type !== 'folder_bundle' || !selectedResource.current_snapshot_id) { setSnapshotSections(null); setSectionImpact(null); return; }
    let cancelled = false;
    setSnapshotSectionsError(null);
    setSectionImpactError(null);
    client<SnapshotSections>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/snapshot-sections?limit=${snapshotSectionsLimit}`)
      .then((value) => { if (!cancelled) setSnapshotSections(value); })
      .catch((err) => { if (!cancelled) { setSnapshotSections(null); setSnapshotSectionsError(String(err)); } });
    client<SectionImpact>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/section-impact`)
      .then((value) => { if (!cancelled) setSectionImpact(value); })
      .catch((err) => { if (!cancelled) { setSectionImpact(null); setSectionImpactError(String(err)); } });
    return () => { cancelled = true; };
  }, [client, selectedResource, settings.workspaceId, settings.projectId, snapshotSectionsLimit]);

  useEffect(() => {
    if (!selectedResource || selectedResource.type !== 'folder_bundle' || !selectedResource.current_snapshot_id) { setContextArtifacts([]); setSelectedArtifact(null); return; }
    let cancelled = false;
    setArtifactError(null);
    client<ContextArtifact[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/context-artifacts?artifact_type=resource_map`)
      .then((rows) => {
        if (cancelled) return;
        setContextArtifacts(rows);
        setPackArtifactIds(rows.filter((row) => row.status === 'approved').map((row) => row.id));
        const latest = rows[0];
        if (!latest) { setSelectedArtifact(null); return; }
        return client<ContextArtifact>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-artifacts/${latest.id}`)
          .then((artifact) => { if (!cancelled) setSelectedArtifact(artifact); });
      })
      .catch((err) => { if (!cancelled) { setContextArtifacts([]); setSelectedArtifact(null); setArtifactError(String(err)); } });
    return () => { cancelled = true; };
  }, [client, selectedResource, settings.workspaceId, settings.projectId]);

  useEffect(() => {
    setAckArtifactWarnings(false);
    setRejectArtifactReason('');
    setArtifactSourceLimit(8);
    setArtifactCitationLimit(8);
  }, [selectedArtifact?.id]);

  async function refreshContextPacks() {
    try {
      const packs = await client<ContextPackSummary[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-packs`);
      setContextPacks(packs);
      const first = packs[0]?.current ?? packs[0]?.latest ?? null;
      setSelectedPack(first);
      setPackError(null);
    } catch (err) {
      setContextPacks([]);
      setSelectedPack(null);
      setPackError(String(err));
    }
  }

  useEffect(() => { void refreshContextPacks(); }, [client, settings.workspaceId, settings.projectId]);

  async function refreshSkillExports(pack = selectedPack) {
    if (!pack) { setSkillExports([]); setSelectedSkillExport(null); return; }
    try {
      const exports = await client<SkillExport[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-packs/${pack.pack_key}/versions/${pack.version}/skill-exports`);
      setSkillExports(exports);
      setSelectedSkillExport((current) => current ? exports.find((item) => item.id === current.id) ?? exports[0] ?? null : exports[0] ?? null);
    } catch (err) {
      setSkillExportError(String(err));
      setSkillExports([]);
      setSelectedSkillExport(null);
    }
  }

  useEffect(() => { void refreshSkillExports(selectedPack); }, [selectedPack?.id, client, settings.workspaceId, settings.projectId]);

  useEffect(() => {
    if (!selectedSkillExport) { setSelectedSkillExportFilePath(null); return; }
    setSelectedSkillExportFilePath((current) => selectedSkillExport.files.some((file) => file.path === current) ? current : selectedSkillExport.files[0]?.path ?? null);
  }, [selectedSkillExport?.id]);

  function changeType(next: ResourceType) {
    setType(next);
    setUri(defaultUri(next));
    setName(defaultName(next));
    setContent(next === 'markdown' ? SAMPLE_MARKDOWN : '');
    setFilename(next === 'upload' ? 'notes.txt' : filename);
    setSupersedesResourceId(null);
    setFrequency(next === 'folder_bundle' ? 'manual' : 'daily');
  }

  function useSampleMarkdown() {
    setConnectOpen(true);
    setType('markdown');
    setName('SourceBrief sample runbook');
    setUri('doc://sourcebrief-sample-runbook.md');
    setContent(SAMPLE_MARKDOWN);
    setFrequency('manual');
    setRefreshNow(true);
    setZipFile(null);
    setSupersedesResourceId(null);
    setConnectResult(null);
    setConnectError(null);
  }

  function openConnectSource() {
    setConnectOpen((open) => !open);
    setType('git');
    setName(defaultName('git'));
    setUri(defaultUri('git'));
    setBranch('main');
    setFrequency('daily');
    setContent('');
    setFilename('notes.txt');
    setRefreshNow(true);
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

  async function refreshArtifacts(resourceId: string) {
    const rows = await client<ContextArtifact[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${resourceId}/context-artifacts?artifact_type=resource_map`);
    setContextArtifacts(rows);
    setPackArtifactIds(rows.filter((row) => row.status === 'approved').map((row) => row.id));
    if (rows[0]) setSelectedArtifact(await client<ContextArtifact>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-artifacts/${rows[0].id}`));
    else setSelectedArtifact(null);
  }

  async function compileResourceMap(force = false) {
    if (!selectedResource) return;
    setArtifactBusy(true); setArtifactError(null);
    try {
      const artifact = await client<ContextArtifact>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/context-artifacts/resource-map${force ? '?force=true' : ''}`, { method: 'POST' });
      setSelectedArtifact(artifact);
      await refreshArtifacts(selectedResource.id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && selectedResource) {
        await refreshArtifacts(selectedResource.id).catch(() => undefined);
      }
      setArtifactError(String(err));
    }
    finally { setArtifactBusy(false); }
  }

  async function approveArtifact() {
    if (!selectedArtifact) return;
    setArtifactBusy(true); setArtifactError(null);
    try {
      const artifact = await client<ContextArtifact>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-artifacts/${selectedArtifact.id}/approve`, { method: 'POST', body: JSON.stringify({ acknowledge_warnings: ackArtifactWarnings }) });
      setSelectedArtifact(artifact);
      if (selectedResource) await refreshArtifacts(selectedResource.id);
    } catch (err) { setArtifactError(String(err)); }
    finally { setArtifactBusy(false); }
  }

  async function rejectArtifact() {
    if (!selectedArtifact) return;
    const reason = rejectArtifactReason.trim();
    if (!reason) { setArtifactError('Enter a rejection reason before rejecting this artifact.'); return; }
    setArtifactBusy(true); setArtifactError(null);
    try {
      const artifact = await client<ContextArtifact>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-artifacts/${selectedArtifact.id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
      setSelectedArtifact(artifact);
      if (selectedResource) await refreshArtifacts(selectedResource.id);
    } catch (err) { setArtifactError(String(err)); }
    finally { setArtifactBusy(false); }
  }

  async function createPackDraft() {
    if (packArtifactIds.length === 0) { setPackError('Select at least one approved Resource Map artifact before creating a Context Pack draft.'); return; }
    setPackBusy(true); setPackError(null);
    try {
      const pack = await client<ContextPackVersion>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-packs/default/versions`, {
        method: 'POST',
        body: JSON.stringify({ title: 'Default context pack', description: 'Curated pack from approved Resource Map artifacts.', artifact_ids: packArtifactIds }),
      });
      setSelectedPack(pack);
      await refreshContextPacks();
    } catch (err) { setPackError(String(err)); }
    finally { setPackBusy(false); }
  }

  async function publishPack() {
    if (!selectedPack) return;
    const comment = packComment.trim();
    if (!comment) { setPackError('Enter a publish comment first.'); return; }
    setPackBusy(true); setPackError(null);
    try {
      const pack = await client<ContextPackVersion>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-packs/${selectedPack.pack_key}/versions/${selectedPack.version}/publish`, { method: 'POST', body: JSON.stringify({ comment }) });
      setSelectedPack(pack); setPackComment(''); await refreshContextPacks();
    } catch (err) { setPackError(String(err)); }
    finally { setPackBusy(false); }
  }

  async function rollbackPack(version: ContextPackVersion) {
    const reason = packComment.trim();
    if (!reason) { setPackError('Enter a rollback reason first.'); return; }
    setPackBusy(true); setPackError(null);
    try {
      const pack = await client<ContextPackVersion>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-packs/${version.pack_key}/versions/${version.version}/rollback`, { method: 'POST', body: JSON.stringify({ reason }) });
      setSelectedPack(pack); setPackComment(''); await refreshContextPacks();
    } catch (err) { setPackError(String(err)); }
    finally { setPackBusy(false); }
  }

  async function invalidatePack(version: ContextPackVersion) {
    const reason = packComment.trim();
    if (!reason) { setPackError('Enter an invalidation reason first.'); return; }
    setPackBusy(true); setPackError(null);
    try {
      const pack = await client<ContextPackVersion>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-packs/${version.pack_key}/versions/${version.version}/invalidate`, { method: 'POST', body: JSON.stringify({ reason }) });
      setSelectedPack(pack); setPackComment(''); await refreshContextPacks();
    } catch (err) { setPackError(String(err)); }
    finally { setPackBusy(false); }
  }

  async function generateSkillExport() {
    if (!selectedPack || selectedPack.status !== 'published') { setSkillExportError('Select a published Context Pack version first.'); return; }
    setSkillExportBusy(true); setSkillExportError(null);
    try {
      const exported = await client<SkillExport>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/context-packs/${selectedPack.pack_key}/versions/${selectedPack.version}/skill-exports`, { method: 'POST', body: JSON.stringify({ export_type: 'hermes_skill', title: `${selectedPack.title} runtime skill`, summary: `Generated from ${selectedPack.pack_key} v${selectedPack.version}` }) });
      setSelectedSkillExport(exported);
      await refreshSkillExports(selectedPack);
    } catch (err) { setSkillExportError(String(err)); }
    finally { setSkillExportBusy(false); }
  }

  async function approveSkillExport() {
    if (!selectedSkillExport) return;
    const comment = skillExportComment.trim();
    if (!comment) { setSkillExportError('Enter an approval comment first.'); return; }
    setSkillExportBusy(true); setSkillExportError(null);
    try {
      const exported = await client<SkillExport>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/skill-exports/${selectedSkillExport.id}/approve`, { method: 'POST', body: JSON.stringify({ comment }) });
      setSelectedSkillExport(exported); setSkillExportComment(''); await refreshSkillExports(selectedPack);
    } catch (err) { setSkillExportError(String(err)); }
    finally { setSkillExportBusy(false); }
  }

  async function rejectSkillExport() {
    if (!selectedSkillExport) return;
    const reason = skillExportComment.trim();
    if (!reason) { setSkillExportError('Enter a rejection reason first.'); return; }
    setSkillExportBusy(true); setSkillExportError(null);
    try {
      const exported = await client<SkillExport>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/skill-exports/${selectedSkillExport.id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
      setSelectedSkillExport(exported); setSkillExportComment(''); await refreshSkillExports(selectedPack);
    } catch (err) { setSkillExportError(String(err)); }
    finally { setSkillExportBusy(false); }
  }

  async function invalidateSkillExport() {
    if (!selectedSkillExport) return;
    const reason = skillExportComment.trim();
    if (!reason) { setSkillExportError('Enter an invalidation/scrub reason first.'); return; }
    setSkillExportBusy(true); setSkillExportError(null);
    try {
      const exported = await client<SkillExport>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/skill-exports/${selectedSkillExport.id}/invalidate`, { method: 'POST', body: JSON.stringify({ reason }) });
      setSelectedSkillExport(exported); setSkillExportComment(''); await refreshSkillExports(selectedPack);
    } catch (err) { setSkillExportError(String(err)); }
    finally { setSkillExportBusy(false); }
  }

  async function downloadSkillExportFile(filePath: string) {
    if (!selectedSkillExport) return;
    setSkillExportBusy(true); setSkillExportError(null);
    try {
      const blob = await apiFetchBlob(settings, `/workspaces/${settings.workspaceId}/projects/${settings.projectId}/skill-exports/${selectedSkillExport.id}/files/${encodeURIComponent(filePath)}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filePath.split('/').pop() || filePath;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) { setSkillExportError(String(err)); }
    finally { setSkillExportBusy(false); }
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
  const selectedPackSummary = selectedPack ? contextPacks.find((pack) => pack.pack_key === selectedPack.pack_key) : undefined;
  const currentPack = selectedPackSummary?.current ?? null;
  const rollbackImpact = selectedPack && currentPack && selectedPack.status === 'superseded'
    ? {
        addedArtifacts: selectedPack.artifacts.filter((artifact) => !currentPack.artifacts.some((current) => current.context_artifact_id === artifact.context_artifact_id)).length,
        removedArtifacts: currentPack.artifacts.filter((artifact) => !selectedPack.artifacts.some((target) => target.context_artifact_id === artifact.context_artifact_id)).length,
        addedResources: selectedPack.coverage.filter((row) => !currentPack.coverage.some((current) => current.resource_id === row.resource_id)).length,
        removedResources: currentPack.coverage.filter((row) => !selectedPack.coverage.some((target) => target.resource_id === row.resource_id)).length,
        addedSnapshots: selectedPack.coverage.filter((row) => !currentPack.coverage.some((current) => current.source_snapshot_id === row.source_snapshot_id)).length,
        removedSnapshots: currentPack.coverage.filter((row) => !selectedPack.coverage.some((target) => target.source_snapshot_id === row.source_snapshot_id)).length,
      }
    : null;
  const selectedPackIssues = selectedPack ? [...(selectedPack.validation_json?.errors ?? []), ...(selectedPack.validation_json?.warnings ?? [])] : [];
  const selectedSkillExportFile = selectedSkillExport?.files.find((file) => file.path === selectedSkillExportFilePath) ?? selectedSkillExport?.files[0] ?? null;
  const skillExportManifest = (selectedSkillExport?.manifest_json ?? {}) as Record<string, unknown>;
  const skillExportCoverage = (skillExportManifest.coverage ?? {}) as Record<string, unknown>;
  const skillExportGeneration = (skillExportManifest.generation ?? {}) as Record<string, unknown>;
  const skillExportProviderBoundary = (skillExportGeneration.provider_boundary ?? {}) as Record<string, unknown>;
  const skillExportInspirations = (skillExportManifest.reference_inspirations ?? {}) as Record<string, unknown>;
  const skillExportSmokeCount = Number(skillExportManifest.smoke_query_count ?? 0);
  const skillExportReferenceCount = selectedSkillExport?.files.filter((file) => file.path.startsWith('references/')).length ?? 0;
  const skillExportFileGroups = selectedSkillExport?.files.reduce<Record<string, typeof selectedSkillExport.files>>((groups, file) => {
    const group = file.path.includes('/') ? file.path.split('/')[0] : 'root';
    groups[group] = [...(groups[group] ?? []), file];
    return groups;
  }, {}) ?? {};
  const skillExportCoverageWarnings = selectedSkillExport
    ? [
        Number(skillExportCoverage.resources ?? 0) === 0 ? 'No resources covered by this package.' : null,
        Number(skillExportCoverage.artifacts ?? 0) === 0 ? 'No Context Artifacts were compiled into this package.' : null,
        Number(skillExportCoverage.citations ?? 0) === 0 ? 'No citations available; generated playbooks must refuse source-specific answers.' : null,
      ].filter(Boolean) as string[]
    : [];

  return <main className="page">
    <PageHeader
      eyebrow="Sources"
      title="Connected sources and lifecycle"
      description="Every context source from connect through indexing, review, and retrieval. Select a source to inspect its evidence and run maintenance in place."
      actions={<>
        <button type="button" className="btn" onClick={openConnectSource}>{connectOpen ? 'Close connect' : 'Connect source'}</button>
        <button type="button" className="btn secondary" onClick={useSampleMarkdown}>Use sample source</button>
        <button type="button" className="btn secondary" onClick={() => reload()} disabled={loading}>{loading ? 'Loading…' : 'Reload'}</button>
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

    <section className="card">
      <div className="section-card-head"><div><h2 className="section-card-title">Context Packs</h2><p className="muted section-card-desc">Published packs pin approved artifacts and source snapshots for runtime use. Operate by pack key and version — no UUID paste flow.</p></div><button className="btn secondary" disabled={packBusy} onClick={() => void refreshContextPacks()}>{packBusy ? 'Working…' : 'Reload packs'}</button></div>
      {packError ? <div className="notice error">{packError}</div> : null}
      <div className="grid two" style={{ marginTop: 12 }}>
        <div className="grid">
          {contextPacks.length === 0 ? <EmptyState text="No Context Packs yet. Select an approved Resource Map artifact, then create the default pack draft." /> : <div className="table-wrap"><table><thead><tr><th>Pack</th><th>Current</th><th>Latest</th><th>Artifacts</th><th>Action</th></tr></thead><tbody>{contextPacks.map((pack) => <tr key={pack.pack_key} className="clickable" onClick={() => setSelectedPack(pack.current ?? pack.latest)}><td><strong>{pack.pack_key}</strong><div className="muted">{pack.title}</div></td><td>{pack.current ? <span><StatusChip value={pack.current.status} /><div className="code">v{pack.current.version} · {short(pack.current.pack_hash)}</div></span> : <span className="muted">none</span>}</td><td>{pack.latest ? <span><StatusChip value={pack.latest.status} /><div className="code">v{pack.latest.version}</div></span> : <span className="muted">none</span>}</td><td>{pack.latest?.artifacts.length ?? 0}</td><td><button className="btn secondary" onClick={(event) => { event.stopPropagation(); setSelectedPack(pack.current ?? pack.latest); }}>Review</button></td></tr>)}</tbody></table></div>}
          {contextPacks.length ? <div><div className="label">Version history</div><div className="table-wrap"><table><thead><tr><th>Version</th><th>Status</th><th>Published</th><th>Reason</th><th>Action</th></tr></thead><tbody>{contextPacks.flatMap((pack) => pack.versions.map((version) => <tr key={`${pack.pack_key}-${version.version}`} className="clickable" onClick={() => setSelectedPack(version)}><td><strong>{pack.pack_key} v{version.version}</strong><div className="code">{short(version.pack_hash)}</div></td><td><StatusChip value={version.status} /></td><td>{fmt(version.published_at)}</td><td>{version.status_reason || <span className="muted">—</span>}</td><td><button className="btn secondary" onClick={(event) => { event.stopPropagation(); setSelectedPack(version); }}>Review version</button></td></tr>))}</tbody></table></div></div> : null}
        </div>
        <div className="grid">
          <div className="grid two"><button className="btn" disabled={packBusy || packArtifactIds.length === 0} onClick={() => void createPackDraft()}>Create default draft from selected artifacts</button><Field label="Publish / rollback / invalidate comment"><input className="input" value={packComment} onChange={(event) => setPackComment(event.target.value)} placeholder="Required for release actions" /></Field></div>{contextArtifacts.some((artifact) => artifact.status === 'approved') ? <div><div className="label">Approved artifacts for draft composition</div><div className="grid">{contextArtifacts.filter((artifact) => artifact.status === 'approved').map((artifact) => <label key={artifact.id} className={`scope-pill ${packArtifactIds.includes(artifact.id) ? 'active' : ''}`}><input type="checkbox" checked={packArtifactIds.includes(artifact.id)} onChange={(event) => setPackArtifactIds((ids) => event.target.checked ? Array.from(new Set([...ids, artifact.id])) : ids.filter((id) => id !== artifact.id))} /> {artifact.title} · {short(artifact.artifact_hash)}</label>)}</div></div> : <div className="empty">Approve one or more Resource Map artifacts to compose a Context Pack draft.</div>}
          {selectedPack ? <div className="notice"><div className="section-card-head"><div><strong>{selectedPack.pack_key} v{selectedPack.version}</strong><div className="muted">{short(selectedPack.pack_hash)} · created {fmt(selectedPack.created_at)}</div></div><StatusChip value={selectedPack.status} /></div>{selectedPack.status === 'published' ? <div className="notice error" style={{ marginTop: 8 }}>Invalidating this published version removes the current runtime pack until another version is published or rolled back.</div> : null}<div className="grid three" style={{ marginTop: 8 }}><Metric label="Artifacts" value={selectedPack.artifacts.length} /><Metric label="Resources" value={selectedPack.coverage.length} /><Metric label="Validation" value={selectedPack.validation_json?.ok === false ? 'failed' : 'ok'} /></div>{selectedPackIssues.length ? <div className="notice error" style={{ marginTop: 8 }}><strong>Validation findings</strong>{selectedPackIssues.map((issue, idx) => <div key={idx} className="muted">{String(issue.code ?? 'validation')}: {String(issue.message ?? JSON.stringify(issue))}</div>)}</div> : null}{rollbackImpact ? <div className="notice" style={{ marginTop: 8 }}><strong>Rollback impact current → v{selectedPack.version}</strong><div className="grid three" style={{ marginTop: 8 }}><Metric label="Artifact delta" value={`+${rollbackImpact.addedArtifacts} / -${rollbackImpact.removedArtifacts}`} /><Metric label="Resource delta" value={`+${rollbackImpact.addedResources} / -${rollbackImpact.removedResources}`} /><Metric label="Snapshot delta" value={`+${rollbackImpact.addedSnapshots} / -${rollbackImpact.removedSnapshots}`} /></div></div> : null}<div className="toolbar" style={{ marginTop: 8 }}><button className="btn" disabled={packBusy || selectedPack.status !== 'draft'} onClick={() => void publishPack()}>Publish draft</button><button className="btn secondary" disabled={packBusy || selectedPack.status !== 'superseded'} onClick={() => void rollbackPack(selectedPack)}>Rollback to this version</button><button className="btn secondary" disabled={packBusy || selectedPack.status === 'invalidated'} onClick={() => void invalidatePack(selectedPack)}>{selectedPack.status === 'published' ? 'Invalidate current pack' : 'Invalidate'}</button></div>{selectedPack.coverage.length ? <div className="table-wrap" style={{ marginTop: 8 }}><table><thead><tr><th>Resource</th><th>Snapshot</th><th>Artifacts</th><th>Citations</th></tr></thead><tbody>{selectedPack.coverage.slice(0, 6).map((row) => <tr key={row.id}><td><strong>{row.resource_name || row.source_family_label || short(row.resource_id)}</strong></td><td><span className="code">{short(row.source_snapshot_id)}</span></td><td>{row.artifact_count}</td><td>{row.citation_count}</td></tr>)}</tbody></table></div> : null}{selectedPack.artifacts.length ? <div className="table-wrap" style={{ marginTop: 8 }}><table><thead><tr><th>Artifact</th><th>Resource</th><th>Status</th><th>Citations</th></tr></thead><tbody>{selectedPack.artifacts.slice(0, 6).map((artifact) => <tr key={artifact.id}><td><strong>{artifact.artifact_title || artifact.artifact_type}</strong><div className="code">{short(artifact.artifact_hash)}</div></td><td>{artifact.resource_name || short(artifact.resource_id)}</td><td><StatusChip value={artifact.artifact_status || 'artifact'} /></td><td>{artifact.citations.slice(0, 4).map((citation) => <div key={citation.id}><span className="code">{citation.normalized_path}</span>{citation.title ? <span className="muted"> · {citation.title}</span> : null}{citation.line_start ? <span className="muted"> · L{citation.line_start}{citation.line_end ? `-${citation.line_end}` : ''}</span> : null}</div>)}</td></tr>)}</tbody></table></div> : null}</div> : <div className="empty">Select a pack version to review coverage and publish state. Runtime only uses published packs.</div>}
        </div>
      </div>
    </section>


    <section className="card">
      <div className="section-card-head"><div><h2 className="section-card-title">Skill Export</h2><p className="muted section-card-desc">Compile reviewable Skill Packs from approved published Context Packs: references, task playbooks, smoke queries, checksums, and SourceBrief citation policy. Drafts are preview-only; download/copy requires approval.</p></div><button className="btn secondary" disabled={skillExportBusy || !selectedPack} onClick={() => void refreshSkillExports(selectedPack)}>Reload exports</button></div>
      {skillExportError ? <div className="notice error">{skillExportError}</div> : null}
      <div className="grid two" style={{ marginTop: 12 }}>
        <div className="grid">
          <button className="btn" disabled={skillExportBusy || selectedPack?.status !== 'published'} onClick={() => void generateSkillExport()}>Compile Hermes Skill Pack</button>
          {skillExports.length ? <div className="table-wrap"><table><thead><tr><th>Export</th><th>Status</th><th>Hash</th><th>Action</th></tr></thead><tbody>{skillExports.map((item) => <tr key={item.id} className="clickable" onClick={() => setSelectedSkillExport(item)}><td><strong>{item.title}</strong><div className="muted">v{item.export_version} · {item.export_type}</div></td><td><StatusChip value={item.status} /></td><td><span className="code">{short(item.package_hash)}</span></td><td><button className="btn secondary" onClick={(event) => { event.stopPropagation(); setSelectedSkillExport(item); }}>Review export</button></td></tr>)}</tbody></table></div> : <div className="empty">Select a published pack version, then generate a Hermes skill export.</div>}
        </div>
        <div className="grid">
          {selectedSkillExport ? <div className="notice"><div className="section-card-head"><div><strong>{selectedSkillExport.title}</strong><div className="muted">{selectedSkillExport.pack_key} v{selectedSkillExport.pack_version} · {short(selectedSkillExport.package_hash)}</div></div><StatusChip value={selectedSkillExport.status} /></div>{selectedSkillExport.status !== 'approved' ? <div className="notice error" style={{ marginTop: 8 }}>Approval required before installing, copying, or downloading this Skill Pack. Drafts are preview-only.</div> : null}<div className="grid three" style={{ marginTop: 8 }}><Metric label="Files" value={selectedSkillExport.files.length} /><Metric label="References" value={skillExportReferenceCount} /><Metric label="Smoke queries" value={skillExportSmokeCount || '—'} /></div><div className="grid three" style={{ marginTop: 8 }}><Metric label="Resources" value={Number(skillExportCoverage.resources ?? 0)} /><Metric label="Artifacts" value={Number(skillExportCoverage.artifacts ?? 0)} /><Metric label="Citations" value={Number(skillExportCoverage.citations ?? 0)} /></div><div className="grid three" style={{ marginTop: 8 }}><Metric label="Validation" value={selectedSkillExport.validation_json?.ok === false ? 'failed' : 'ok'} /><Metric label="Leak scan" value={selectedSkillExport.leak_scan_json?.ok === false ? 'failed' : 'ok'} /><Metric label="Generation" value={String(skillExportGeneration.mode ?? 'deterministic')} hint={`provider boundary: ${String(skillExportProviderBoundary.future_mode ?? 'section-aware map-reduce')}`} /></div>{Object.keys(skillExportInspirations).length ? <div className="notice" style={{ marginTop: 8 }}><strong>Reference inspirations implemented</strong><div className="grid two" style={{ marginTop: 8 }}>{Object.entries(skillExportInspirations).map(([name, features]) => <div key={name}><div className="label">{name}</div><div className="muted">{Array.isArray(features) ? features.join('; ') : String(features)}</div></div>)}</div></div> : null}{skillExportCoverageWarnings.length ? <div className="notice error" style={{ marginTop: 8 }}><strong>Coverage warnings</strong>{skillExportCoverageWarnings.map((warning, idx) => <div key={idx} className="muted">{warning}</div>)}</div> : null}{selectedSkillExport.leak_scan_json?.findings?.length ? <div className="notice error" style={{ marginTop: 8 }}><strong>Leak scan findings</strong>{selectedSkillExport.leak_scan_json.findings.map((finding, idx) => <div key={idx} className="muted">{String(finding.code ?? 'finding')}: {String(finding.message ?? JSON.stringify(finding))}</div>)}</div> : null}<Field label="Skill Pack review comment / reason"><input className="input" value={skillExportComment} onChange={(event) => setSkillExportComment(event.target.value)} placeholder="Required for approve / reject / invalidate" /></Field><div className="toolbar" style={{ marginTop: 8 }}><button className="btn" disabled={skillExportBusy || selectedSkillExport.status !== 'draft'} onClick={() => void approveSkillExport()}>Approve pack</button><button className="btn secondary" disabled={skillExportBusy || !['draft','failed'].includes(selectedSkillExport.status)} onClick={() => void rejectSkillExport()}>Reject</button><button className="btn secondary" disabled={skillExportBusy || selectedSkillExport.status === 'invalidated'} onClick={() => void invalidateSkillExport()}>Invalidate / scrub</button></div>{selectedSkillExport.files.length ? <div className="grid" style={{ marginTop: 8 }}>{Object.entries(skillExportFileGroups).map(([group, files]) => <div key={group}><div className="label">{group === 'root' ? 'package root' : group}</div><div className="table-wrap" style={{ marginTop: 6 }}><table><thead><tr><th>File</th><th>Bytes</th><th>Hash</th><th>Install</th></tr></thead><tbody>{files.map((file) => <tr key={file.path} className="clickable" onClick={() => setSelectedSkillExportFilePath(file.path)}><td><strong>{file.path}</strong><div className="muted">{file.kind}</div></td><td>{file.bytes}</td><td><span className="code">{short(file.sha256)}</span></td><td>{selectedSkillExport.status === 'approved' ? <button className="btn secondary" onClick={(event) => { event.stopPropagation(); void downloadSkillExportFile(file.path); }}>Download</button> : <span className="muted">preview only</span>}</td></tr>)}</tbody></table></div></div>)}</div> : null}{selectedSkillExportFile?.content ? <div><div className="label">Preview: {selectedSkillExportFile.path}</div><pre className="code-block" style={{ maxHeight: 280, overflow: 'auto' }}>{selectedSkillExportFile.content}</pre></div> : <div className="empty">No generated file content retained. Failed or invalidated exports are scrubbed.</div>}</div> : <div className="empty">Select an export to review Skill Pack files, validation, leak scan, coverage, and smoke queries.</div>}
        </div>
      </div>
    </section>
    {connectOpen ? <section className="card connect-panel">
      <div className="section-card-head"><div><h2 className="section-card-title">Connect a source</h2><p className="muted section-card-desc">Pick a source type — only the fields it needs are shown. New sources appear in the list and are selected automatically.</p></div><button type="button" className="btn secondary" onClick={useSampleMarkdown}>Fill sample Markdown</button></div>
      <form className="grid two" aria-label="Connect source form" onSubmit={submitConnect}>
        <div className="grid">
          <Field label="Source type"><select className="input" value={type} onChange={(event) => changeType(event.target.value as ResourceType)}><option value="git">Git repository</option><option value="folder_bundle">Folder bundle (.zip)</option><option value="url">URL / web page</option><option value="markdown">Markdown / inline doc</option><option value="upload">Upload text</option></select></Field>
          {supersedesResourceId ? <div className="notice">Uploading a new version of {name}. SourceBrief keeps the same family label and compares it to the previous manifest.</div> : <Field label="Name"><input className="input" value={name} onChange={(event) => setName(event.target.value)} /></Field>}
          {type !== 'folder_bundle' ? <Field label={type === 'git' ? 'Git URL' : type === 'url' ? 'URL' : 'URI / path'}><input className="input" value={uri} onChange={(event) => setUri(event.target.value)} /></Field> : null}
          {type === 'git' ? <div className="grid two"><Field label="Branch"><input className="input" value={branch} onChange={(event) => setBranch(event.target.value)} /></Field></div> : null}
          {type === 'folder_bundle' ? <Field label="Folder bundle zip"><input className="input" type="file" accept=".zip,application/zip" onChange={(event) => setZipFile(event.target.files?.[0] ?? null)} /><div className="muted">Upload a zipped folder. SourceBrief validates paths and archives before indexing.</div></Field> : null}
          {type === 'upload' ? <Field label="Filename"><input className="input" value={filename} onChange={(event) => setFilename(event.target.value)} /></Field> : null}
          {type === 'markdown' || type === 'upload' ? <Field label="Content"><textarea className="input" rows={8} value={content} onChange={(event) => setContent(event.target.value)} /></Field> : null}
          {type === 'folder_bundle'
            ? <div className="notice">Folder bundles are updated manually. Upload a new zip when the folder changes.</div>
            : <div className="grid two"><Field label="Update frequency"><select className="input" value={frequency} onChange={(event) => setFrequency(event.target.value)}><option value="manual">manual</option><option value="hourly">hourly</option><option value="daily">daily</option><option value="weekly">weekly</option></select></Field><label className={`scope-pill ${refreshNow ? 'active' : ''}`}><input type="checkbox" checked={refreshNow} onChange={(event) => setRefreshNow(event.target.checked)} /> Create index immediately</label></div>}
          <button type="submit" className="btn" disabled={connectBusy}>{connectBusy ? 'Connecting…' : 'Connect source'}</button>
        </div>
        <div className="grid">
          {connectError ? <div className="notice error">{connectError}</div> : null}
          {connectResult ? <div className="notice"><strong>Source connected.</strong><div className="muted">{refreshNow ? 'Indexing has started; watch Index activity for queued/running/succeeded status.' : 'Indexing was not started yet; run Reindex when you are ready.'}</div><div style={{ marginTop: 8 }}><strong>{connectResult.name}</strong> is selected in the list.</div><div className="toolbar" style={{ marginTop: 8 }}><button type="button" className="btn secondary" onClick={() => void previewSelected()} disabled={previewBusy}>{previewBusy ? 'Generating…' : 'Preview this source'}</button><a className="btn secondary" href="/workbench">Ask in Workbench</a></div></div> : <div className="empty">Connected sources are added to the list and indexed when requested. For a deterministic first run, use “Fill sample Markdown”, connect it, then preview or ask it in Workbench.</div>}
        </div>
      </form>
    </section> : null}

    <div className="grid two">
      <SectionCard title="Sources" description="Attention-first: failed, stale, not indexed, and unreviewed sources lead.">
        {sortedResources.length === 0
          ? <div className="grid"><EmptyState text="No sources connected yet. Use the sample Markdown to prove the full connect → index → cited context flow, or connect your own git repo, URL, or document." /><div className="toolbar"><button type="button" className="btn" onClick={openConnectSource}>Connect source</button><button type="button" className="btn secondary" onClick={useSampleMarkdown}>Use sample source</button></div></div>
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
                  <td>
                    <strong>{resource.source_family_label || resource.name}</strong>
                    {resource.version_label ? <div className="muted">{resource.version_label}</div> : null}
                    <div className="toolbar" style={{ gap: 6, marginTop: 4 }}>
                      <Chip>{resource.type}</Chip>
                      {resource.coverage_status ? <StatusChip value={resource.coverage_status} /> : null}
                      {resource.status !== 'active' ? <StatusChip value={resource.status} /> : null}
                    </div>
                    {resource.coverage_warnings?.length ? <div className="muted" style={{ color: 'var(--risk)', marginTop: 4 }}>{resource.coverage_warnings[0]}</div> : null}
                  </td>
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
              <div><div className="label">Retrieval</div><Chip tone={selectedResource.queryable ? 'ready' : selectedResource.retrieval_enabled ? 'warn' : 'warn'}>{selectedResource.queryable ? 'queryable' : selectedResource.retrieval_enabled ? 'not queryable' : 'off'}</Chip></div>
            </div>
            {selectedResource.coverage_warnings?.length ? <div className="notice error"><strong>Coverage warning</strong>{selectedResource.coverage_warnings.map((warning, index) => <div key={index} className="muted">{warning}</div>)}{selectedReview?.last_index_error_message ? <div className="muted">Last index error: {selectedReview.last_index_error_message}</div> : null}</div> : null}
            {selectedResource.coverage_status === 'partial' ? <div className="notice"><strong>Partial import budget</strong><div className="muted">{Object.entries(selectedResource.index_diagnostics?.configured_budgets ?? {}).map(([key, value]) => `${key}=${value}`).join(', ') || 'limited import profile'}</div></div> : null}
            <div><div className="label">Source location</div><div className="muted">{selectedResource.uri}</div></div>
            {selectedResource.type === 'folder_bundle' ? <div className="notice">
              <strong>Folder manifest</strong>
              {manifest ? <div className="grid three" style={{ marginTop: 8 }}>
                <Metric label="Files" value={manifest.file_count} />
                <Metric label="Sections" value={manifest.section_count} hint={`${manifest.sections_reused_count} reused / ${manifest.sections_extracted_count} extracted`} />
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
            {selectedResource.type === 'folder_bundle' ? <div className="notice">
              <strong>Section reuse and impact</strong>
              {sectionImpact ? <div className="grid three" style={{ marginTop: 8 }}>
                <Metric label="Deleted-file sections" value={sectionImpact.sections_from_deleted_files_count} />
                <Metric label="Absent sections" value={sectionImpact.sections_absent_count} />
                <Metric label="Artifact impact" value={sectionImpact.impacted_artifacts_known ? 'known' : 'not calculated'} />
              </div> : <div className="muted" style={{ marginTop: 8 }}>{sectionImpactError ? `Section impact unavailable: ${sectionImpactError}` : 'Section impact will appear after indexing.'}</div>}
              {sectionImpact ? <div className="muted" style={{ marginTop: 6 }}>{sectionImpact.message}</div> : null}
              {snapshotSections ? <>
                <div className="muted" style={{ marginTop: 6 }}>Showing {snapshotSections.row_count_returned.toLocaleString()} of {snapshotSections.total_row_count.toLocaleString()} extracted/reused sections.</div>
                <div className="table-wrap" style={{ marginTop: 8 }}><table><thead><tr><th>Path</th><th>Title</th><th>Reuse</th><th>Preview</th></tr></thead><tbody>{snapshotSections.rows.map((row) => <tr key={row.id}><td><span className="code">{row.normalized_path}</span><div className="muted">L{row.start_line ?? '—'}-{row.end_line ?? '—'}</div></td><td>{row.title || <span className="muted">Untitled</span>}</td><td><StatusChip value={row.reuse_status} /></td><td>{row.content_preview}</td></tr>)}</tbody></table></div>
                {snapshotSections.next_cursor ? <button className="btn secondary" style={{ marginTop: 8 }} onClick={() => setSnapshotSectionsLimit((value) => value + 25)}>Show more sections</button> : null}
              </> : snapshotSectionsError ? <div className="notice error" style={{ marginTop: 8 }}>Snapshot sections unavailable: {snapshotSectionsError}</div> : <div className="muted" style={{ marginTop: 8 }}>Sections will appear after indexing.</div>}
            </div> : null}
            {selectedResource.type === 'folder_bundle' ? <div className="notice">
              <div className="section-card-head"><div><strong>Resource Map artifact</strong><div className="muted section-card-desc">Deterministic source map for agent/runtime review. Compile creates a draft; approval is explicit.</div></div><button className="btn secondary" disabled={artifactBusy || !manifest} onClick={() => void compileResourceMap(selectedArtifact?.status === 'failed')}>{artifactBusy ? 'Working…' : selectedArtifact?.status === 'failed' ? 'Retry compile' : selectedArtifact ? 'Recompile map' : 'Compile map'}</button></div>
              {artifactError ? <div className="notice error" style={{ marginTop: 8 }}>{artifactError}</div> : null}
              {selectedArtifact ? <>
                <div className="grid four" style={{ marginTop: 8 }}>
                  <Metric label="Status" value={<StatusChip value={selectedArtifact.status} />} />
                  <Metric label="Revision" value={selectedArtifact.artifact_revision} />
                  <Metric label="Sources" value={numberMetric(selectedArtifact.coverage_json, 'source_count', selectedArtifact.sources.length)} />
                  <Metric label="Citations" value={numberMetric(selectedArtifact.coverage_json, 'citation_count', selectedArtifact.citations.length)} />
                </div>
                <div className="grid four" style={{ marginTop: 8 }}>
                  <Metric label="Hash" value={<span className="code">{short(selectedArtifact.artifact_hash)}</span>} />
                  <Metric label="Compiled" value={fmt(selectedArtifact.created_at)} />
                  <Metric label="Validation" value={selectedArtifact.validation_json?.ok === false ? 'failed' : 'ok'} />
                  <Metric label="Warnings" value={selectedArtifact.validation_json?.warnings?.length ?? 0} />
                </div>
                {selectedArtifact.error_message ? <div className="notice error" style={{ marginTop: 8 }}>{selectedArtifact.error_message}</div> : null}
                {selectedArtifact.validation_json?.errors?.length ? <div className="notice error" style={{ marginTop: 8 }}>{selectedArtifact.validation_json.errors.map((error, index) => <div key={index}>{String(error.message ?? 'Validation error')}</div>)}</div> : null}
                <div className="muted" style={{ marginTop: 6 }}>{selectedArtifact.summary || 'Resource Map is ready for review.'}</div>
                {selectedArtifact.validation_json?.warnings?.length ? <label className={`scope-pill ${ackArtifactWarnings ? 'active' : ''}`} style={{ marginTop: 8 }}><input type="checkbox" checked={ackArtifactWarnings} onChange={(event) => setAckArtifactWarnings(event.target.checked)} /> I reviewed and acknowledge {selectedArtifact.validation_json.warnings.length} Resource Map warning(s)</label> : null}
                <Field label="Reject reason"><input className="input" value={rejectArtifactReason} onChange={(event) => setRejectArtifactReason(event.target.value)} placeholder="Required only when rejecting" /></Field>
                <div className="toolbar" style={{ marginTop: 8 }}>
                  <button className="btn" disabled={artifactBusy || selectedArtifact.status !== 'draft' || Boolean(selectedArtifact.validation_json?.warnings?.length && !ackArtifactWarnings)} onClick={() => void approveArtifact()}>Approve artifact</button>
                  <button className="btn secondary" disabled={artifactBusy || selectedArtifact.status !== 'draft'} onClick={() => void rejectArtifact()}>Reject</button>
                </div>
                <div className="muted" style={{ marginTop: 8 }}>Showing {Math.min(artifactSourceLimit, selectedArtifact.sources.length)} of {selectedArtifact.sources.length} source rows.</div>
                <div className="table-wrap" style={{ marginTop: 8 }}><table><thead><tr><th>Path</th><th>Coverage</th><th>Sections</th><th>Status</th></tr></thead><tbody>{selectedArtifact.sources.slice(0, artifactSourceLimit).map((source) => <tr key={source.id}><td><span className="code">{source.normalized_path}</span></td><td>{source.coverage_status}</td><td>{source.section_count}</td><td><StatusChip value={source.status} /></td></tr>)}</tbody></table></div>
                {artifactSourceLimit < selectedArtifact.sources.length ? <button className="btn secondary" style={{ marginTop: 8 }} onClick={() => setArtifactSourceLimit((value) => value + 25)}>Show more source rows</button> : null}
                <div className="muted" style={{ marginTop: 8 }}>Showing {Math.min(artifactCitationLimit, selectedArtifact.citations.length)} of {selectedArtifact.citations.length} citation rows.</div>
                <div className="table-wrap" style={{ marginTop: 8 }}><table><thead><tr><th>Path</th><th>Title</th><th>Lines</th><th>Hash</th></tr></thead><tbody>{selectedArtifact.citations.slice(0, artifactCitationLimit).map((citation) => <tr key={citation.id}><td><span className="code">{citation.normalized_path}</span></td><td>{citation.title || <span className="muted">Untitled</span>}</td><td>{citation.line_start ?? '—'}-{citation.line_end ?? '—'}</td><td><span className="code">{short(citation.content_hash)}</span></td></tr>)}</tbody></table></div>
                {artifactCitationLimit < selectedArtifact.citations.length ? <button className="btn secondary" style={{ marginTop: 8 }} onClick={() => setArtifactCitationLimit((value) => value + 25)}>Show more citation rows</button> : null}
              </> : <div className="muted" style={{ marginTop: 8 }}>{contextArtifacts.length ? 'Select a Resource Map artifact to inspect it.' : 'No Resource Map artifact compiled yet.'}</div>}
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
