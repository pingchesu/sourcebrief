'use client';

import { useEffect, useState } from 'react';
import { PageHeader, Card, EmptyState, Metric, StatusChip } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import type { AgentFile, AgentFilesResponse, RemoteGrepResponse, RemoteReadFileResponse, Resource } from '../../lib/types';
import { apiFetchBlob, apiFetchText, fmt } from '../../lib/api';

type AgentPackArtifact = { path: string; kind: string; description: string; content: string };

const AGENT_PACK_ENDPOINTS = [
  { path: 'contextsmith-agent.yaml', kind: 'manifest', description: 'Portable remote repo-agent manifest.', endpoint: 'manifest' },
  { path: 'hermes/SKILL.md', kind: 'hermes-skill', description: 'Hermes skill shim. Install separately from MCP config.', endpoint: 'hermes/SKILL.md' },
  { path: 'codex/AGENTS.md', kind: 'codex-instructions', description: 'Codex instruction adapter for remote ContextSmith usage.', endpoint: 'codex/AGENTS.md' },
  { path: 'claude/CLAUDE.md', kind: 'claude-instructions', description: 'Claude instruction adapter for remote ContextSmith usage.', endpoint: 'claude/CLAUDE.md' },
  { path: 'mcp.json', kind: 'mcp-config', description: 'Hermes/Codex/Claude MCP config snippets using token environment placeholders.', endpoint: 'mcp.json' },
];

function downloadArtifact(file: AgentPackArtifact) {
  const blob = new Blob([file.content], { type: file.path.endsWith('.json') ? 'application/json' : 'text/plain' });
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = file.path.replaceAll('/', '__');
  link.click();
  URL.revokeObjectURL(href);
}

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(href);
}

