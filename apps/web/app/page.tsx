'use client';

import { useState } from 'react';

interface SearchHit {
  resource_id: string;
  snapshot_id: string;
  path: string | null;
  title: string | null;
  ordinal: number;
  content_hash: string;
  version: string;
  version_kind: string;
  commit: string | null;
  snippet: string;
  score: number;
}

interface SearchResponse {
  query: string;
  count: number;
  hits: SearchHit[];
}

const DEFAULT_API =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:18000';

const panel: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: '1rem',
  padding: '1.5rem',
  boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
};

const label: React.CSSProperties = {
  display: 'block',
  fontSize: '0.8rem',
  fontWeight: 700,
  color: '#475569',
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  marginBottom: '0.35rem',
};

const input: React.CSSProperties = {
  width: '100%',
  padding: '0.6rem 0.75rem',
  borderRadius: '0.6rem',
  border: '1px solid #cbd5e1',
  fontSize: '0.95rem',
  boxSizing: 'border-box',
};

const endpoints: Array<[string, string]> = [
  ['POST', '/workspaces/{ws}/projects/{proj}/resources'],
  ['PATCH', '/workspaces/{ws}/projects/{proj}/resources/{res}'],
  ['POST', '/workspaces/{ws}/projects/{proj}/resources/{res}/refresh'],
  ['GET', '/workspaces/{ws}/projects/{proj}/resources/{res}/snapshots'],
  ['GET', '/workspaces/{ws}/projects/{proj}/resources/{res}/index-runs'],
  ['POST', '/workspaces/{ws}/projects/{proj}/search'],
];

