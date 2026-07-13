'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { PageHeader, Card, Field, EmptyState } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import type { GitResourceEnv } from '../../lib/types';

type GitDraft = { branch: string; auth_token_env: string; clone_timeout: string; max_file_bytes: string; max_repo_files: string; max_repo_bytes: string; max_chunks: string; max_symbols: string; update_frequency: string };

function toGitDraft(env: GitResourceEnv | null): GitDraft {
  return {
    branch: env?.branch ?? '',
    auth_token_env: env?.auth_token_env ?? '',
    clone_timeout: env?.clone_timeout?.toString() ?? '',
    max_file_bytes: env?.max_file_bytes?.toString() ?? '',
    max_repo_files: env?.max_repo_files?.toString() ?? '',
    max_repo_bytes: env?.max_repo_bytes?.toString() ?? '',
    max_chunks: env?.max_chunks?.toString() ?? '',
    max_symbols: env?.max_symbols?.toString() ?? '',
    update_frequency: env?.update_frequency ?? 'daily',
  };
}

function optionalPositiveInteger(value: string, label: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (!Number.isSafeInteger(parsed) || parsed < 1) throw new Error(`${label} must be a positive whole number.`);
  return parsed;
}

export default function ConfigPage() {
  const { settings, workspaces, projectsByWorkspace, workspace, project, resources, client, reload, chooseScope } = usePlatform();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(settings.workspaceId);
  const [selectedProjectId, setSelectedProjectId] = useState(settings.projectId);
  const [gitEnvs, setGitEnvs] = useState<GitResourceEnv[]>([]);
  const [selectedGitResourceId, setSelectedGitResourceId] = useState('');
  const selectedGitEnv = useMemo(() => gitEnvs.find((env) => env.resource_id === selectedGitResourceId) ?? gitEnvs[0] ?? null, [gitEnvs, selectedGitResourceId]);
  const [gitDraft, setGitDraft] = useState<GitDraft>(toGitDraft(null));
  const [gitBusy, setGitBusy] = useState(false);
  const [gitError, setGitError] = useState<string | null>(null);
  const [gitSaved, setGitSaved] = useState(false);
  const availableProjects = useMemo(() => projectsByWorkspace[selectedWorkspaceId] ?? [], [projectsByWorkspace, selectedWorkspaceId]);

  useEffect(() => { setSelectedWorkspaceId(settings.workspaceId); setSelectedProjectId(settings.projectId); }, [settings.workspaceId, settings.projectId]);
  useEffect(() => {
    if (!availableProjects.some((item) => item.id === selectedProjectId)) setSelectedProjectId(availableProjects[0]?.id ?? '');
  }, [availableProjects, selectedProjectId]);
  useEffect(() => {
    if (!settings.workspaceId || !settings.projectId || !settings.sessionToken) return;
    setGitError(null);
    void client<GitResourceEnv[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/git-env`)
      .then((rows) => { setGitEnvs(rows); setSelectedGitResourceId((current) => current && rows.some((row) => row.resource_id === current) ? current : rows[0]?.resource_id ?? ''); })
      .catch((err) => setGitError(String(err)));
  }, [client, settings.workspaceId, settings.projectId, settings.sessionToken]);
  useEffect(() => { setGitDraft(toGitDraft(selectedGitEnv)); }, [selectedGitEnv]);

  async function saveScope(event: FormEvent) {
    event.preventDefault();
    const next = chooseScope(selectedWorkspaceId, selectedProjectId);
    await reload(next);
  }

  async function saveGitSettings(event: FormEvent) {
    event.preventDefault();
    if (!selectedGitEnv) return;
    setGitBusy(true); setGitError(null); setGitSaved(false);
    try {
      const updated = await client<GitResourceEnv>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedGitEnv.resource_id}/git-env`, {
        method: 'PATCH',
        body: JSON.stringify({
          branch: gitDraft.branch.trim() || null,
          auth_token_env: gitDraft.auth_token_env.trim() || null,
          clone_timeout: optionalPositiveInteger(gitDraft.clone_timeout, 'Clone timeout'),
          max_file_bytes: optionalPositiveInteger(gitDraft.max_file_bytes, 'Max file bytes'),
          max_repo_files: optionalPositiveInteger(gitDraft.max_repo_files, 'Max repo files'),
          max_repo_bytes: optionalPositiveInteger(gitDraft.max_repo_bytes, 'Max repo bytes'),
          max_chunks: optionalPositiveInteger(gitDraft.max_chunks, 'Max chunks'),
          max_symbols: optionalPositiveInteger(gitDraft.max_symbols, 'Max symbols'),
          update_frequency: gitDraft.update_frequency,
        }),
      });
      setGitEnvs((rows) => rows.map((row) => row.resource_id === updated.resource_id ? updated : row));
      setGitDraft(toGitDraft(updated));
      await reload().catch(() => undefined);
      setGitSaved(true);
    } catch (err) { setGitError(String(err)); }
    finally { setGitBusy(false); }
  }

  return <main className="page"><PageHeader eyebrow="Settings" title="Workspace settings" description="Choose workspace/project and tune each Git source's indexing settings. Source creation/review stays in Sources; Git indexing limits live here." />
    <div className="grid two"><Card><h2>Workspace and project</h2><p className="muted">Pick the active workspace and project by name.</p><form className="grid" onSubmit={saveScope}><Field label="Workspace"><select className="input" value={selectedWorkspaceId} onChange={(event) => setSelectedWorkspaceId(event.target.value)}>{workspaces.length === 0 ? <option value={settings.workspaceId}>{workspace?.name ?? 'No workspace loaded'}</option> : workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="Project"><select className="input" value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}>{availableProjects.length === 0 ? <option value={settings.projectId}>{project?.name ?? 'No project loaded'}</option> : availableProjects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><button type="submit" className="btn" disabled={!selectedWorkspaceId || !selectedProjectId}>Save workspace</button></form></Card>
    <Card><h2>Source lifecycle</h2><p className="muted">Use Sources for connecting, indexing, previewing, and asking cited questions. Use Settings for cross-cutting Git indexing knobs.</p><div className="notice"><strong>Canonical path</strong><div className="muted">Sources → Connect/inspect source → Quality review → Repo Agents only when packaging runtime contracts</div></div><div className="toolbar" style={{ marginTop: 12 }}><Link className="btn" href="/sources">Open Sources</Link><Link className="btn secondary" href="/workbench">Open Workbench</Link></div></Card></div>
    <Card><h2>Git indexing settings</h2><p className="muted">Settings for the selected Git source. SourceBrief stores environment variable names, never raw GitHub tokens. Save settings here, then reindex the source from Sources when you want the new limits applied.</p>{gitError ? <div className="notice error">{gitError}</div> : null}{gitSaved ? <div className="notice">Git settings saved.</div> : null}{gitEnvs.length === 0 ? <EmptyState text="No Git sources in this project." /> : <form className="grid" onSubmit={saveGitSettings}><Field label="Git source"><select className="input" value={selectedGitEnv?.resource_id ?? ''} onChange={(event) => { setSelectedGitResourceId(event.target.value); setGitSaved(false); }}>{gitEnvs.map((env) => <option key={env.resource_id} value={env.resource_id}>{env.name}</option>)}</select></Field><div className="grid two"><Field label="Git branch"><input className="input" value={gitDraft.branch} onChange={(event) => setGitDraft((draft) => ({ ...draft, branch: event.target.value }))} placeholder="main" /></Field><Field label="Git auth token env var"><input className="input" value={gitDraft.auth_token_env} onChange={(event) => setGitDraft((draft) => ({ ...draft, auth_token_env: event.target.value }))} placeholder="GITHUB_TOKEN_FOR_SOURCEBRIEF" /><div className="muted">Name of an env var available to API/worker. Do not paste the token value.</div></Field></div><div className="grid three"><Field label="Clone timeout seconds"><input className="input" inputMode="numeric" value={gitDraft.clone_timeout} onChange={(event) => setGitDraft((draft) => ({ ...draft, clone_timeout: event.target.value }))} placeholder="120" /></Field><Field label="Max file bytes"><input className="input" inputMode="numeric" value={gitDraft.max_file_bytes} onChange={(event) => setGitDraft((draft) => ({ ...draft, max_file_bytes: event.target.value }))} placeholder="10000000" /></Field><Field label="Max repo files"><input className="input" inputMode="numeric" value={gitDraft.max_repo_files} onChange={(event) => setGitDraft((draft) => ({ ...draft, max_repo_files: event.target.value }))} placeholder="5000" /></Field></div><div className="grid three"><Field label="Max repo bytes"><input className="input" inputMode="numeric" value={gitDraft.max_repo_bytes} onChange={(event) => setGitDraft((draft) => ({ ...draft, max_repo_bytes: event.target.value }))} placeholder="200000000" /></Field><Field label="Max chunks"><input className="input" inputMode="numeric" value={gitDraft.max_chunks} onChange={(event) => setGitDraft((draft) => ({ ...draft, max_chunks: event.target.value }))} placeholder="20000" /></Field><Field label="Max symbols"><input className="input" inputMode="numeric" value={gitDraft.max_symbols} onChange={(event) => setGitDraft((draft) => ({ ...draft, max_symbols: event.target.value }))} placeholder="20000" /></Field></div><Field label="Git update frequency"><select className="input" value={gitDraft.update_frequency} onChange={(event) => setGitDraft((draft) => ({ ...draft, update_frequency: event.target.value }))}><option value="manual">manual</option><option value="hourly">hourly</option><option value="daily">daily</option><option value="weekly">weekly</option></select></Field><button className="btn" disabled={gitBusy || !selectedGitEnv} type="submit">{gitBusy ? 'Saving…' : 'Save Git settings'}</button></form>}</Card>
  </main>;
}
