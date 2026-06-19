'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { usePlatform } from '../lib/platform-context';

type NavItem = { href: string; label: string };
type NavSection = { label?: string; secondary?: boolean; items: NavItem[] };

const NAV_SECTIONS: NavSection[] = [
  { items: [{ href: '/', label: 'Command Center' }] },
  { label: 'Build context', items: [{ href: '/sources', label: 'Sources' }, { href: '/workbench', label: 'Workbench' }] },
  { label: 'Assure quality', items: [{ href: '/quality', label: 'Quality' }] },
  { label: 'Ship', items: [{ href: '/agent-profile', label: 'Project agent' }, { href: '/repo-agents', label: 'Repo agents' }, { href: '/graphs', label: 'Graphs' }] },
  { label: 'Administration', secondary: true, items: [{ href: '/users', label: 'Team access' }, { href: '/config', label: 'Settings' }, { href: '/login', label: 'Account' }] },
];

function isActive(pathname: string, href: string): boolean {
  return href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { agent, provider, workspace, project, currentUser, signedIn, loading, error, reload } = usePlatform();
  const providerStatus = provider?.status ?? (signedIn ? 'loading' : 'signed out');
  const providerChipClass = provider?.status === 'ok' ? 'ok' : signedIn ? 'warn' : '';
  const principal = currentUser?.display_name || currentUser?.email || 'Signed out';

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-kicker">CONTEXTSMITH</div><div className="brand-title">Context Console</div></div>
      <nav className="nav" aria-label="Primary">
        {NAV_SECTIONS.map((section, index) => <div key={section.label ?? `section-${index}`} className={`nav-section ${section.secondary ? 'secondary' : ''}`.trim()}>
          {section.label ? <div className="nav-section-label">{section.label}</div> : null}
          <div className="nav-group">{section.items.map((item) => <Link key={item.href} href={item.href} className={`nav-link ${isActive(pathname, item.href) ? 'active' : ''}`.trim()} aria-current={isActive(pathname, item.href) ? 'page' : undefined}><span>{item.label}</span></Link>)}</div>
        </div>)}
      </nav>
      <div className="sidebar-footer"><strong>{agent?.name ?? 'Project agent'}</strong><span>{workspace?.name ?? 'Workspace not loaded'}</span><span>{project?.name ?? 'Project not loaded'}</span></div>
    </aside>
    <section className="main">
      <header className="topbar">
        <div className="topbar-identity">
          <strong>{workspace?.name ?? 'ContextSmith'}{project ? ` · ${project.name}` : ''}</strong>
          <div className="topbar-meta"><span>{agent?.name ?? (signedIn ? 'Agent loading…' : 'No active session')}</span><span>{signedIn ? `Signed in as ${principal}` : 'No active session'}</span><span>{provider ? `${provider.embedding.provider}/${provider.embedding.model}` : 'provider not loaded'}</span>{error ? <span style={{ color: 'var(--risk)' }}>{error}</span> : null}</div>
        </div>
        <div className="toolbar"><span className={`chip ${providerChipClass}`.trim()}>{providerStatus}</span><Link className="btn secondary" href="/login">Account</Link><button className="btn secondary" onClick={() => reload()} disabled={loading || !signedIn}>{loading ? 'Loading…' : 'Reload'}</button></div>
      </header>
      {children}
    </section>
  </div>;
}