export default function Home() {
  const [api, setApi] = useState(DEFAULT_API);
  const [email, setEmail] = useState('dev@example.com');
  const [workspaceId, setWorkspaceId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function runSearch(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setStatus(null);
    setHits([]);
    try {
      const res = await fetch(
        `${api}/workspaces/${workspaceId}/projects/${projectId}/search`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-User-Email': email,
          },
          body: JSON.stringify({ query, top_k: 10 }),
        },
      );
      if (!res.ok) {
        setStatus(`Search failed: HTTP ${res.status}`);
        return;
      }
      const data: SearchResponse = await res.json();
      setHits(data.hits);
      setStatus(`${data.count} result${data.count === 1 ? '' : 's'} for “${data.query}”`);
    } catch (err) {
      setStatus(`Request error: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', minHeight: '100vh', background: '#f8fafc' }}>
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '1.25rem 3rem',
          borderBottom: '1px solid #e2e8f0',
          background: '#ffffff',
        }}
      >
        <a
          href="/"
          style={{
            color: '#334155',
            fontWeight: 700,
            letterSpacing: '0.14em',
            textDecoration: 'none',
            textTransform: 'uppercase',
          }}
        >
          ContextSmith
        </a>
        <nav style={{ display: 'flex', gap: '1rem', fontSize: '0.95rem' }} aria-label="Primary">
          <a href={`${DEFAULT_API}/docs`} style={{ color: '#0f172a' }}>
            API Docs
          </a>
          <a href="/api/health" style={{ color: '#0f172a' }}>
            Frontend Health
          </a>
        </nav>
      </header>

      <section style={{ padding: '3rem 3rem 1.5rem', maxWidth: '980px' }}>
        <p style={{ color: '#475569', textTransform: 'uppercase', letterSpacing: '0.16em' }}>
          Milestone 2 · Resource Ingestion &amp; Lexical Search
        </p>
        <h1 style={{ fontSize: 'clamp(2rem, 5vw, 3.5rem)', lineHeight: 1.05, margin: '0 0 1rem' }}>
          Add resources, snapshot them, search the text.
        </h1>
        <p style={{ color: '#334155', fontSize: '1.1rem', lineHeight: 1.7, maxWidth: '760px' }}>
          Add a markdown/document resource (inline content) or a public/local git repository, run a
          manual refresh, and the worker produces a versioned source snapshot plus lexical chunks.
          Search returns chunk snippets with citations — resource, snapshot, path/title, ordinal, and
          commit/hash version.
        </p>
      </section>

      <section
        style={{
          display: 'grid',
          gap: '1.5rem',
          gridTemplateColumns: 'minmax(320px, 1fr) minmax(280px, 0.8fr)',
          padding: '0 3rem 4rem',
          maxWidth: '1200px',
          alignItems: 'start',
        }}
      >
        <form style={panel} onSubmit={runSearch} aria-label="Project lexical search">
          <h2 style={{ marginTop: 0 }}>Search a project</h2>
          <div style={{ display: 'grid', gap: '0.9rem' }}>
            <div style={{ display: 'grid', gap: '0.9rem', gridTemplateColumns: '1fr 1fr' }}>
              <div>
                <label style={label} htmlFor="api">API base URL</label>
                <input id="api" style={input} value={api} onChange={(e) => setApi(e.target.value)} />
              </div>
              <div>
                <label style={label} htmlFor="email">X-User-Email</label>
                <input id="email" style={input} value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
            </div>
            <div style={{ display: 'grid', gap: '0.9rem', gridTemplateColumns: '1fr 1fr' }}>
              <div>
                <label style={label} htmlFor="ws">Workspace ID</label>
                <input id="ws" style={input} placeholder="uuid" value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)} />
              </div>
              <div>
                <label style={label} htmlFor="proj">Project ID</label>
                <input id="proj" style={input} placeholder="uuid" value={projectId} onChange={(e) => setProjectId(e.target.value)} />
              </div>
            </div>
            <div>
              <label style={label} htmlFor="q">Query</label>
              <input id="q" style={input} placeholder="e.g. resource deletion" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
            <button
              type="submit"
              disabled={loading || !workspaceId || !projectId || !query}
              style={{
                background: loading ? '#64748b' : '#0f172a',
                color: '#ffffff',
                padding: '0.75rem 1rem',
                borderRadius: '0.6rem',
                border: 'none',
                fontWeight: 700,
                cursor: loading ? 'default' : 'pointer',
              }}
            >
              {loading ? 'Searching…' : 'Search'}
            </button>
          </div>

          {status ? (
            <p style={{ marginTop: '1rem', color: '#475569', fontWeight: 600 }}>{status}</p>
          ) : null}

          <div style={{ display: 'grid', gap: '0.75rem', marginTop: '1rem' }}>
            {hits.map((hit) => (
              <article
                key={`${hit.snapshot_id}-${hit.ordinal}-${hit.content_hash}`}
                style={{ border: '1px solid #e2e8f0', borderRadius: '0.75rem', padding: '0.85rem' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <strong style={{ color: '#0f172a' }}>{hit.title || hit.path || 'chunk'}</strong>
                  <span style={{ color: '#64748b', fontSize: '0.85rem' }}>score {hit.score.toFixed(4)}</span>
                </div>
                <p style={{ color: '#334155', lineHeight: 1.6, margin: '0.5rem 0' }}>{hit.snippet}</p>
                <div style={{ color: '#64748b', fontSize: '0.8rem', fontFamily: 'ui-monospace, monospace' }}>
                  {hit.path ? `path=${hit.path} · ` : ''}ordinal={hit.ordinal} · {hit.version_kind}=
                  {(hit.commit || hit.version).slice(0, 12)}
                </div>
              </article>
            ))}
          </div>
        </form>

        <aside style={{ display: 'grid', gap: '1.5rem' }}>
          <div style={panel}>
            <h2 style={{ marginTop: 0 }}>Ingest a resource</h2>
            <p style={{ color: '#334155', lineHeight: 1.6 }}>
              Create a document resource with inline content, then refresh it:
            </p>
            <pre
              style={{
                background: '#0f172a',
                color: '#e2e8f0',
                padding: '0.9rem',
                borderRadius: '0.6rem',
                overflowX: 'auto',
                fontSize: '0.78rem',
                lineHeight: 1.5,
              }}
            >
{`# document resource (inline content)
{
  "type": "markdown",
  "name": "Runbook",
  "uri": "doc://runbook",
  "source_config": { "content": "..." }
}

# git resource (https or local file://)
{
  "type": "git",
  "name": "Repo",
  "uri": "https://github.com/org/repo.git",
  "source_config": { "branch": "main" }
}`}
            </pre>
          </div>

          <div style={panel}>
            <h2 style={{ marginTop: 0 }}>M2 endpoints</h2>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
              {endpoints.map(([method, path]) => (
                <li key={`${method} ${path}`} style={{ fontSize: '0.82rem', fontFamily: 'ui-monospace, monospace' }}>
                  <span style={{ color: '#0369a1', fontWeight: 700 }}>{method}</span>{' '}
                  <span style={{ color: '#334155' }}>{path}</span>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </section>
    </main>
  );
}
