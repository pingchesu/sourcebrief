'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { usePlatform } from '../lib/platform-context';
import { short } from '../lib/api';

type NavItem = { href: string; label: string };
type NavSection = { label?: string; secondary?: boolean; items: NavItem[] };

// Navigation is organized around the product workflow (build context → assure
// quality → ship the agent pack), not around backend module names. Advanced and
// admin surfaces are kept reachable but visually demoted in a secondary group.
const NAV_SECTIONS: NavSection[] = [
  { items: [{ href: '/', label: 'Command Center' }] },
  {
    label: 'Build context',
    items: [
      { href: '/sources', label: 'Sources' },
      { href: '/repo-agents', label: 'Workbench' },
      { href: '/ask', label: 'Ask & citations' },
    ],
  },
  {
    label: 'Assure quality',
    items: [
      { href: '/review', label: 'Review queue' },
      { href: '/evals', label: 'Retrieval evals' },
    ],
  },
  {
    label: 'Ship agent pack',
    items: [
      { href: '/agent-files', label: 'Agent files' },
      { href: '/agent-profile', label: 'Project agent' },
    ],
  },
  {
    label: 'Operations',
    secondary: true,
    items: [
      { href: '/maintenance', label: 'Maintenance' },
      { href: '/config', label: 'Configuration' },
      { href: '/users', label: 'Users & tokens' },
      { href: '/admin', label: 'Audit & admin' },
      { href: '/login', label: 'Session' },
    ],
  },
];

function isActive(pathname: string, href: string): boolean {
  return href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { agent, provider, workspace, project, settings, loading, error, reload } = usePlatform();

  const signedIn = Boolean(settings.bearer.trim() || settings.email.trim());
  const principal = settings.bearer.trim() ? 'Token session' : settings.email.trim() || 'Signed out';
  const providerStatus = provider?.status ?? (signedIn ? 'loading' : 'signed out');
  const providerChipClass = provider?.status === 'ok' ? 'ok' : signedIn ? 'warn' : '';

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-kicker">CONTEXTSMITH</div>
        <div className="brand-title">Context Console</div>
      </div>
      <nav className="nav" aria-label="Primary">
        {NAV_SECTIONS.map((section, index) => (
          <div key={section.label ?? `section-${index}`} className={`nav-section ${section.secondary ? 'secondary' : ''}`.trim()}>
            {section.label ? <div className="nav-section-label">{section.label}</div> : null}
            <div className="nav-group">
              {section.items.map((item) => (
                <Link key={item.href} href={item.href} className={`nav-link ${isActive(pathname, item.href) ? 'active' : ''}`.trim()} aria-current={isActive(pathname, item.href) ? 'page' : undefined}>
                  <span>{item.label}</span>
                </Link>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <strong>{agent?.name ?? 'Project agent'}</strong>
        <span>{workspace?.name ?? 'Workspace not loaded'}</span>
        <span>{project?.name ?? 'Project not loaded'}</span>
        <span className="code">{short(settings.workspaceId)} / {short(settings.projectId)}</span>
      </div>
    </aside>
    <section className="main">
      <header className="topbar">
        <div className="topbar-identity">
          <strong>{workspace?.name ?? 'ContextSmith'}{project ? ` · ${project.name}` : ''}</strong>
          <div className="topbar-meta">
            <span>{agent?.name ?? (signedIn ? 'Agent loading…' : 'No active session')}</span>
            <span>{signedIn ? `Signed in as ${principal}` : 'No active session'}</span>
            <span>{provider ? `${provider.embedding.provider}/${provider.embedding.model}` : 'provider not loaded'}</span>
            {error ? <span className="code" style={{ color: 'var(--risk)' }}>{error}</span> : null}
          </div>
        </div>
        <div className="toolbar">
          <span className={`chip ${providerChipClass}`.trim()}>{providerStatus}</span>
          <Link className="btn secondary" href="/login">Session</Link>
          <button className="btn secondary" onClick={() => reload()} disabled={loading}>{loading ? 'Loading…' : 'Reload'}</button>
        </div>
      </header>
      {children}
    </section>
  </div>;
}
