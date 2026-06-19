'use client';

import { useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, Metric, EmptyState, StatusChip } from '../../components/ui';
import { AgentContextPreview } from '../../components/AgentContextPreview';
import { ResourceScopePicker, describeScope } from '../../components/ResourceScopePicker';
import { usePlatform } from '../../lib/platform-context';
import type { AgentContextResponse } from '../../lib/types';
import { fmt } from '../../lib/api';

const REVIEW_PROMPTS = [
  { id: 'identity', label: 'Agent identity', query: 'Summarize this generated repo/document agent for a reviewer. Explain what project it represents, which resources it can cite, and what kind of questions it should or should not answer. Cite concrete repository evidence.' },
  { id: 'runtime', label: 'Runtime behavior', query: 'Describe the runtime behavior and operating constraints this agent should follow. Include production-action boundaries and evidence discipline. Cite source context.' },
  { id: 'coverage', label: 'Source coverage', query: 'Review the indexed resource coverage for this project. What major repos/resources are available, what is likely missing or stale, and what should a human reviewer inspect first? Cite evidence from resources.' },
];

export default function AgentProfilePage() {
  const { agent, provider, workspace, project, resources, reviewItems, usageItems, settings, client } = usePlatform();
  const [selectedPrompt, setSelectedPrompt] = useState(REVIEW_PROMPTS[0].id);
  const [scopeResourceIds, setScopeResourceIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<AgentContextResponse | null>(null);
  const [generatedFor, setGeneratedFor] = useState<{ lens: string; scope: string } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const activePrompt = REVIEW_PROMPTS.find((prompt) => prompt.id === selectedPrompt) ?? REVIEW_PROMPTS[0];
  const usageByResource = useMemo(() => new Map(usageItems.map((item) => [item.resource_id, item])), [usageItems]);
  const reviewByResource = useMemo(() => new Map(reviewItems.map((item) => [item.resource.id, item])), [reviewItems]);

  async function generatePreview() {
    setGenerating(true); setPreviewError(null);
    try {
      const result = await client<AgentContextResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-context`, {
        method: 'POST',
        body: JSON.stringify({ query: activePrompt.query, runtime: agent?.default_runtime ?? 'hermes', resource_ids: scopeResourceIds.length ? scopeResourceIds : null, top_k: 12, max_chars: 22000, include_code_symbols: true }),
      });
      setPreview(result);
      setGeneratedFor({ lens: activePrompt.label, scope: describeScope(resources, scopeResourceIds) });
    } catch (err) { setPreviewError(String(err)); }
    finally { setGenerating(false); }
  }

  useEffect(() => {
    if (agent && resources.length && preview === null && !generating) void generatePreview();
    // generate initial review packet once after data loads; later user changes require explicit button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent?.id, resources.length]);

  return <main className="page">
    <PageHeader eyebrow="Agent Profile" title="Generated repo agent content" description="Review the generated agent identity, resource coverage, context packets, citations, and symbols. No server/vim review required." />
    {!agent ? <EmptyState text="Agent profile is loading or unavailable." /> : <>
      <div className="grid four"><Metric label="Runtime" value={agent.default_runtime} /><Metric label="Resources" value={agent.resource_count} /><Metric label="Snapshots" value={agent.current_snapshot_count} /><Metric label="Graph nodes/edges" value={`${agent.graph_node_count}/${agent.graph_edge_count}`} /></div>
      <Card><h2>Agent manifest</h2><p className="muted">Human-readable summary of what was generated. Review by project/resource names and evidence below.</p><div className="grid two"><div><div className="label">Agent</div><strong>{agent.name}</strong><p className="muted">{agent.description || 'Generated knowledge agent for this project.'}</p></div><div><div className="label">Workspace / project</div><strong>{workspace?.name ?? 'Workspace'} / {project?.name ?? 'Project'}</strong></div></div></Card>
      <div className="grid two"><Card><h2>Operating guardrails</h2><p className="muted">Production mutations require explicit external approval. Runtime responses must stay grounded in indexed evidence and citations.</p><div className="grid two"><Metric label="Default runtime" value={agent.default_runtime} /><Metric label="Resources in scope" value={agent.resource_count} /></div></Card><Card><h2>Provider and freshness</h2><div className="grid"><StatusChip value={provider?.status ?? 'unknown'} /><p className="muted">{provider ? `${provider.embedding.provider}/${provider.embedding.model}` : 'Provider not loaded'}</p><p className="muted">Last indexed: {fmt(agent.last_index_finished_at)}</p></div></Card></div>
      <Card><h2>Resource contribution map</h2><p className="muted">This tells you what the repo agent is made of. Use this before approving the agent: resource status, review status, freshness, usage, and refresh cadence.</p><div className="table-wrap"><table><thead><tr><th>Resource</th><th>Review/freshness</th><th>Usage</th><th>Refresh</th></tr></thead><tbody>{resources.map((resource) => { const review = reviewByResource.get(resource.id); const usage = usageByResource.get(resource.id); return <tr key={resource.id}><td><strong>{resource.name}</strong><div className="muted">{resource.type}</div></td><td><StatusChip value={resource.review_status} /> <StatusChip value={review?.freshness_status ?? 'unknown'} /><div className="muted">{review?.stale_reasons.join(', ') || 'no stale reasons'}</div></td><td>{usage?.hit_count ?? 0} hits<div className="muted">last {fmt(usage?.last_used_at)}</div></td><td>{resource.update_frequency}<div className="muted">{fmt(resource.last_refresh_finished_at)}</div></td></tr>; })}</tbody></table></div></Card>
      <Card><h2>Generate reviewable agent content</h2><p className="muted">This generates the actual runtime context packet and citations for the selected review lens. This is the content you review.</p><div className="grid"><div className="grid two"><label><span className="label">Review lens</span><select className="input" value={selectedPrompt} onChange={(event) => setSelectedPrompt(event.target.value)}>{REVIEW_PROMPTS.map((prompt) => <option key={prompt.id} value={prompt.id}>{prompt.label}</option>)}</select></label><div><div className="label">Current scope</div><div>{describeScope(resources, scopeResourceIds)}</div></div></div><ResourceScopePicker resources={resources} selectedIds={scopeResourceIds} onChange={setScopeResourceIds} label="Agent-content scope" /><button type="button" className="btn" disabled={generating} onClick={() => void generatePreview()}>{generating ? 'Generating…' : 'Generate review packet'}</button></div>{previewError ? <div className="notice error">{previewError}</div> : null}</Card>
      {generatedFor ? <div className="notice">Generated for: <strong>{generatedFor.lens}</strong> · {generatedFor.scope}</div> : null}
      {generatedFor && (generatedFor.lens !== activePrompt.label || generatedFor.scope !== describeScope(resources, scopeResourceIds)) ? <div className="notice error">Displayed agent packet was generated for previous controls. Regenerate before review/approval.</div> : null}
      <AgentContextPreview result={preview} resources={resources} title="Generated agent review packet" />
    </>}
  </main>;
}
