'use client';

import { useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, Metric, StatusChip, EmptyState } from '../../components/ui';
import { AgentContextPreview } from '../../components/AgentContextPreview';
import { usePlatform } from '../../lib/platform-context';
import type { AgentCardSummary, AgentCardSummaryList, AgentContextResponse, PatchProposal, PrRequest, Resource, ReviewItem, RepoAgentBrief, UsageItem } from '../../lib/types';
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
  const [patchScope, setPatchScope] = useState('Draft a minimal repo-scoped patch from indexed evidence');
  const [patchPath, setPatchPath] = useState('README.md');
  const [patchContent, setPatchContent] = useState('');
  const [patchProposal, setPatchProposal] = useState<PatchProposal | null>(null);
  const [prRecord, setPrRecord] = useState<PrRequest | null>(null);
  const [patchBusy, setPatchBusy] = useState(false);
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

  async function generatePatchProposal() {
    if (!selected) return;
    setPatchBusy(true); setError(null); setPatchProposal(null); setPrRecord(null);
    try {
      const result = await client<PatchProposal>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/remote-code/generate_patch`, {
        method: 'POST',
        body: JSON.stringify({
          resource_id: selected.id,
          scope: patchScope,
          source_branch: `contextsmith/${selected.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'repo'}-patch`,
          target_branch: brief?.branch ?? 'main',
          base_commit: brief?.commit ?? undefined,
          files: [{ path: patchPath, start_line: 1, end_line: 1, new_content: patchContent || '# Proposed ContextSmith patch', rationale: 'Operator-entered patch proposal' }],
        }),
      });
      setPatchProposal(result);
    } catch (err) { setError(String(err)); }
    finally { setPatchBusy(false); }
  }

  async function recordPrApproval() {
    if (!patchProposal) return;
    setPatchBusy(true); setError(null);
    try {
      const result = await client<PrRequest>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/remote-code/open_pr`, {
        method: 'POST',
        body: JSON.stringify({ patch_proposal_id: patchProposal.id, source_branch: patchProposal.source_branch ?? 'contextsmith/patch', target_branch: patchProposal.target_branch ?? 'main', approval_note: `Approved patch proposal ${patchProposal.id}` }),
      });
      setPrRecord(result);
    } catch (err) { setError(String(err)); }
    finally { setPatchBusy(false); }
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
        <h2>Opt-in patch / PR workflow</h2>
        <p className="muted">Read-only remains the default. Patch generation requires project policy <code>patch_generation=enabled</code> plus <code>patch:generate</code>; PR records require <code>open_pr=enabled</code>, <code>pr:write</code>, and explicit approval.</p>
        <div className="notice">This surface creates a patch proposal and PR approval record only. It does not mutate the source repo, push branches, run tests, deploy, or open GitHub PRs without a separate approved integration.</div>
        <div className="grid">
          <label className="label">Scope<input value={patchScope} onChange={(event) => setPatchScope(event.target.value)} /></label>
          <label className="label">Repo-relative path<input value={patchPath} onChange={(event) => setPatchPath(event.target.value)} /></label>
          <label className="label">Replacement for line 1<textarea rows={4} value={patchContent} onChange={(event) => setPatchContent(event.target.value)} placeholder="New first-line content for a patch proposal" /></label>
          <button type="button" className="btn secondary" disabled={patchBusy} onClick={() => void generatePatchProposal()}>{patchBusy ? 'Working…' : 'Generate opt-in patch proposal'}</button>
        </div>
        {patchProposal ? <div><div className="label">Patch proposal</div><div className="code">{patchProposal.diff_summary}<br />indexed_commit={patchProposal.indexed_commit ?? 'unknown'}<br />branch_moved={String(patchProposal.branch_moved)}<br />warnings={patchProposal.warnings.join(', ') || 'none'}</div><pre className="code-block light">{patchProposal.unified_diff}</pre><button type="button" className="btn" disabled={patchBusy || patchProposal.branch_moved} onClick={() => void recordPrApproval()}>Record PR approval</button></div> : null}
        {prRecord ? <div className="notice">PR approval record: {prRecord.status} · {prRecord.source_branch} → {prRecord.target_branch} · {prRecord.diff_summary}</div> : null}
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
