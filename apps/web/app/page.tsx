'use client';

import { type CSSProperties, type FormEvent, useState } from 'react';

const DEFAULT_API = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:18000';
const DEFAULT_SCOPES = 'project:read,project:query,resource:read,resource:write,resource:refresh,review:read,review:write,token:admin';

type ProviderHealth = {
  status: string;
  embedding: { namespace: string; dev_quality: boolean; status: string; provider: string; model: string };
};

type Workspace = { id: string; name: string; slug: string };
type Project = { id: string; workspace_id: string; name: string; description: string | null; visibility: string };
type Resource = {
  id: string;
  type: string;
  name: string;
  uri: string;
  status: string;
  retrieval_enabled: boolean;
  update_frequency: string;
  current_snapshot_id: string | null;
  review_status: string;
  last_reviewed_at: string | null;
  next_refresh_at: string | null;
  last_refresh_finished_at: string | null;
};
type IndexRun = { id: string; resource_id: string; status: string; trigger: string; error_message: string | null; finished_at: string | null };
type ReviewItem = { resource: Resource; freshness_status: string; usage_count: number; last_index_status: string | null; stale_reasons: string[] };
type UsageItem = { resource_id: string; query_count: number; hit_count: number; context_packet_count: number; last_used_at: string | null };
type ApiToken = { id: string; name: string; scopes: string[]; allowed_project_ids: string[] | null; allowed_resource_ids: string[] | null; revoked_at: string | null; created_at: string | null; last_used_at: string | null };
type TokenCreateResponse = { token: string; api_token: ApiToken };
type AgentCitation = { resource_id: string; chunk_id: string; path: string | null; title: string | null; ordinal: number; score: number; graph_score: number; version: string; version_kind: string };
type AgentContextResponse = { query: string; runtime: string; instruction: string; context: string; citations: AgentCitation[]; token_budget_hint: number };

type Notice = { tone: 'info' | 'success' | 'error'; text: string } | null;

const page: CSSProperties = { fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif', minHeight: '100vh', background: '#f8fafc', color: '#0f172a' };
const panel: CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 18, padding: 20, boxShadow: '0 1px 2px rgba(15,23,42,.04)' };
const label: CSSProperties = { display: 'block', fontSize: 12, fontWeight: 800, color: '#475569', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 6 };
const input: CSSProperties = { width: '100%', boxSizing: 'border-box', border: '1px solid #cbd5e1', borderRadius: 10, padding: '10px 12px', fontSize: 14, background: '#fff' };
const button: CSSProperties = { border: 0, borderRadius: 10, padding: '10px 14px', fontWeight: 800, background: '#0f172a', color: '#fff', cursor: 'pointer' };
const secondaryButton: CSSProperties = { ...button, background: '#e2e8f0', color: '#0f172a' };
const dangerButton: CSSProperties = { ...button, background: '#b91c1c' };
const code: CSSProperties = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12, color: '#475569' };

function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || `workspace-${Date.now()}`;
}

function splitCsv(value: string): string[] {
  return value.split(',').map((part) => part.trim()).filter(Boolean);
}

function short(id?: string | null): string {
  return id ? id.slice(0, 8) : '—';
}

