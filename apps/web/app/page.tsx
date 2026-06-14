const services = [
  ['API', 'http://localhost:18000/readyz', 'FastAPI ready endpoint'],
  ['Frontend', '/api/health', 'Next.js production health route'],
  ['Database', null, 'Postgres/pgvector verified by API readiness'],
  ['Queue', null, 'Redis/RQ verified by refresh smoke flow'],
];

export default function Home() {
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
          <a href="http://localhost:18000/docs" style={{ color: '#0f172a' }}>
            API Docs
          </a>
          <a href="/api/health" style={{ color: '#0f172a' }}>
            Frontend Health
          </a>
        </nav>
      </header>

      <section style={{ padding: '4rem 3rem 2rem', maxWidth: '980px' }}>
        <p style={{ color: '#475569', textTransform: 'uppercase', letterSpacing: '0.16em' }}>
          Milestone 1 Runtime Shell
        </p>
        <h1 style={{ fontSize: 'clamp(2.5rem, 6vw, 5rem)', lineHeight: 1, margin: '0 0 1rem' }}>
          Forge trusted context for every agent.
        </h1>
        <p style={{ color: '#334155', fontSize: '1.2rem', lineHeight: 1.7, maxWidth: '760px' }}>
          The Docker Compose stack boots the API, Postgres/pgvector, Redis, RQ worker, and
          production frontend together. The QA smoke flow creates a workspace, project, resource,
          refresh job, validates RQ completion, checks auth denial, and verifies this UI.
        </p>
        <div style={{ display: 'flex', gap: '1rem', marginTop: '2rem', flexWrap: 'wrap' }}>
          <a
            href="http://localhost:18000/docs"
            style={{
              background: '#0f172a',
              color: '#ffffff',
              padding: '0.85rem 1.1rem',
              borderRadius: '0.75rem',
              textDecoration: 'none',
              fontWeight: 700,
            }}
          >
            Open API Docs
          </a>
          <a
            href="/api/health"
            style={{
              background: '#e2e8f0',
              color: '#0f172a',
              padding: '0.85rem 1.1rem',
              borderRadius: '0.75rem',
              textDecoration: 'none',
              fontWeight: 700,
            }}
          >
            Check Frontend Health
          </a>
        </div>
      </section>

      <section
        aria-labelledby="service-status"
        style={{
          display: 'grid',
          gap: '1rem',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          padding: '0 3rem 4rem',
          maxWidth: '1100px',
        }}
      >
        <h2 id="service-status" style={{ gridColumn: '1 / -1', margin: '0 0 0.25rem' }}>
          Runtime status surfaces
        </h2>
        {services.map(([name, href, detail]) => (
          <article
            key={name}
            style={{
              background: '#ffffff',
              border: '1px solid #e2e8f0',
              borderRadius: '1rem',
              padding: '1rem',
              boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span
                aria-hidden="true"
                style={{ width: '0.65rem', height: '0.65rem', borderRadius: '50%', background: '#16a34a' }}
              />
              <h3 style={{ margin: 0 }}>{name}</h3>
            </div>
            <p style={{ color: '#475569', lineHeight: 1.5 }}>{detail}</p>
            {href ? (
              <a href={href} style={{ color: '#0369a1', fontWeight: 700 }}>
                Open check
              </a>
            ) : (
              <span style={{ color: '#64748b' }}>Verified by backend smoke flow</span>
            )}
          </article>
        ))}
      </section>
    </main>
  );
}
