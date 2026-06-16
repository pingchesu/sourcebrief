'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader, Card, EmptyState, Field, Metric, StatusChip } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import type { RetrievalEvalQuestion, RetrievalEvalResponse, RetrievalEvalRunList } from '../../lib/types';

function safeJson(value: unknown) { return JSON.stringify(value, null, 2); }

export default function QualityEvalsPage() {
  const { settings, client, resources, provider } = usePlatform();
  const indexedResources = useMemo(() => resources.filter((resource) => resource.current_snapshot_id && resource.retrieval_enabled && resource.status === 'active'), [resources]);
  const [selectedId, setSelectedId] = useState(indexedResources[0]?.id ?? '');
  const selected = indexedResources.find((resource) => resource.id === selectedId) ?? indexedResources[0] ?? null;
  const [questionsJson, setQuestionsJson] = useState('');
  const [result, setResult] = useState<RetrievalEvalResponse | null>(null);
  const [history, setHistory] = useState<RetrievalEvalRunList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);

  async function loadHistory() {
    setHistoryBusy(true);
    try {
      const response = await client<RetrievalEvalRunList>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/retrieval-evals?limit=20`);
      setHistory(response);
    } catch (err) {
      setError(String(err));
    } finally {
      setHistoryBusy(false);
    }
  }

  useEffect(() => { void loadHistory(); }, [settings.workspaceId, settings.projectId]);

  function seedQuestions() {
    if (!selected) return;
    const seeded: RetrievalEvalQuestion[] = [
      {
        id: 'repo-responsibility',
        query: `What is ${selected.name} responsible for? Cite exact files.`,
        expected_resource_ids: [selected.id],
        resource_ids: [selected.id],
        min_citations: 1,
        top_k: 8,
        include_code_symbols: true,
      },
      {
        id: 'repo-entrypoints-config',
        query: `Show ${selected.name}'s main entrypoints, config files, and runtime boundaries.`,
        expected_resource_ids: [selected.id],
        resource_ids: [selected.id],
        min_citations: 1,
        top_k: 10,
        include_code_symbols: true,
      },
    ];
    setQuestionsJson(safeJson(seeded));
  }

  async function runEval(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(null); setResult(null);
    try {
      const questions = JSON.parse(questionsJson || '[]') as RetrievalEvalQuestion[];
      const response = await client<RetrievalEvalResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/retrieval-evals`, {
        method: 'POST',
        body: JSON.stringify({ runtime: 'hermes', max_chars: 10000, questions }),
      });
      setResult(response);
      await loadHistory();
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  async function loadRun(runId: string) {
    setBusy(true); setError(null);
    try {
      const response = await client<RetrievalEvalResponse>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/retrieval-evals/${runId}`);
      setResult(response);
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  return <main className="page">
    <PageHeader eyebrow="Quality Evals" title="Retrieval quality gate" description="Run and persist project-level golden questions against the real agent-context path. History makes embedding/rerank/graph changes comparable instead of one-off guesses." actions={<button className="btn secondary" disabled={!selected} onClick={seedQuestions}>Seed from selected repo</button>} />
    <div className="grid four"><Metric label="Indexed resources" value={indexedResources.length} /><Metric label="Provider" value={provider?.embedding?.provider ?? '—'} /><Metric label="Model" value={provider?.embedding?.model ?? '—'} /><Metric label="Last eval" value={history?.runs[0]?.status ?? result?.summary.status ?? 'not run'} /></div>
    <div className="grid two">
      <Card>
        <h2>Golden questions</h2>
        {indexedResources.length === 0 ? <EmptyState text="Index at least one resource before running evals." /> : <form className="grid" onSubmit={runEval}>
          <Field label="Seed resource"><select className="input" value={selected?.id ?? ''} onChange={(event) => setSelectedId(event.target.value)}>{indexedResources.map((resource) => <option key={resource.id} value={resource.id}>{resource.name} — {resource.type}</option>)}</select></Field>
          <Field label="Questions JSON"><textarea className="input" rows={18} value={questionsJson} onChange={(event) => setQuestionsJson(event.target.value)} placeholder="Click Seed from selected repo or paste RetrievalEvalQuestion[] JSON." /></Field>
          <button className="btn" disabled={busy || !questionsJson.trim()}>{busy ? 'Running…' : 'Run retrieval eval'}</button>
        </form>}
        {error ? <div className="notice error">{error}</div> : null}
      </Card>
      <Card>
        <h2>Eval summary</h2>
        {!result ? <EmptyState text="No eval result selected yet. Run an eval or load a historical run." /> : <div className="grid">
          <div className="grid four"><Metric label="Status" value={result.summary.status} /><Metric label="Pass rate" value={`${Math.round(result.summary.pass_rate * 100)}%`} /><Metric label="Passed" value={result.summary.passed_count} /><Metric label="Avg latency" value={`${result.summary.avg_latency_ms}ms`} /></div>
          <div className="notice">Run {result.run_id ?? 'not persisted'} · Provider {result.provider}/{result.model}; vector status {(result.diagnostics.vector_status as string) ?? 'unknown'}; embedding namespace {(result.diagnostics.embedding_namespace as string) ?? 'unknown'}.</div>
          {result.summary.failure_reasons.length ? <div className="notice error">{result.summary.failure_reasons.join('\n')}</div> : null}
        </div>}
      </Card>
    </div>
    <Card>
      <h2>Eval history</h2>
      {historyBusy ? <EmptyState text="Loading historical eval runs…" /> : !history?.runs.length ? <EmptyState text="No persisted eval runs yet." /> : <div className="table-wrap"><table><thead><tr><th>Status</th><th>Created</th><th>Questions</th><th>Pass rate</th><th>Provider</th><th>Scope</th><th></th></tr></thead><tbody>{history.runs.map((run) => <tr key={run.id}><td><StatusChip value={run.status} /></td><td>{new Date(run.created_at).toLocaleString()}</td><td>{run.question_count}</td><td>{Math.round(run.pass_rate * 100)}%</td><td>{run.provider}/{run.model}</td><td>{run.project_wide ? 'project-wide' : `${run.resource_ids.length} resource(s)`}</td><td><button className="btn secondary" onClick={() => void loadRun(run.id)} disabled={busy}>Load</button></td></tr>)}</tbody></table></div>}
    </Card>
    {result ? <Card>
      <h2>Question results</h2>
      <div className="table-wrap"><table><thead><tr><th>Status</th><th>ID</th><th>Citations</th><th>Symbols</th><th>Latency</th><th>Failures</th></tr></thead><tbody>{result.results.map((row) => <tr key={row.id}><td><StatusChip value={row.passed ? 'passed' : 'failed'} /></td><td>{row.id}</td><td>{row.citation_count}</td><td>{row.symbol_count}</td><td>{row.latency_ms}ms</td><td>{row.failure_reasons.join(', ') || '—'}</td></tr>)}</tbody></table></div>
      <pre className="code-block light">{safeJson(result.results.flatMap((row) => row.hit_quality.map((hit) => ({ question: row.id, ...hit })))).slice(0, 6000)}</pre>
    </Card> : null}
  </main>;
}
