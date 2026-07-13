'use client';

import type { AgentContextCoverage, AgentContextResponse, Resource } from '../lib/types';
import { Card, EmptyState, Metric, StatusChip } from './ui';

function budgetSummary(entry: AgentContextCoverage) {
  const budgets = Object.entries(entry.configured_budgets || {});
  if (entry.budget_reason) return entry.budget_reason;
  if (budgets.length) return budgets.map(([key, value]) => `${key}=${value}`).join(', ');
  return 'default';
}

export function AgentContextPreview({ result, resources, title = 'Generated context packet' }: { result: AgentContextResponse | null; resources: Resource[]; title?: string }) {
  if (!result) return <EmptyState text="No generated runtime context yet. Generate a preview to review the agent output, instruction, citations, and code symbols." />;
  const byResource = new Map(resources.map((resource) => [resource.id, resource]));
  const citedResources = new Set(result.citations.map((citation) => citation.resource_id));
  const partialCoverage = (result.resource_coverage || []).filter((entry) => entry.coverage_status === 'partial');
  return <div className="grid">
    <div className="grid four"><Metric label="Runtime" value={result.runtime} /><Metric label="Citations" value={result.citations.length} /><Metric label="Cited resources" value={citedResources.size} /><Metric label="Symbols" value={result.symbols?.length ?? 0} /></div>
    {partialCoverage.length ? <Card><h2>Partial corpus risk</h2><div className="notice error">These sources hit an actual ingestion limit. Answers are grounded only in the indexed subset; treat install/security/architecture/comparison claims as incomplete until the source is reindexed with broader coverage.</div><ul className="muted">{partialCoverage.map((entry) => <li key={entry.resource_id}><strong>{entry.name}</strong>: {budgetSummary(entry)}{entry.suggested_retry ? ` · ${entry.suggested_retry}` : ''}</li>)}</ul></Card> : null}
    {result.coverage_warnings?.length ? <Card><h2>Coverage warning</h2><div className="notice error">{result.coverage_warnings.map((warning, index) => <div key={index}>{warning}</div>)}</div></Card> : null}
    {result.resource_coverage?.length ? <Card><h2>Resource coverage</h2><div className="table-wrap"><table><thead><tr><th>Source</th><th>Coverage</th><th>Queryable</th><th>Budget reason</th><th>Retry guidance</th></tr></thead><tbody>{result.resource_coverage.map((entry) => <tr key={entry.resource_id}><td><strong>{entry.name}</strong></td><td><StatusChip value={entry.coverage_status} />{entry.coverage_warnings.length ? <div className="muted">{entry.coverage_warnings.join('; ')}</div> : null}</td><td>{entry.queryable ? 'yes' : 'no'}</td><td>{budgetSummary(entry)}</td><td>{entry.suggested_retry || <span className="muted">—</span>}</td></tr>)}</tbody></table></div></Card> : null}
    <Card><h2>{title}</h2><p className="muted">This is the actual context packet a runtime agent would read. If this looks wrong/noisy/stale, the repo agent is not review-ready.</p><pre className="code-block">{result.context || 'No context returned for this query/scope.'}</pre></Card>
    <Card><h2>Citations and evidence</h2>{result.citations.length === 0 ? <EmptyState text="No citations returned. This is a retrieval failure for this query/scope." /> : <div className="table-wrap"><table><thead><tr><th>Source</th><th>Evidence</th><th>Relevance</th></tr></thead><tbody>{result.citations.map((citation) => { const resource = byResource.get(citation.resource_id); return <tr key={citation.chunk_id}><td><strong>{resource?.name ?? 'Source'}</strong></td><td><strong>{citation.title || citation.path || 'Evidence passage'}</strong><div className="muted">Passage {citation.ordinal + 1}</div></td><td>{Math.round(citation.score * 100)}%</td></tr>; })}</tbody></table></div>}</Card>
    <Card><h2>Code symbols</h2>{!result.symbols || result.symbols.length === 0 ? <EmptyState text="No code symbols were returned for this query/scope." /> : <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Path</th><th>Lines</th></tr></thead><tbody>{result.symbols.slice(0, 20).map((symbol) => <tr key={`${symbol.resource_id}-${symbol.path}-${symbol.name}-${symbol.line_start}`}><td><strong>{symbol.name}</strong><div className="muted">{symbol.kind} · {symbol.language}</div></td><td>{symbol.path}</td><td>{symbol.line_start}-{symbol.line_end}</td></tr>)}</tbody></table></div>}</Card>
  </div>;
}
