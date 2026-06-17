'use client';

import { useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, Metric, StatusChip, EmptyState } from '../../components/ui';
import { AgentContextPreview } from '../../components/AgentContextPreview';
import { usePlatform } from '../../lib/platform-context';
import type { AgentCardSummary, AgentCardSummaryList, AgentContextResponse, Resource, ReviewItem, RepoAgentBrief, UsageItem } from '../../lib/types';
import { short } from '../../lib/api';

function readiness(resource: Resource, review?: ReviewItem) {
  if (resource.status !== 'active') return 'inactive';
  if (!resource.retrieval_enabled) return 'retrieval-off';
  if (!resource.current_snapshot_id) return 'not-indexed';
  if (review?.freshness_status && review.freshness_status !== 'fresh') return 'needs-review';
  return 'ready';
}

function invocation(resource: Resource, workspaceId: string, projectId: string) {
  return JSON.stringify({
    endpoint: `/workspaces/${workspaceId}/projects/${projectId}/agent-context`,
    body: {
      runtime: 'hermes',
      resource_ids: [resource.id],
      query: `Ask the ${resource.name} repo agent how this repo works and cite exact files.`,
      include_code_symbols: true,
    },
  }, null, 2);
}

function suggestedQuestions(resource: Resource) {
  const name = resource.name;
  return [
    `What is ${name} responsible for in this project?`,
    `Show the main entrypoints, config files, and runtime boundaries for ${name}.`,
    `What should a Hermes/Codex specialist know before editing ${name}?`,
    `Find likely runbooks, deployment logic, and operational risks in ${name}.`,
  ];
}

