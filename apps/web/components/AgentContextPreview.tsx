'use client';

import type { AgentContextResponse, Resource } from '../lib/types';
import { Card, EmptyState, Metric } from './ui';

export function AgentContextPreview({ result, resources, title = 'Generated context packet' }: { result: AgentContextResponse | null; resources: Resource[]; title?: string }) {
  if (!result) return <EmptyState text="No generated runtime context yet. Generate a preview to review the agent output, instruction, citations, and code symbols." />;
  const byResource = new Map(resources.map((resource) => [resource.id, resource]));
  const citedResources = new Set(result.citations.map((citation) => citation.resource_id));
  return <div className="grid">
    <div className="grid four"><Metric label="Runtime" value={result.runtime} /><Metric label="Citations" value={result.citations.length} /><Metric label="Cited resources" value={citedResources.size} /><Metric label="Symbols" value={result.symbols?.length ?? 0} /></div>
    <Card><h2>{title}</h2><p className="muted">This is the actual context packet a runtime agent would read. If this looks wrong/noisy/stale, the repo agent is not review-ready.</p><pre className="code-block">{result.context || 'No context returned for this query/scope.'}</pre></Card>
    <Card><h2>Citations and evidence</h2>{result.citations.length === 0 ? <EmptyState text="No citations returned. This is a retrieval failure for this query/scope." /> : <div className="table-wrap"><table><thead><tr><th>Source</th><th>Evidence</th><th>Relevance</th></tr></thead><tbody>{result.citations.map((citation) => { const resource = byResource.get(citation.resource_id); return <tr key={citation.chunk_id}><td><strong>{resource?.name ?? 'Source'}</strong></td><td><strong>{citation.title || citation.path || 'Evidence passage'}</strong><div className="muted">Passage {citation.ordinal + 1}</div></td><td>{Math.round(citation.score * 100)}%</td></tr>; })}</tbody></table></div>}</Card>
    <Card><h2>Code symbols</h2>{!result.symbols || result.symbols.length === 0 ? <EmptyState text="No code symbols were returned for this query/scope." /> : <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Path</th><th>Lines</th></tr></thead><tbody>{result.symbols.slice(0, 20).map((symbol) => <tr key={`${symbol.resource_id}-${symbol.path}-${symbol.name}-${symbol.line_start}`}><td><strong>{symbol.name}</strong><div className="muted">{symbol.kind} · {symbol.language}</div></td><td>{symbol.path}</td><td>{symbol.line_start}-{symbol.line_end}</td></tr>)}</tbody></table></div>}</Card>
  </div>;
}
