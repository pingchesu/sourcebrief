'use client';

import { useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, SectionCard, Metric, Chip, StatusChip, EmptyState, Field, ReadinessBadge } from '../../components/ui';
import { AgentContextPreview } from '../../components/AgentContextPreview';
import { ResourceScopePicker, describeScope } from '../../components/ResourceScopePicker';
import { usePlatform } from '../../lib/platform-context';
import { readiness } from '../../lib/lifecycle';
import { short } from '../../lib/api';
import type { AgentCardSummary, AgentCardSummaryList, AgentContextResponse, PatchProposal, PrRequest, RepoAgentBrief, Resource, ReviewItem } from '../../lib/types';

type ScopeMode = 'project' | 'agent' | 'custom';

// Map the chosen scope onto the agent-context `resource_ids` contract:
// whole project → null, single repo sub-agent → [id], custom sources → ids.
function scopeResourceIds(mode: ScopeMode, agentId: string, customIds: string[]): string[] | null {
  if (mode === 'agent') return agentId ? [agentId] : null;
  if (mode === 'custom') return customIds.length ? customIds : null;
  return null;
}

function describeWorkbenchScope(mode: ScopeMode, agent: Resource | null, resources: Resource[], customIds: string[]): string {
  if (mode === 'agent') return agent ? `${agent.name} repo sub-agent` : 'No repo sub-agent selected';
  if (mode === 'custom') return describeScope(resources, customIds);
  return `Whole project · all ${resources.length} current resources`;
}

// Fallback suggested prompts when the repo-agent brief has not loaded yet.
function fallbackAgentPrompts(resource: Resource): string[] {
  const name = resource.name;
  return [
    `What is ${name} responsible for in this project?`,
    `Show the main entrypoints, config files, and runtime boundaries for ${name}.`,
    `What should a Hermes/Codex specialist know before editing ${name}?`,
    `Find likely runbooks, deployment logic, and operational risks in ${name}.`,
  ];
}

function genericPrompts(scopeLabel: string): string[] {
  return [
    `Across ${scopeLabel}, how does this system fit together? Cite exact files.`,
    `What are the main entrypoints, runtime boundaries, and config surfaces in ${scopeLabel}?`,
    `What should a specialist agent know before answering questions about ${scopeLabel}?`,
  ];
}

