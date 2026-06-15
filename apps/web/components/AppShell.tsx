'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { usePlatform } from '../lib/platform-context';
import { short } from '../lib/api';

const NAV = [
  ['/', 'Dashboard'],
  ['/import', 'Import Resources'],
  ['/repo-agents', 'Repo Agents'],
  ['/evals', 'Quality Evals'],
  ['/agent-files', 'Agent Files'],
  ['/git-env', 'Git Env'],
  ['/maintenance', 'Update / Reindex'],
  ['/agent-profile', 'Project Agent'],
  ['/resources', 'Resources'],
  ['/review', 'Review Center'],
  ['/ask', 'Ask / Citations'],
  ['/login', 'Login / Logout'],
  ['/config', 'Config'],
  ['/users', 'User Management'],
  ['/admin', 'Admin'],
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { agent, provider, workspace, project, settings, loading, error, reload } = usePlatform();
  const principal = settings.bearer.trim() ? 'token session' : settings.email.trim() || 'signed out';
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-kicker">CONTEXTSMITH</div><div className="brand-title">Knowledge Agents</div></div>
      <nav className="nav-group">{NAV.map(([href, label]) => <Link key={href} href={href} className={`nav-link ${pathname === href ? 'active' : ''}`}><span>{label}</span></Link>)}</nav>
      <div className="sidebar-footer"><strong>{agent?.name ?? 'AngiKnowledge Agent'}</strong><br />{workspace?.name ?? 'Workspace'}<br />{project?.name ?? 'Project'}<br /><span className="code">{short(settings.workspaceId)} / {short(settings.projectId)}</span></div>
    </aside>
    <section className="main">
      <header className="topbar">
        <div><strong>{agent?.name ?? 'Loading agent…'}</strong><div className="code">{workspace?.name ?? short(settings.workspaceId)} · {project?.name ?? short(settings.projectId)} · signed in as {principal} · {provider ? `${provider.embedding.provider}/${provider.embedding.model}` : 'provider not loaded'} {error ? `· ${error}` : ''}</div></div>
        <div className="toolbar"><span className={`chip ${provider?.status === 'ok' ? 'ok' : 'warn'}`}>{provider?.status ?? (principal === 'signed out' ? 'signed out' : 'loading')}</span><Link className="btn secondary" href="/login">Session</Link><button className="btn secondary" onClick={() => reload()} disabled={loading}>{loading ? 'Loading…' : 'Reload'}</button></div>
      </header>
      {children}
    </section>
  </div>;
}