export default function RepoAgentsPage() {
  const { resources, reviewItems, usageItems, settings, client, agent } = usePlatform();
  const repoAgents = useMemo(() => resources.filter((resource) => resource.type === 'git'), [resources]);
  const reviewByResource = useMemo(() => new Map(reviewItems.map((item) => [item.resource.id, item])), [reviewItems]);
  const usageByResource = useMemo(() => new Map(usageItems.map((item) => [item.resource_id, item])), [usageItems]);
  const [summaries, setSummaries] = useState<AgentCardSummary[]>([]);
  const [auditRunning, setAuditRunning] = useState(false);
  const [selectedId, setSelectedId] = useState<string>('');
  const [preview, setPreview] = useState<AgentContextResponse | null>(null);
  const [brief, setBrief] = useState<RepoAgentBrief | null>(null);
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const selected = repoAgents.find((resource) => resource.id === selectedId) ?? repoAgents[0] ?? null;
  const summaryByResource = useMemo(() => new Map(summaries.map((summary) => [summary.resource_id, summary])), [summaries]);
  const selectedSummary = selected ? summaryByResource.get(selected.id) : undefined;
  const selectedReview = selected ? reviewByResource.get(selected.id) : undefined;
  const selectedUsage = selected ? usageByResource.get(selected.id) : undefined;

  useEffect(() => {
    if (!selected) { setBrief(null); setBriefError(null); setBriefLoading(false); return; }
    let cancelled = false;
    setBrief(null);
    setBriefError(null);
    setBriefLoading(true);
    client<RepoAgentBrief>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selected.id}/brief`)
      .then((result) => { if (!cancelled) setBrief(result); })
      .catch((err) => { if (!cancelled) setBriefError(String(err)); })
      .finally(() => { if (!cancelled) setBriefLoading(false); });
    return () => { cancelled = true; };
  }, [client, selected?.id, settings.workspaceId, settings.projectId]);

  useEffect(() => {
    let cancelled = false;
    client<AgentCardSummaryList>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-card-summaries`)
      .then((result) => { if (!cancelled) setSummaries(result.summaries); })
      .catch(() => { if (!cancelled) setSummaries([]); });
    return () => { cancelled = true; };
  }, [client, settings.workspaceId, settings.projectId]);

  async function runReadOnlyAudit() {
    setAuditRunning(true); setError(null);
    try {
      const result = await client<AgentCardSummaryList>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-card-summaries/run?dry_run=true`, { method: 'POST' });
      setSummaries(result.summaries);
    } catch (err) { setError(String(err)); }
    finally { setAuditRunning(false); }
  }

  async function generateSubAgentPrompt(resource: Resource) {
    setSelectedId(resource.id);
    setGenerating(true); setError(null);
    try {
      const result = await client<AgentContextResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-context`, {
        method: 'POST',
        body: JSON.stringify({
          query: `You are the ${resource.name} repo sub-agent. Build a concise operating brief for Hermes/Codex: repo purpose, entrypoints, key files, config/runtime boundaries, how to answer questions about this repo, and what not to mutate without approval. Cite exact files.`,
          runtime: agent?.default_runtime ?? 'hermes',
          resource_ids: [resource.id],
          top_k: 14,
          max_chars: 22000,
          include_code_symbols: true,
        }),
      });
      setPreview(result);
    } catch (err) { setError(String(err)); }
    finally { setGenerating(false); }
  }

  return <main className="page">
    <PageHeader eyebrow="Repo Agents" title="Git repos as sub-agents" description="Each git resource is treated as a scoped repo sub-agent with its own identity, readiness, invocation contract, generated operating brief, citations, and symbols. This is the repo-as-agent surface, not a generic index table." actions={<><button className="btn secondary" disabled={auditRunning} onClick={() => void runReadOnlyAudit()}>{auditRunning ? 'Auditing…' : 'Run read-only drift audit'}</button><button className="btn" disabled={!selected || generating} onClick={() => selected && void generateSubAgentPrompt(selected)}>{generating ? 'Generating…' : 'Generate selected sub-agent brief'}</button></>} />
    <div className="grid four"><Metric label="Repo sub-agents" value={repoAgents.length} /><Metric label="Ready" value={repoAgents.filter((resource) => readiness(resource, reviewByResource.get(resource.id)) === 'ready').length} /><Metric label="Needs review" value={repoAgents.filter((resource) => readiness(resource, reviewByResource.get(resource.id)) !== 'ready').length} /><Metric label="Drift findings" value={summaries.filter((summary) => summary.status !== 'healthy').length} /></div>
    {repoAgents.length === 0 ? <EmptyState text="No git resources found. Add a git repo resource to create a repo sub-agent." /> : <div className="repo-agent-grid">{repoAgents.map((resource) => {
      const review = reviewByResource.get(resource.id);
      const usage = usageByResource.get(resource.id);
      const state = readiness(resource, review);
      const summary = summaryByResource.get(resource.id);
      return <button type="button" key={resource.id} className={`repo-agent-card ${selected?.id === resource.id ? 'active' : ''}`} onClick={() => { setSelectedId(resource.id); setPreview(null); }}>
        <div className="repo-agent-card-head"><strong>{resource.name}</strong><StatusChip value={summary?.status ?? state} /></div>
        <div className="muted">Repo sub-agent generated from git resource</div>
        <div className="code">{resource.uri}</div>
        <div className="repo-agent-card-metrics"><span>hits {usage?.hit_count ?? 0}</span><span>snapshot {short(resource.current_snapshot_id)}</span><span>{review?.freshness_status ?? 'unknown'}</span><span>{summary?.severity ?? 'not audited'}</span></div>
      </button>;
    })}</div>}
    {selected ? <div className="grid two">
      <Card>
        <h2>{selected.name} sub-agent</h2>
        <p className="muted">This repo is a scoped sub-agent. Hermes/Codex should route repo-specific questions to this resource id instead of querying the whole project blindly.</p>
        <div className="grid three"><Metric label="Readiness" value={brief?.readiness ?? readiness(selected, selectedReview)} /><Metric label="Review" value={selected.review_status} /><Metric label="Drift audit" value={selectedSummary?.status ?? 'not run'} /></div>
        {selectedSummary ? <div><div className="label">Drift findings</div><div className="notice">{selectedSummary.summary}</div><pre className="code-block light">{selectedSummary.findings.length ? selectedSummary.findings.map((finding) => `${String(finding.severity ?? 'info')}: ${String(finding.code ?? 'finding')} — ${String(finding.message ?? '')}`).join('\n') : 'No findings.'}</pre></div> : <div className="notice">No drift audit has been run for this repo agent yet. The audit is read-only and only writes ContextSmith summary/audit records.</div>}
        <div><div className="label">Repo identity</div><div className="code">resource_id={selected.id}<br />snapshot={selected.current_snapshot_id ?? 'none'}<br />branch={brief?.branch ?? 'default'}<br />uri={selected.uri}</div></div>
        <div><div className="label">Generated operating brief</div>{briefError ? <div className="notice error">{briefError}</div> : <pre className="code-block light">{brief?.operating_brief ?? (briefLoading ? 'Loading repo-agent brief…' : 'No repo-agent brief available.')}</pre>}</div>
        <div><div className="label">Quality gates</div><div className="code">{brief?.quality_gates.join('\n') ?? (briefLoading ? 'loading' : 'unavailable')}</div></div>
      </Card>
      <Card>
        <h2>Runtime invocation contract</h2>
        <p className="muted">This is the concrete contract that makes it repo-as-agent: the runtime asks the project agent with this repo resource id as the specialist scope.</p>
        <pre className="code-block light">{invocation(selected, settings.workspaceId, settings.projectId)}</pre>
      </Card>
      <Card>
        <h2>What to ask this sub-agent</h2>
        <div className="grid">{(brief?.suggested_questions ?? suggestedQuestions(selected)).map((question) => <button key={question} type="button" className="scope-pill" onClick={() => void generateSubAgentPrompt(selected)}><strong>{question}</strong><small>Generates a cited, repo-scoped operating brief</small></button>)}</div>
      </Card>
      <Card>
        <h2>Sub-agent boundary</h2>
        <div className="notice">This sub-agent can explain and cite its repo. It does not perform production mutations. Production actions still go through Hermes approval, typed MCP tools, and evidence workflow.</div>
        <pre className="code-block light">{`Agent identity: ${selected.name}\nScope: this repo only\nRuntime: ${agent?.default_runtime ?? 'hermes'}\nAllowed operation: cited context and code-symbol retrieval\nDisallowed operation: direct production mutation without Hermes approval`}</pre>
      </Card>
    </div> : null}
    {error ? <div className="notice error">{error}</div> : null}
    <AgentContextPreview result={preview} resources={resources} title="Generated repo sub-agent operating brief" />
  </main>;
}