export default function Home() {
  const [api, setApi] = useState(DEFAULT_API);
  const [email, setEmail] = useState('dev@example.com');
  const [bearer, setBearer] = useState('');
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(false);

  const [workspaceName, setWorkspaceName] = useState('Alpha Workspace');
  const [projectName, setProjectName] = useState('ContextSmith Alpha Project');
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [workspaceId, setWorkspaceId] = useState('');
  const [projectId, setProjectId] = useState('');

  const [provider, setProvider] = useState<ProviderHealth | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [usageItems, setUsageItems] = useState<UsageItem[]>([]);
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [lastRun, setLastRun] = useState<IndexRun | null>(null);
  const [selectedResourceId, setSelectedResourceId] = useState('');

  const [resourceType, setResourceType] = useState<'markdown' | 'upload' | 'url' | 'git'>('markdown');
  const [resourceName, setResourceName] = useState('Runbook');
  const [resourceUri, setResourceUri] = useState('doc://runbook');
  const [resourceContent, setResourceContent] = useState('ContextSmith alpha console resource. Marker webconsole.');
  const [resourceUrl, setResourceUrl] = useState('https://example.com');
  const [resourceBranch, setResourceBranch] = useState('main');
  const [resourceFrequency, setResourceFrequency] = useState('manual');

  const [reviewStatus, setReviewStatus] = useState('approved');
  const [reviewNote, setReviewNote] = useState('Reviewed from web console');

  const [tokenName, setTokenName] = useState('Hermes console token');
  const [tokenScopes, setTokenScopes] = useState(DEFAULT_SCOPES);
  const [tokenProjectScoped, setTokenProjectScoped] = useState(true);
  const [tokenResourceScoped, setTokenResourceScoped] = useState(false);
  const [plaintextToken, setPlaintextToken] = useState('');

  const [question, setQuestion] = useState('What does the webconsole marker prove?');
  const [agentContext, setAgentContext] = useState<AgentContextResponse | null>(null);

  function authHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (bearer.trim()) headers.Authorization = `Bearer ${bearer.trim()}`;
    else headers['X-User-Email'] = email;
    return headers;
  }

  async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${api}${path}`, { ...init, headers: { ...authHeaders(), ...(init.headers ?? {}) } });
    const text = await response.text();
    const body = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const detail = body?.detail ? `: ${JSON.stringify(body.detail)}` : '';
      throw new Error(`HTTP ${response.status}${detail}`);
    }
    return body as T;
  }

  function ids(): { ws: string; proj: string } {
    const ws = workspace?.id || workspaceId;
    const proj = project?.id || projectId;
    if (!ws || !proj) throw new Error('Workspace ID and Project ID are required');
    return { ws, proj };
  }

  async function runAction(name: string, fn: () => Promise<void>) {
    setLoading(true);
    setNotice({ tone: 'info', text: `${name}…` });
    try {
      await fn();
      setNotice({ tone: 'success', text: `${name} completed` });
    } catch (error) {
      setNotice({ tone: 'error', text: `${name} failed: ${String(error)}` });
    } finally {
      setLoading(false);
    }
  }

  async function loadDashboard(wsArg?: string, projArg?: string) {
    const ws = wsArg || workspace?.id || workspaceId;
    const proj = projArg || project?.id || projectId;
    if (!ws || !proj) return;
    const [providerHealth, nextResources, review, usage, tokenList] = await Promise.all([
      apiFetch<ProviderHealth>('/provider-health'),
      apiFetch<Resource[]>(`/workspaces/${ws}/projects/${proj}/resources`),
      apiFetch<{ resources: ReviewItem[] }>(`/workspaces/${ws}/projects/${proj}/resource-review`),
      apiFetch<{ resources: UsageItem[] }>(`/workspaces/${ws}/projects/${proj}/resource-usage`),
      apiFetch<ApiToken[]>(`/workspaces/${ws}/api-tokens`),
    ]);
    setProvider(providerHealth);
    setResources(nextResources);
    setReviewItems(review.resources);
    setUsageItems(usage.resources);
    setTokens(tokenList);
    if (!selectedResourceId && nextResources[0]) setSelectedResourceId(nextResources[0].id);
  }

  async function bootstrap(event: FormEvent) {
    event.preventDefault();
    await runAction('Create workspace/project', async () => {
      const slug = `${slugify(workspaceName)}-${Date.now().toString(36)}`;
      const nextWorkspace = await apiFetch<Workspace>('/workspaces', {
        method: 'POST',
        body: JSON.stringify({ name: workspaceName, slug }),
      });
      const nextProject = await apiFetch<Project>(`/workspaces/${nextWorkspace.id}/projects`, {
        method: 'POST',
        body: JSON.stringify({ name: projectName, description: 'Created from SaaS alpha console' }),
      });
      setWorkspace(nextWorkspace);
      setProject(nextProject);
      setPlaintextToken('');
      setWorkspaceId(nextWorkspace.id);
      setProjectId(nextProject.id);
      await loadDashboard(nextWorkspace.id, nextProject.id);
    });
  }

  async function addResource(event: FormEvent) {
    event.preventDefault();
    await runAction('Create resource', async () => {
      const { ws, proj } = ids();
      const payload = (() => {
        if (resourceType === 'url') {
          return { type: 'url', name: resourceName, uri: resourceUrl, update_frequency: resourceFrequency, source_config: { url: resourceUrl } };
        }
        if (resourceType === 'git') {
          return { type: 'git', name: resourceName, uri: resourceUri, update_frequency: resourceFrequency, source_config: { url: resourceUri, branch: resourceBranch } };
        }
        if (resourceType === 'upload') {
          return { type: 'upload', name: resourceName, uri: resourceUri || `upload://${resourceName}`, update_frequency: resourceFrequency, source_config: { filename: resourceName, content_type: 'text/markdown', content: resourceContent } };
        }
        return { type: 'markdown', name: resourceName, uri: resourceUri, update_frequency: resourceFrequency, source_config: { content: resourceContent } };
      })();
      const created = await apiFetch<Resource>(`/workspaces/${ws}/projects/${proj}/resources`, { method: 'POST', body: JSON.stringify(payload) });
      setSelectedResourceId(created.id);
      await loadDashboard(ws, proj);
    });
  }

  async function refreshSelected() {
    await runAction('Refresh selected resource', async () => {
      const { ws, proj } = ids();
      if (!selectedResourceId) throw new Error('Select a resource first');
      const run = await apiFetch<IndexRun>(`/workspaces/${ws}/projects/${proj}/resources/${selectedResourceId}/refresh`, { method: 'POST' });
      setLastRun(run);
      await loadDashboard(ws, proj);
    });
  }

  async function pollRun() {
    await runAction('Poll latest index run', async () => {
      const { ws } = ids();
      if (!lastRun) throw new Error('No index run yet');
      const run = await apiFetch<IndexRun>(`/workspaces/${ws}/index-runs/${lastRun.id}`);
      setLastRun(run);
      await loadDashboard();
    });
  }

  async function submitReview(event: FormEvent) {
    event.preventDefault();
    await runAction('Save review', async () => {
      const { ws, proj } = ids();
      if (!selectedResourceId) throw new Error('Select a resource first');
      await apiFetch<Resource>(`/workspaces/${ws}/projects/${proj}/resources/${selectedResourceId}/review`, {
        method: 'POST',
        body: JSON.stringify({ review_status: reviewStatus, review_note: reviewNote, stale_after_days: 30 }),
      });
      await loadDashboard(ws, proj);
    });
  }

  async function createToken(event: FormEvent) {
    event.preventDefault();
    await runAction('Create API token', async () => {
      const ws = workspace?.id || workspaceId;
      const proj = project?.id || projectId;
      if (!ws) throw new Error('Workspace ID is required');
      if (tokenProjectScoped && !proj) throw new Error('Project ID is required for project-scoped tokens');
      if (tokenResourceScoped && !selectedResourceId) throw new Error('Select a resource for resource-scoped tokens');
      const created = await apiFetch<TokenCreateResponse>(`/workspaces/${ws}/api-tokens`, {
        method: 'POST',
        body: JSON.stringify({
          name: tokenName,
          scopes: splitCsv(tokenScopes),
          allowed_project_ids: tokenProjectScoped && proj ? [proj] : null,
          allowed_resource_ids: tokenResourceScoped ? [selectedResourceId] : null,
        }),
      });
      setPlaintextToken(created.token);
      await loadDashboard(ws, proj);
    });
  }

  async function revokeToken(id: string) {
    await runAction('Revoke token', async () => {
      const { ws } = ids();
      await apiFetch<ApiToken>(`/workspaces/${ws}/api-tokens/${id}`, { method: 'DELETE' });
      await loadDashboard();
    });
  }

  async function askAgent(event: FormEvent) {
    event.preventDefault();
    await runAction('Ask project agent', async () => {
      const { ws, proj } = ids();
      const response = await apiFetch<AgentContextResponse>(`/workspaces/${ws}/projects/${proj}/agent-context`, {
        method: 'POST',
        body: JSON.stringify({ query: question, runtime: 'hermes', resource_ids: selectedResourceId ? [selectedResourceId] : null, top_k: 6, max_chars: 12000 }),
      });
      setAgentContext(response);
      await loadDashboard(ws, proj);
    });
  }

  const usageByResource = new Map(usageItems.map((item) => [item.resource_id, item]));
  const noticeStyle: CSSProperties = {
    ...panel,
    borderColor: notice?.tone === 'error' ? '#fecaca' : notice?.tone === 'success' ? '#bbf7d0' : '#bae6fd',
    background: notice?.tone === 'error' ? '#fef2f2' : notice?.tone === 'success' ? '#f0fdf4' : '#f0f9ff',
  };

  return (
    <main style={page}>
      <header style={{ padding: '22px 32px', background: '#fff', borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 900, letterSpacing: '.16em', color: '#0369a1', textTransform: 'uppercase' }}>ContextSmith</div>
          <h1 style={{ margin: '4px 0 0', fontSize: 28 }}>SaaS Alpha Console</h1>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <a href={`${api}/docs`} style={{ color: '#0369a1', fontWeight: 700 }}>API docs</a>
          <a href="/api/health" style={{ color: '#0369a1', fontWeight: 700 }}>Frontend health</a>
        </div>
      </header>

      <section style={{ padding: 32, display: 'grid', gap: 18, gridTemplateColumns: 'minmax(320px, 430px) minmax(520px, 1fr)', alignItems: 'start' }}>
        <div style={{ display: 'grid', gap: 18 }}>
          <section style={panel} aria-label="Connection settings">
            <h2 style={{ marginTop: 0 }}>Connection</h2>
            <div style={{ display: 'grid', gap: 12 }}>
              <div><label style={label}>API base URL</label><input style={input} value={api} onChange={(e) => setApi(e.target.value)} /></div>
              <div><label style={label}>Dev user email</label><input style={input} value={email} onChange={(e) => setEmail(e.target.value)} /></div>
              <div><label style={label}>Bearer token (optional)</label><input style={input} type="password" value={bearer} onChange={(e) => setBearer(e.target.value)} placeholder="Only use after token creation" /></div>
              <button style={secondaryButton} type="button" onClick={() => runAction('Load dashboard', () => loadDashboard())} disabled={loading || !(workspaceId && projectId)}>Load dashboard</button>
            </div>
          </section>

          <form style={panel} onSubmit={bootstrap} aria-label="Create workspace and project">
            <h2 style={{ marginTop: 0 }}>1. Workspace / Project</h2>
            <div style={{ display: 'grid', gap: 12 }}>
              <div><label style={label}>Workspace name</label><input style={input} value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} /></div>
              <div><label style={label}>Project name</label><input style={input} value={projectName} onChange={(e) => setProjectName(e.target.value)} /></div>
              <button style={button} disabled={loading} type="submit">Create workspace + project</button>
              <div><label style={label}>Workspace ID</label><input style={input} value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)} placeholder="uuid" /></div>
              <div><label style={label}>Project ID</label><input style={input} value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="uuid" /></div>
            </div>
          </form>

          <form style={panel} onSubmit={addResource} aria-label="Create resource">
            <h2 style={{ marginTop: 0 }}>2. Add resource</h2>
            <div style={{ display: 'grid', gap: 12 }}>
              <div><label style={label}>Type</label><select style={input} value={resourceType} onChange={(e) => setResourceType(e.target.value as 'markdown' | 'upload' | 'url' | 'git')}><option value="markdown">Markdown document</option><option value="upload">Upload text</option><option value="url">Public URL</option><option value="git">Git repository</option></select></div>
              <div><label style={label}>Name</label><input style={input} value={resourceName} onChange={(e) => setResourceName(e.target.value)} /></div>
              <div><label style={label}>{resourceType === 'url' ? 'URL' : resourceType === 'git' ? 'Git URL / local file URI' : 'URI'}</label><input style={input} value={resourceType === 'url' ? resourceUrl : resourceUri} onChange={(e) => resourceType === 'url' ? setResourceUrl(e.target.value) : setResourceUri(e.target.value)} /></div>
              {resourceType === 'git' ? <div><label style={label}>Branch / ref</label><input style={input} value={resourceBranch} onChange={(e) => setResourceBranch(e.target.value)} placeholder="main" /></div> : null}
              <div><label style={label}>Update frequency</label><input style={input} value={resourceFrequency} onChange={(e) => setResourceFrequency(e.target.value)} placeholder="manual, daily, 6h" /></div>
              {resourceType === 'markdown' || resourceType === 'upload' ? <div><label style={label}>Content</label><textarea style={{ ...input, minHeight: 120 }} value={resourceContent} onChange={(e) => setResourceContent(e.target.value)} /></div> : null}
              <button style={button} disabled={loading || !(workspaceId && projectId)} type="submit">Create resource</button>
            </div>
          </form>

          <form style={panel} onSubmit={createToken} aria-label="Token management">
            <h2 style={{ marginTop: 0 }}>3. Token management</h2>
            <div style={{ display: 'grid', gap: 12 }}>
              <div><label style={label}>Token name</label><input style={input} value={tokenName} onChange={(e) => setTokenName(e.target.value)} /></div>
              <div><label style={label}>Scopes</label><textarea style={{ ...input, minHeight: 72 }} value={tokenScopes} onChange={(e) => setTokenScopes(e.target.value)} /></div>
              <label><input type="checkbox" checked={tokenProjectScoped} onChange={(e) => setTokenProjectScoped(e.target.checked)} /> Restrict to this project</label>
              <label><input type="checkbox" checked={tokenResourceScoped} onChange={(e) => setTokenResourceScoped(e.target.checked)} /> Restrict to selected resource</label>
              <button style={button} disabled={loading || !workspaceId || (tokenProjectScoped && !projectId) || (tokenResourceScoped && !selectedResourceId)} type="submit">Create token</button>
              {plaintextToken ? <div style={{ border: '1px solid #fde68a', background: '#fffbeb', padding: 12, borderRadius: 10 }}><strong>Copy now:</strong><pre style={{ ...code, whiteSpace: 'pre-wrap' }}>{plaintextToken}</pre><span style={{ color: '#92400e' }}>Plaintext is only shown once.</span><div style={{ marginTop: 8 }}><button style={secondaryButton} type="button" onClick={() => setPlaintextToken('')}>Dismiss copied token</button></div></div> : null}
            </div>
          </form>
        </div>

        <div style={{ display: 'grid', gap: 18 }}>
          {notice ? <div style={noticeStyle}>{notice.text}</div> : null}

          <section style={panel} aria-label="Platform status">
            <h2 style={{ marginTop: 0 }}>Status</h2>
            <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(4, minmax(120px, 1fr))' }}>
              <Metric label="Workspace" value={workspace?.name || short(workspaceId)} />
              <Metric label="Project" value={project?.name || short(projectId)} />
              <Metric label="Resources" value={String(resources.length)} />
              <Metric label="Provider" value={provider ? `${provider.embedding.provider}/${provider.embedding.model}` : 'not loaded'} />
            </div>
            {provider ? <p style={{ ...code, marginBottom: 0 }}>namespace={provider.embedding.namespace} · dev_quality={String(provider.embedding.dev_quality)}</p> : <p style={{ color: '#64748b' }}>Load dashboard to verify provider health.</p>}
          </section>

          <section style={panel} aria-label="Resources">
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
              <h2 style={{ margin: 0 }}>Resources</h2>
              <div style={{ display: 'flex', gap: 8 }}><button style={secondaryButton} onClick={refreshSelected} disabled={loading || !selectedResourceId}>Refresh</button><button style={secondaryButton} onClick={pollRun} disabled={loading || !lastRun}>Poll run</button></div>
            </div>
            {lastRun ? <p style={code}>last run {short(lastRun.id)} · {lastRun.status}{lastRun.error_message ? ` · ${lastRun.error_message}` : ''}</p> : null}
            {resources.length === 0 ? <Empty text="No resources yet. Add one from the left panel." /> : <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse' }}><thead><tr><Th>Name</Th><Th>Status</Th><Th>Review</Th><Th>Usage</Th><Th>Snapshot</Th></tr></thead><tbody>{resources.map((resource) => { const usage = usageByResource.get(resource.id); return <tr key={resource.id} onClick={() => setSelectedResourceId(resource.id)} style={{ background: selectedResourceId === resource.id ? '#eff6ff' : '#fff', cursor: 'pointer' }}><Td><strong>{resource.name}</strong><div style={code}>{resource.type} · {short(resource.id)}</div></Td><Td>{resource.status}<div style={code}>{resource.retrieval_enabled ? 'retrieval on' : 'retrieval off'}</div></Td><Td>{resource.review_status}</Td><Td>{usage ? `${usage.hit_count} hits / ${usage.context_packet_count} packets` : '—'}</Td><Td>{short(resource.current_snapshot_id)}</Td></tr>; })}</tbody></table></div>}
          </section>

          <form style={panel} onSubmit={submitReview} aria-label="Resource review">
            <h2 style={{ marginTop: 0 }}>Review / cleanup</h2>
            <div style={{ display: 'grid', gap: 12, gridTemplateColumns: '180px 1fr auto' }}>
              <select style={input} value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)}><option value="approved">approved</option><option value="needs_update">needs_update</option><option value="stale">stale</option><option value="ignored">ignored</option><option value="unreviewed">unreviewed</option></select>
              <input style={input} value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder="Review note" />
              <button style={button} disabled={loading || !selectedResourceId} type="submit">Save review</button>
            </div>
            {reviewItems.length === 0 ? <Empty text="No review rows yet." /> : <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>{reviewItems.slice(0, 5).map((item) => <div key={item.resource.id} style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 10 }}><strong>{item.resource.name}</strong> · {item.freshness_status} · usage {item.usage_count}<div style={code}>{item.stale_reasons.join(', ') || 'no stale reasons'}</div></div>)}</div>}
          </form>

          <section style={panel} aria-label="API tokens">
            <h2 style={{ marginTop: 0 }}>Tokens</h2>
            {tokens.length === 0 ? <Empty text="No tokens yet. Create one from the left panel." /> : <div style={{ display: 'grid', gap: 8 }}>{tokens.map((token) => <div key={token.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, border: '1px solid #e2e8f0', borderRadius: 10, padding: 10 }}><div><strong>{token.name}</strong><div style={code}>{token.scopes.join(', ')} · {token.revoked_at ? 'revoked' : 'active'}</div></div><button style={dangerButton} onClick={() => revokeToken(token.id)} disabled={Boolean(token.revoked_at)}>Revoke</button></div>)}</div>}
          </section>

          <form style={panel} onSubmit={askAgent} aria-label="Agent context">
            <h2 style={{ marginTop: 0 }}>Ask project agent</h2>
            <div style={{ display: 'grid', gap: 12 }}>
              <input style={input} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask a question across indexed resources" />
              <button style={button} disabled={loading || !(workspaceId && projectId)} type="submit">Ask with Hermes runtime</button>
            </div>
            {agentContext ? <article style={{ marginTop: 14 }}><div style={code}>runtime={agentContext.runtime} · citations={agentContext.citations.length} · budget={agentContext.token_budget_hint}</div><pre style={{ background: '#0f172a', color: '#e2e8f0', padding: 14, borderRadius: 12, whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto' }}>{agentContext.context}</pre><div style={{ display: 'grid', gap: 8 }}>{agentContext.citations.map((citation) => <div key={citation.chunk_id} style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 10 }}><strong>{citation.title || citation.path || short(citation.chunk_id)}</strong><div style={code}>score={citation.score.toFixed(3)} · ordinal={citation.ordinal} · {citation.version_kind}={short(citation.version)}</div></div>)}</div></article> : <Empty text="Ask after indexing a resource to inspect cited context." />}
          </form>
        </div>
      </section>
    </main>
  );
}

function Metric({ label: metricLabel, value }: { label: string; value: string }) {
  return <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, padding: 12 }}><div style={label}>{metricLabel}</div><strong>{value}</strong></div>;
}

function Empty({ text }: { text: string }) {
  return <p style={{ color: '#64748b', fontStyle: 'italic' }}>{text}</p>;
}

function Th({ children }: { children: React.ReactNode }) { return <th style={{ textAlign: 'left', borderBottom: '1px solid #e2e8f0', padding: 10, color: '#475569', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.08em' }}>{children}</th>; }
function Td({ children }: { children: React.ReactNode }) { return <td style={{ borderBottom: '1px solid #e2e8f0', padding: 10, verticalAlign: 'top' }}>{children}</td>; }