function invocationContract(resource: Resource, workspaceId: string, projectId: string): string {
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

export default function WorkbenchPage() {
  const { resources, reviewItems, usageItems, agent, client, settings, loading, error, reload } = usePlatform();

  const repoAgents = useMemo(() => resources.filter((resource) => resource.type === 'git'), [resources]);
  const reviewByResource = useMemo(() => new Map<string, ReviewItem>(reviewItems.map((item) => [item.resource.id, item])), [reviewItems]);
  const usageByResource = useMemo(() => new Map(usageItems.map((item) => [item.resource_id, item])), [usageItems]);

  // --- Scope state. ---
  const [mode, setMode] = useState<ScopeMode>('project');
  const [agentId, setAgentId] = useState<string>('');
  const [customIds, setCustomIds] = useState<string[]>([]);

  // Default to the first repo sub-agent once resources load (name-first, no UUID entry).
  useEffect(() => {
    if (repoAgents.length === 0) return;
    setAgentId((current) => (current && repoAgents.some((r) => r.id === current) ? current : repoAgents[0].id));
    setMode((current) => (current === 'project' ? 'agent' : current));
  }, [repoAgents]);

  const selectedAgent = useMemo(() => repoAgents.find((r) => r.id === agentId) ?? null, [repoAgents, agentId]);

  // --- Ask state. ---
  const [runtime, setRuntime] = useState('hermes');
  useEffect(() => { setRuntime(agent?.default_runtime ?? 'hermes'); }, [agent?.default_runtime]);
  const [topK, setTopK] = useState(8);
  const [question, setQuestion] = useState('How does this system work? Cite the exact files and runtime boundaries.');
  const [result, setResult] = useState<AgentContextResponse | null>(null);
  const [generatedFor, setGeneratedFor] = useState<{ scope: string; question: string; runtime: string; topK: number } | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  // --- Repo-agent brief. ---
  const [brief, setBrief] = useState<RepoAgentBrief | null>(null);
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== 'agent' || !selectedAgent) { setBrief(null); setBriefError(null); setBriefLoading(false); return; }
    let cancelled = false;
    setBrief(null); setBriefError(null); setBriefLoading(true);
    client<RepoAgentBrief>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/repo-agents/${selectedAgent.id}/brief`)
      .then((value) => { if (!cancelled) setBrief(value); })
      .catch((err) => { if (!cancelled) setBriefError(String(err)); })
      .finally(() => { if (!cancelled) setBriefLoading(false); });
    return () => { cancelled = true; };
  }, [client, mode, selectedAgent, settings.workspaceId, settings.projectId]);

  // --- Drift audit summaries (Advanced). ---
  const [summaries, setSummaries] = useState<AgentCardSummary[]>([]);
  const [auditRunning, setAuditRunning] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const summaryByResource = useMemo(() => new Map(summaries.map((s) => [s.resource_id, s])), [summaries]);
  const selectedSummary = selectedAgent ? summaryByResource.get(selectedAgent.id) : undefined;

  useEffect(() => {
    let cancelled = false;
    client<AgentCardSummaryList>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-card-summaries`)
      .then((value) => { if (!cancelled) setSummaries(value.summaries); })
      .catch(() => { if (!cancelled) setSummaries([]); });
    return () => { cancelled = true; };
  }, [client, settings.workspaceId, settings.projectId]);

  // --- Opt-in patch / PR (Advanced). ---
  const [patchScope, setPatchScope] = useState('Draft a minimal repo-scoped patch from indexed evidence');
  const [patchPath, setPatchPath] = useState('README.md');
  const [patchContent, setPatchContent] = useState('');
  const [patchProposal, setPatchProposal] = useState<PatchProposal | null>(null);
  const [prRecord, setPrRecord] = useState<PrRequest | null>(null);
  const [patchBusy, setPatchBusy] = useState(false);
  const [patchError, setPatchError] = useState<string | null>(null);

  const scopeLabel = describeWorkbenchScope(mode, selectedAgent, resources, customIds);
  const liveScope = { scope: scopeLabel, question, runtime, topK };
  const stale = generatedFor != null && (generatedFor.scope !== scopeLabel || generatedFor.question !== question || generatedFor.runtime !== runtime || generatedFor.topK !== topK);

  function canAsk(): boolean {
    return mode !== 'agent' || Boolean(selectedAgent);
  }

  async function ask(overrideQuestion?: string) {
    if (!canAsk()) {
      setAskError('Select a repo sub-agent before generating repo-scoped context.');
      return;
    }
    const finalQuestion = overrideQuestion ?? question;
    if (overrideQuestion != null) setQuestion(overrideQuestion);
    setAsking(true); setAskError(null);
    try {
      const next = await client<AgentContextResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-context`, {
        method: 'POST',
        body: JSON.stringify({
          query: finalQuestion,
          runtime,
          resource_ids: scopeResourceIds(mode, agentId, customIds),
          top_k: topK,
          max_chars: 22000,
          include_code_symbols: true,
        }),
      });
      setResult(next);
      setGeneratedFor({ scope: scopeLabel, question: finalQuestion, runtime, topK });
    } catch (err) { setAskError(String(err)); }
    finally { setAsking(false); }
  }

  async function runDriftAudit() {
    setAuditRunning(true);
    try {
      const value = await client<AgentCardSummaryList>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/agent-card-summaries/run?dry_run=true`, { method: 'POST' });
      setSummaries(value.summaries);
    } catch (err) { setPatchError(String(err)); }
    finally { setAuditRunning(false); }
  }

  async function generatePatchProposal() {
    if (!selectedAgent) return;
    setPatchBusy(true); setPatchError(null); setPatchProposal(null); setPrRecord(null);
    try {
      const value = await client<PatchProposal>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/remote-code/generate_patch`, {
        method: 'POST',
        body: JSON.stringify({
          resource_id: selectedAgent.id,
          scope: patchScope,
          source_branch: `contextsmith/${selectedAgent.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'repo'}-patch`,
          target_branch: brief?.branch ?? 'main',
          base_commit: brief?.commit ?? undefined,
          files: [{ path: patchPath, start_line: 1, end_line: 1, new_content: patchContent || '# Proposed ContextSmith patch', rationale: 'Operator-entered patch proposal' }],
        }),
      });
      setPatchProposal(value);
    } catch (err) { setPatchError(String(err)); }
    finally { setPatchBusy(false); }
  }

  async function recordPrApproval() {
    if (!patchProposal) return;
    setPatchBusy(true); setPatchError(null);
    try {
      const value = await client<PrRequest>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/remote-code/open_pr`, {
        method: 'POST',
        body: JSON.stringify({ patch_proposal_id: patchProposal.id, source_branch: patchProposal.source_branch ?? 'contextsmith/patch', target_branch: patchProposal.target_branch ?? 'main', approval_note: `Approved patch proposal ${patchProposal.id}` }),
      });
      setPrRecord(value);
    } catch (err) { setPatchError(String(err)); }
    finally { setPatchBusy(false); }
  }

  const readyAgents = repoAgents.filter((r) => readiness(r, reviewByResource.get(r.id)) === 'ready').length;
  const needsReview = repoAgents.length - readyAgents;
  const retrievalReady = repoAgents.filter((r) => r.retrieval_enabled && r.current_snapshot_id).length;
  const driftFindings = summaries.filter((s) => s.status !== 'healthy').length;

  const prompts = mode === 'agent' && selectedAgent
    ? (brief?.suggested_questions ?? fallbackAgentPrompts(selectedAgent))
    : genericPrompts(scopeLabel);

  return <main className="page">
    <PageHeader
      eyebrow="Workbench"
      title="Agent Workbench"
      description="Pick a scope — the whole project, one repo sub-agent, or a custom set of sources — confirm it is ready, then ask and inspect the exact cited context, citations, and code symbols the runtime would read. No UUID required."
      actions={<button className="btn secondary" onClick={() => reload()} disabled={loading}>{loading ? 'Loading…' : 'Reload'}</button>}
    />

    {error ? <div className="notice error">Could not load workbench data: {error}</div> : null}

    <div className="grid four">
      <Metric label="Repo sub-agents" value={repoAgents.length} />
      <Metric label="Ready" value={readyAgents} />
      <Metric label="Needs review" value={needsReview} />
      <Metric label="Retrieval-ready" value={retrievalReady} hint={`${driftFindings} drift finding${driftFindings === 1 ? '' : 's'}`} />
    </div>

    <div className="grid two">
      <SectionCard title="Scope" description="Choose what the agent should answer about. Selection is by name — repo sub-agents and sources, never UUIDs.">
        <div className="segmented" role="tablist" aria-label="Scope mode">
          <button type="button" role="tab" aria-selected={mode === 'project'} className={mode === 'project' ? 'active' : ''} onClick={() => setMode('project')}>Whole project</button>
          <button type="button" role="tab" aria-selected={mode === 'agent'} className={mode === 'agent' ? 'active' : ''} onClick={() => setMode('agent')}>Repo sub-agent</button>
          <button type="button" role="tab" aria-selected={mode === 'custom'} className={mode === 'custom' ? 'active' : ''} onClick={() => setMode('custom')}>Custom sources</button>
        </div>

        {mode === 'project' ? <div className="notice">All retrieval-enabled current resources in this project are in scope. Best for cross-cutting questions that span repos and docs.</div> : null}

        {mode === 'agent' ? (repoAgents.length === 0
          ? <EmptyState text="No git sources connected yet. Connect a git repo in Sources to create a repo sub-agent." />
          : <div className="repo-agent-grid">{repoAgents.map((resource) => {
            const review = reviewByResource.get(resource.id);
            const usage = usageByResource.get(resource.id);
            return <button type="button" key={resource.id} className={`repo-agent-card ${agentId === resource.id ? 'active' : ''}`} onClick={() => setAgentId(resource.id)}>
              <div className="repo-agent-card-head"><strong>{resource.name}</strong><ReadinessBadge state={readiness(resource, review)} lastIndexStatus={review?.last_index_status} /></div>
              <div className="muted">Repo sub-agent generated from a git source</div>
              <div className="code">{resource.uri}</div>
              <div className="repo-agent-card-metrics"><span>hits {usage?.hit_count ?? 0}</span><span>snapshot {short(resource.current_snapshot_id)}</span><span>{review?.freshness_status ?? 'unknown'}</span></div>
            </button>;
          })}</div>) : null}

        {mode === 'custom' ? (resources.length === 0
          ? <EmptyState text="No sources connected yet. Connect sources in Sources to query a custom scope." />
          : <ResourceScopePicker resources={resources} selectedIds={customIds} onChange={setCustomIds} label="Ask scope" />) : null}

        <div>
          <div className="label">Suggested prompts for this scope</div>
          <div className="workbench-prompts">{prompts.map((prompt) => (
            <button key={prompt} type="button" className="scope-pill" disabled={asking || !canAsk()} onClick={() => void ask(prompt)}>
              <strong>{prompt}</strong><small>Generates cited context for the current scope</small>
            </button>
          ))}</div>
        </div>
      </SectionCard>

      <SectionCard title="Ask" description="Generate the exact context packet a runtime agent would read for this scope.">
        <div className="grid two">
          <Field label="Runtime"><select className="input" value={runtime} onChange={(e) => setRuntime(e.target.value)}><option value="hermes">Hermes</option><option value="claude">Claude</option><option value="codex">Codex</option><option value="cursor">Cursor</option><option value="api">API</option></select></Field>
          <Field label="Top K"><input className="input" type="number" min={1} max={50} value={topK} onChange={(e) => setTopK(Number(e.target.value))} /></Field>
        </div>
        <div><div className="label">Current scope</div><div>{scopeLabel}</div></div>
        <Field label="Question"><textarea className="input" style={{ minHeight: 110 }} value={question} onChange={(e) => setQuestion(e.target.value)} /></Field>
        <div className="toolbar">
          <button type="button" className="btn" disabled={asking || !canAsk()} onClick={() => void ask()}>{asking ? 'Generating…' : 'Generate cited answer context'}</button>
          <StatusChip value={result ? (stale ? 'stale' : 'generated') : 'idle'} />
        </div>
        {askError ? <div className="notice error">{askError}</div> : null}
        {generatedFor ? <div className="notice">Generated for: <strong>{generatedFor.scope}</strong> · {generatedFor.runtime} · topK {generatedFor.topK}<br /><span className="muted">{generatedFor.question}</span></div> : null}
        {stale ? <div className="notice error">Displayed context was generated for previous controls (now: {liveScope.scope} · {liveScope.runtime} · topK {liveScope.topK}). Regenerate before review/approval.</div> : null}
      </SectionCard>
    </div>

    {mode === 'agent' && selectedAgent ? <div className="grid two">
      <Card>
        <h2>{selectedAgent.name} sub-agent brief</h2>
        <p className="muted">Hermes/Codex should route repo-specific questions to this resource as a scoped specialist instead of querying the whole project blindly.</p>
        <div className="grid three">
          <Metric label="Readiness" value={brief?.readiness ?? readiness(selectedAgent, reviewByResource.get(selectedAgent.id))} />
          <Metric label="Review" value={selectedAgent.review_status} />
          <Metric label="Drift audit" value={selectedSummary?.status ?? 'not run'} />
        </div>
        <div><div className="label">Repo identity</div><div className="code">snapshot={short(selectedAgent.current_snapshot_id)}<br />branch={brief?.branch ?? 'default'}<br />commit={short(brief?.commit)}<br />uri={selectedAgent.uri}</div></div>
        <div><div className="label">Generated operating brief</div>{briefError ? <div className="notice error">{briefError}</div> : <pre className="code-block light">{brief?.operating_brief ?? (briefLoading ? 'Loading repo-agent brief…' : 'No repo-agent brief available.')}</pre>}</div>
        <div><div className="label">Quality gates</div><div className="code">{brief?.quality_gates.join('\n') ?? (briefLoading ? 'loading' : 'unavailable')}</div></div>
        {selectedSummary ? <div>
          <div className="label">Drift findings</div>
          {selectedSummary.findings.length === 0
            ? <div className="empty">No concrete drift findings recorded for this repo sub-agent.</div>
            : <div className="table-wrap"><table><thead><tr><th>Severity</th><th>Finding</th></tr></thead><tbody>{selectedSummary.findings.map((finding, index) => (
              <tr key={index}><td><StatusChip value={String(finding.severity ?? selectedSummary.severity)} /></td><td><strong>{String(finding.code ?? finding.type ?? `finding-${index + 1}`)}</strong><div className="muted">{String(finding.message ?? finding.summary ?? finding.detail ?? JSON.stringify(finding))}</div></td></tr>
            ))}</tbody></table></div>}
        </div> : null}
      </Card>
      <Card>
        <h2>Runtime invocation contract</h2>
        <p className="muted">The concrete contract that makes this repo-as-agent: the runtime asks the project agent with this repo resource as the specialist scope.</p>
        <pre className="code-block light">{invocationContract(selectedAgent, settings.workspaceId, settings.projectId)}</pre>
        <div><div className="label">Sub-agent boundary</div><div className="notice">{brief?.safety_boundary ?? 'This sub-agent can explain and cite its repo. It does not perform production mutations. Production actions still go through Hermes approval, typed MCP tools, and the evidence workflow.'}</div></div>
      </Card>
    </div> : null}

    <AgentContextPreview result={result} resources={resources} title="Generated context packet" />

    <Card>
      <button type="button" className="advanced-toggle" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((open) => !open)}>
        <span>Advanced · governance (drift audit, opt-in patch / PR)</span><span className="code">{advancedOpen ? 'hide' : 'show'}</span>
      </button>
      {advancedOpen ? <div className="grid">
        {patchError ? <div className="notice error">{patchError}</div> : null}
        <SectionCard
          title="Read-only drift audit"
          description="Compares indexed evidence against the live repos. Read-only — it only writes ContextSmith summary/audit records, never the source repos."
          action={<button type="button" className="btn secondary" disabled={auditRunning} onClick={() => void runDriftAudit()}>{auditRunning ? 'Auditing…' : 'Run read-only drift audit'}</button>}
        >
          {summaries.length === 0
            ? <EmptyState text="No drift audit has been run yet. The audit is read-only and safe to run." />
            : <div className="table-wrap"><table><thead><tr><th>Repo sub-agent</th><th>Status</th><th>Severity</th><th>Summary</th></tr></thead><tbody>{summaries.map((s) => {
              const resource = repoAgents.find((r) => r.id === s.resource_id);
              return <tr key={s.id}><td><strong>{resource?.name ?? short(s.resource_id)}</strong></td><td><StatusChip value={s.status} /></td><td>{s.severity}</td><td><div>{s.summary}</div>{s.findings.length > 0 ? <div className="code">{s.findings.map((finding, index) => `${index + 1}. ${String(finding.code ?? finding.type ?? finding.severity ?? 'finding')}: ${String(finding.message ?? finding.summary ?? finding.detail ?? JSON.stringify(finding))}`).join('\n')}</div> : null}</td></tr>;
            })}</tbody></table></div>}
        </SectionCard>

        <SectionCard
          title="Opt-in patch / PR workflow"
          description={selectedAgent ? `Targets the ${selectedAgent.name} repo sub-agent. Read-only remains the default.` : 'Select a repo sub-agent (Scope → Repo sub-agent) to target a patch.'}
        >
          <div className="notice">Patch generation requires project policy <code>patch_generation=enabled</code> plus <code>patch:generate</code>; PR records require <code>open_pr=enabled</code>, <code>pr:write</code>, and explicit approval. This surface creates a patch proposal and PR approval record only — it does not mutate the source repo, push branches, run tests, deploy, or open GitHub PRs without a separate approved integration.</div>
          {selectedAgent ? <>
            <div className="grid">
              <Field label="Scope"><input className="input" value={patchScope} onChange={(e) => setPatchScope(e.target.value)} /></Field>
              <Field label="Repo-relative path"><input className="input" value={patchPath} onChange={(e) => setPatchPath(e.target.value)} /></Field>
              <Field label="Replacement for line 1"><textarea className="input" rows={4} value={patchContent} onChange={(e) => setPatchContent(e.target.value)} placeholder="New first-line content for a patch proposal" /></Field>
              <button type="button" className="btn secondary" disabled={patchBusy} onClick={() => void generatePatchProposal()}>{patchBusy ? 'Working…' : 'Generate opt-in patch proposal'}</button>
            </div>
            {patchProposal ? <div><div className="label">Patch proposal</div><div className="code">{patchProposal.diff_summary}<br />indexed_commit={short(patchProposal.indexed_commit)}<br />branch_moved={String(patchProposal.branch_moved)}<br />warnings={patchProposal.warnings.join(', ') || 'none'}</div><pre className="code-block light">{patchProposal.unified_diff}</pre><button type="button" className="btn" disabled={patchBusy || patchProposal.branch_moved} onClick={() => void recordPrApproval()}>Record PR approval</button></div> : null}
            {prRecord ? <div className="notice">PR approval record: {prRecord.status} · {prRecord.source_branch} → {prRecord.target_branch} · {prRecord.diff_summary}</div> : null}
          </> : <EmptyState text="No repo sub-agent selected. Switch Scope to Repo sub-agent and pick one to draft a patch." />}
        </SectionCard>
      </div> : null}
    </Card>
  </main>;
}
