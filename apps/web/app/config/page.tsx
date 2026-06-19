'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, Field } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import type { Resource } from '../../lib/types';

export default function ConfigPage() {
  const { settings, workspaces, projectsByWorkspace, workspace, project, client, reload, chooseScope } = usePlatform();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(settings.workspaceId);
  const [selectedProjectId, setSelectedProjectId] = useState(settings.projectId);
  const availableProjects = useMemo(() => projectsByWorkspace[selectedWorkspaceId] ?? [], [projectsByWorkspace, selectedWorkspaceId]);
  const [resourceType, setResourceType] = useState<'git' | 'url' | 'markdown' | 'upload'>('git');
  const [resourceName, setResourceName] = useState('New source');
  const [resourceUri, setResourceUri] = useState('https://github.com/owner/repo.git');
  const [branch, setBranch] = useState('main');
  const [frequency, setFrequency] = useState('daily');
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { setSelectedWorkspaceId(settings.workspaceId); setSelectedProjectId(settings.projectId); }, [settings.workspaceId, settings.projectId]);
  useEffect(() => {
    if (!availableProjects.some((item) => item.id === selectedProjectId)) setSelectedProjectId(availableProjects[0]?.id ?? '');
  }, [availableProjects, selectedProjectId]);

  async function saveScope(event: FormEvent) {
    event.preventDefault();
    const next = chooseScope(selectedWorkspaceId, selectedProjectId);
    await reload(next);
  }

  async function addResource(event: FormEvent) {
    event.preventDefault(); setBusy(true);
    try {
      const source_config = resourceType === 'git' ? { url: resourceUri, branch } : resourceType === 'url' ? { url: resourceUri } : { content };
      await client<Resource>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources`, { method: 'POST', body: JSON.stringify({ type: resourceType, name: resourceName, uri: resourceUri, update_frequency: frequency, source_config }) });
      await reload();
    } finally { setBusy(false); }
  }

  return <main className="page"><PageHeader eyebrow="Settings" title="Workspace settings" description="Choose the active workspace/project and connect new context sources. Account access is managed from Team Access." />
    <div className="grid two"><Card><h2>Workspace and project</h2><p className="muted">Pick the active workspace and project by name.</p><form className="grid" onSubmit={saveScope}><Field label="Workspace"><select className="input" value={selectedWorkspaceId} onChange={(event) => setSelectedWorkspaceId(event.target.value)}>{workspaces.length === 0 ? <option value={settings.workspaceId}>{workspace?.name ?? 'No workspace loaded'}</option> : workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="Project"><select className="input" value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}>{availableProjects.length === 0 ? <option value={settings.projectId}>{project?.name ?? 'No project loaded'}</option> : availableProjects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><button className="btn" disabled={!selectedWorkspaceId || !selectedProjectId}>Save workspace</button></form></Card>
    <Card><h2>Add source</h2><p className="muted">Add repos, URLs, markdown, or uploaded text as agent sources. Refreshing turns them into reviewed runtime context.</p><form className="grid" onSubmit={addResource}><Field label="Type"><select className="input" value={resourceType} onChange={(e) => setResourceType(e.target.value as 'git' | 'url' | 'markdown' | 'upload')}><option value="git">Git repo</option><option value="url">URL</option><option value="markdown">Markdown</option><option value="upload">Upload text</option></select></Field><Field label="Name"><input className="input" value={resourceName} onChange={(e) => setResourceName(e.target.value)} /></Field><Field label="URI / URL"><input className="input" value={resourceUri} onChange={(e) => setResourceUri(e.target.value)} /></Field>{resourceType === 'git' ? <Field label="Branch"><input className="input" value={branch} onChange={(e) => setBranch(e.target.value)} /></Field> : null}<Field label="Update cadence"><select className="input" value={frequency} onChange={(e) => setFrequency(e.target.value)}><option value="manual">Manual</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select></Field>{resourceType === 'markdown' || resourceType === 'upload' ? <Field label="Content"><textarea className="input" value={content} onChange={(e) => setContent(e.target.value)} /></Field> : null}<button className="btn" disabled={busy}>{busy ? 'Saving…' : 'Add source'}</button></form></Card></div>
  </main>;
}
