'use client';

import { useEffect, useState } from 'react';
import { PageHeader, Card, EmptyState, Metric, StatusChip } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import type { AgentFile, AgentFilesResponse } from '../../lib/types';
import { apiFetchText, fmt } from '../../lib/api';

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

  useEffect(() => { void load(false); void loadPack(); }, [settings.workspaceId, settings.projectId]);

  return <main className="page">
    <PageHeader eyebrow="Agent Files" title="Generated agent files and skills" description="Generate legacy agent files and the new remote-only Skill Pack that installs thin Hermes/Codex/Claude adapters while ContextSmith hosts the indexed repo context." actions={<button className="btn" disabled={busy} onClick={() => void load(true)}>{busy ? 'Regenerating…' : 'Regenerate agent files'}</button>} />
    {error ? <div className="notice error">{error}</div> : null}
    <div className="grid four"><Metric label="Files" value={files?.files.length ?? 0} /><Metric label="Resources" value={files?.resource_count ?? 0} /><Metric label="Repo skills" value={files?.repo_agent_count ?? 0} /><Metric label="Generated" value={fmt(files?.generated_at)} /></div>

    <Card>
      <h2>Install remote repo agent</h2>
      <p className="muted">Phase 1 Skill Pack is context-only and remote-first. Install the Hermes skill shim from a pinned raw GitHub URL after publishing, then configure MCP separately with a scoped token. The local runtime must not assume repo files are available for local grep/read.</p>
      <div className="notice">Available capability: <strong>contextsmith.get_agent_context</strong>. Remote grep/read/search/symbol tools are intentionally not advertised yet.</div>
      <button className="btn secondary" disabled={packBusy} onClick={() => void loadPack()}>{packBusy ? 'Loading…' : 'Reload Skill Pack artifacts'}</button>
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

    <div className="grid two">
      <Card>
        <h2>Legacy generated files</h2>
        {!files ? <EmptyState text="Agent files are loading." /> : <div className="grid">{files.files.map((file) => <button type="button" key={file.path} className={`scope-pill ${selected?.path === file.path ? 'active' : ''}`} onClick={() => setSelectedPath(file.path)}><strong>{file.path}</strong><small>{file.kind} · {file.description}</small></button>)}</div>}
      </Card>
      <Card>
        <h2>{selected?.path ?? 'Preview'}</h2>
        {selected ? <div className="grid"><StatusChip value={selected.kind} /><p className="muted">{selected.description}</p><pre className="code-block light">{selected.content}</pre></div> : <EmptyState text="Select a generated file." />}
      </Card>
    </div>
  </main>;
}
