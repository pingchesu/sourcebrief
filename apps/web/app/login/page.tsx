'use client';

import type { FormEvent } from 'react';
import { useState } from 'react';
import { PageHeader, Card, Metric, StatusChip } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';

export default function LoginPage() {
  const { currentUser, signedIn, workspace, project, provider, login, logout, loading, error } = usePlatform();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await login(email, password);
  }

  return <main className="page">
    <PageHeader eyebrow="Account" title="Sign in to ContextSmith" description="Use your ContextSmith account. Admin users can invite teammates and assign workspace roles after signing in." />
    <div className="grid four">
      <Metric label="Account" value={currentUser?.display_name || currentUser?.email || 'Signed out'} />
      <Metric label="Workspace" value={workspace?.name ?? '—'} />
      <Metric label="Project" value={project?.name ?? '—'} />
      <div className="metric"><div className="metric-label">Platform</div><div className="metric-value"><StatusChip value={provider?.status ?? (signedIn ? 'loading' : 'signed-out')} /></div></div>
    </div>
    <div className="grid two">
      <Card>
        <h2>{signedIn ? 'Account session' : 'Login'}</h2>
        {signedIn ? <div className="grid">
          <div className="notice">Signed in as <strong>{currentUser?.display_name || currentUser?.email}</strong>.</div>
          <button className="btn danger" type="button" onClick={() => void logout()} disabled={loading}>Logout</button>
        </div> : <form className="grid" onSubmit={submit}>
          <label><span className="label">Email</span><input name="email" className="input" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" /></label>
          <label><span className="label">Password</span><input name="password" className="input" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error ? <div className="notice danger">{error}</div> : null}
          <button className="btn" type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}</button>
        </form>}
      </Card>
      <Card>
        <h2>First administrator</h2>
        <p className="muted">The first administrator is created automatically during setup. Sign in with that account, then invite additional admins and teammates from Team Access.</p>
        <ul className="muted">
          <li>The setup operator owns the first email and password through deployment configuration.</li>
          <li>Admins can create additional admins from Team Access.</li>
        </ul>
      </Card>
    </div>
  </main>;
}