export default function AgentFilesPage() {
  const { settings, client } = usePlatform();
  const [files, setFiles] = useState<AgentFilesResponse | null>(null);
  const [packFiles, setPackFiles] = useState<AgentPackArtifact[]>([]);
  const [selectedPath, setSelectedPath] = useState('');
  const [selectedPackPath, setSelectedPackPath] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [packError, setPackError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [packBusy, setPackBusy] = useState(false);
  const [resources, setResources] = useState<Resource[]>([]);
  const [selectedResourceId, setSelectedResourceId] = useState('');
  const [grepPattern, setGrepPattern] = useState('');
  const [grepResult, setGrepResult] = useState<RemoteGrepResponse | null>(null);
  const [readResult, setReadResult] = useState<RemoteReadFileResponse | null>(null);
  const [toolBusy, setToolBusy] = useState(false);
  const [toolError, setToolError] = useState<string | null>(null);
  const selected: AgentFile | null = files?.files.find((file) => file.path === selectedPath) ?? files?.files[0] ?? null;
  const selectedPack: AgentPackArtifact | null = packFiles.find((file) => file.path === selectedPackPath) ?? packFiles[0] ?? null;

  async function load(regenerate = false) {
    setBusy(true); setError(null);
    try {
      const result = await client<AgentFilesResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-files${regenerate ? '/regenerate' : ''}`, { method: regenerate ? 'POST' : 'GET' });
      setFiles(result);
      setSelectedPath((previous) => result.files.some((file) => file.path === previous) ? previous : result.files[0]?.path ?? '');
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function loadPack() {
    setPackBusy(true); setPackError(null);
    try {
      const artifacts = await Promise.all(AGENT_PACK_ENDPOINTS.map(async (item) => ({
        path: item.path,
        kind: item.kind,
        description: item.description,
        content: await apiFetchText(settings, `/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-pack/${item.endpoint}`),
      })));
      setPackFiles(artifacts);
      setSelectedPackPath((previous) => artifacts.some((file) => file.path === previous) ? previous : artifacts[0]?.path ?? '');
    } catch (err) { setPackError(String(err)); }
    finally { setPackBusy(false); }
  }

  async function downloadPackZip() {
    setPackBusy(true); setPackError(null);
    try {
      const blob = await apiFetchBlob(settings, `/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-pack.zip`);
      downloadBlob(blob, 'contextsmith-skill-pack.zip');
    } catch (err) { setPackError(String(err)); }
    finally { setPackBusy(false); }
  }

  async function loadResources() {
    try {
      const result = await client<Resource[]>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources`);
      const gitResources = result.filter((resource) => resource.type.toLowerCase() === 'git');
      setResources(gitResources);
      setSelectedResourceId((previous) => gitResources.some((resource) => resource.id === previous) ? previous : gitResources.find((resource) => resource.current_snapshot_id)?.id ?? gitResources[0]?.id ?? '');
    } catch (err) { setToolError(String(err)); }
  }

  async function runGrepExample() {
    if (!selectedResourceId || !grepPattern.trim()) return;
    setToolBusy(true); setToolError(null); setReadResult(null);
    try {
      const result = await client<RemoteGrepResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/remote-code/grep_code`, {
        method: 'POST',
        body: JSON.stringify({ pattern: grepPattern.trim(), resource_ids: [selectedResourceId], max_matches: 5 }),
      });
      setGrepResult(result);
    } catch (err) { setToolError(String(err)); }
    finally { setToolBusy(false); }
  }

  async function readFirstMatch() {
    const match = grepResult?.matches[0];
    if (!match) return;
    setToolBusy(true); setToolError(null);
    try {
      const result = await client<RemoteReadFileResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/remote-code/read_file`, {
        method: 'POST',
        body: JSON.stringify({ resource_id: match.resource_id, path: match.path, start_line: Math.max(1, match.line_start - 3), end_line: match.line_end + 3 }),
      });
      setReadResult(result);
    } catch (err) { setToolError(String(err)); }
    finally { setToolBusy(false); }
  }

  useEffect(() => { void load(false); void loadPack(); void loadResources(); }, [settings.workspaceId, settings.projectId]);

  return <main className="page">
    <PageHeader eyebrow="Agent Files" title="Ship the agent pack" description="Hand this project agent off to a runtime: download the remote-only Skill Pack — thin Hermes/Codex/Claude adapters plus MCP config — while ContextSmith keeps hosting the indexed repo context. Legacy generated files remain below for older integrations." actions={<button className="btn" disabled={busy} onClick={() => void load(true)}>{busy ? 'Regenerating…' : 'Regenerate agent files'}</button>} />
    {error ? <div className="notice error">{error}</div> : null}
    <div className="grid four"><Metric label="Files" value={files?.files.length ?? 0} /><Metric label="Resources" value={files?.resource_count ?? 0} /><Metric label="Repo skills" value={files?.repo_agent_count ?? 0} /><Metric label="Generated" value={fmt(files?.generated_at)} /></div>

    <Card>
      <h2>Install remote repo agent</h2>
      <p className="muted">Phase 3 Skill Pack is remote-first: install the Hermes skill shim from a pinned raw GitHub URL, configure MCP separately with a scoped token, then use ContextSmith for context plus exact remote code inspection.</p>
      <div className="notice">Available capabilities: <strong>contextsmith.get_agent_context</strong>, <strong>grep_code</strong>, <strong>read_file</strong>, <strong>search_code</strong>, and <strong>find_symbol</strong>. Local repo checkout is not required.</div>
      <div className="actions"><button className="btn secondary" disabled={packBusy} onClick={() => void loadPack()}>{packBusy ? 'Loading…' : 'Reload Skill Pack artifacts'}</button><button className="btn" disabled={packBusy} onClick={() => void downloadPackZip()}>Download Skill Pack (.zip)</button></div>
      {packError ? <div className="notice error">{packError}</div> : null}
      <div className="grid two">
        <div className="grid">
          {packFiles.length === 0 ? <EmptyState text="Skill Pack artifacts are loading." /> : packFiles.map((file) => <button type="button" key={file.path} className={`scope-pill ${selectedPack?.path === file.path ? 'active' : ''}`} onClick={() => setSelectedPackPath(file.path)}><strong>{file.path}</strong><small>{file.kind} · {file.description}</small></button>)}
        </div>
        <div>
          <h3>{selectedPack?.path ?? 'Skill Pack preview'}</h3>
          {selectedPack ? <div className="grid"><StatusChip value={selectedPack.kind} /><p className="muted">{selectedPack.description}</p><div className="actions"><button className="btn secondary" onClick={() => void navigator.clipboard.writeText(selectedPack.content)}>Copy artifact</button><button className="btn secondary" onClick={() => downloadArtifact(selectedPack)}>Download file</button></div><pre className="code-block light">{selectedPack.content}</pre></div> : <EmptyState text="Select a Skill Pack artifact." />}
        </div>
      </div>
    </Card>

    <Card>
      <h2>Remote follow-up inspection</h2>
      <p className="muted">Smoke the same workflow the installed agents use: get context first, then run bounded remote grep and read_file against indexed snapshots. Pick a resource from the project; no UUID hand-entry or local checkout is needed.</p>
      <div className="grid two">
        <label>Resource<select value={selectedResourceId} onChange={(event) => setSelectedResourceId(event.target.value)}>{resources.map((resource) => <option key={resource.id} value={resource.id}>{resource.name} · {resource.current_snapshot_id ? 'indexed' : 'not indexed'}</option>)}</select></label>
        <label>Pattern<input value={grepPattern} onChange={(event) => setGrepPattern(event.target.value)} placeholder="e.g. reconcile_cart" /></label>
      </div>
      <div className="actions"><button className="btn" disabled={toolBusy || !selectedResourceId || !grepPattern.trim()} onClick={() => void runGrepExample()}>{toolBusy ? 'Running…' : 'Run remote grep'}</button><button className="btn secondary" disabled={toolBusy || !grepResult?.matches.length} onClick={() => void readFirstMatch()}>Read first match</button></div>
      {toolError ? <div className="notice error">{toolError}</div> : null}
      {grepResult ? <div className="notice">{grepResult.matches.length} remote grep matches{grepResult.truncated ? ' · truncated' : ''}{grepResult.matches[0] ? ` · first: ${grepResult.matches[0].path}:${grepResult.matches[0].line_start}` : ''}</div> : null}
      {readResult ? <pre className="code-block light">{readResult.content}</pre> : <EmptyState text="Run remote grep, then read the first match to preview exact indexed source lines." />}
    </Card>

    <div className="grid two">
      <Card>
        <h2>Legacy generated files</h2>
        <p className="muted">Kept for older integrations. For new handoffs use the Skill Pack above.</p>
        {!files ? <EmptyState text="Agent files are loading." /> : <div className="grid">{files.files.map((file) => <button type="button" key={file.path} className={`scope-pill ${selected?.path === file.path ? 'active' : ''}`} onClick={() => setSelectedPath(file.path)}><strong>{file.path}</strong><small>{file.kind} · {file.description}</small></button>)}</div>}
      </Card>
      <Card>
        <h2>{selected?.path ?? 'Preview'}</h2>
        {selected ? <div className="grid"><StatusChip value={selected.kind} /><p className="muted">{selected.description}</p><pre className="code-block light">{selected.content}</pre></div> : <EmptyState text="Select a generated file." />}
      </Card>
    </div>
  </main>;
}
