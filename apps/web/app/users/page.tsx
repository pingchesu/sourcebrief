'use client';

import { type FormEvent, useMemo, useState } from 'react';
import { PageHeader, Card, Metric, EmptyState, StatusChip, Field } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import { fmt } from '../../lib/api';
import type { WorkspaceMember } from '../../lib/types';

const ROLES = ['owner', 'admin', 'member', 'viewer'] as const;

export default function UsersPage() {
  const { members, workspace, settings, client, reload, signedIn, currentUser } = usePlatform();
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<(typeof ROLES)[number]>('member');
  const [busy, setBusy] = useState(false);
  const admins = useMemo(() => members.filter((member) => ['owner', 'admin'].includes(member.role) && member.user.is_active), [members]);
  const myMembership = useMemo(() => members.find((member) => member.user.id === currentUser?.id), [members, currentUser?.id]);
  const canManageTeam = Boolean(currentUser?.is_platform_admin || (myMembership && ['owner', 'admin'].includes(myMembership.role)));
  const canManageGlobalUserState = Boolean(currentUser?.is_platform_admin);

  async function createMember(event: FormEvent) {
    event.preventDefault();
    if (!settings.workspaceId || !canManageTeam) return;
    setBusy(true);
    try {
      await client<WorkspaceMember>(`/workspaces/${settings.workspaceId}/members`, { method: 'POST', body: JSON.stringify({ email, display_name: displayName || null, password: password || null, role }) });
      setEmail(''); setDisplayName(''); setPassword(''); setRole('member');
      await reload();
    } finally { setBusy(false); }
  }

  async function updateRole(member: WorkspaceMember, nextRole: string) {
    if (!canManageTeam) return;
    await client<WorkspaceMember>(`/workspaces/${settings.workspaceId}/members/${member.id}`, { method: 'PATCH', body: JSON.stringify({ role: nextRole }) });
    await reload();
  }

  async function toggleActive(member: WorkspaceMember) {
    if (!canManageGlobalUserState) return;
    await client<WorkspaceMember>(`/workspaces/${settings.workspaceId}/members/${member.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !member.user.is_active }) });
    await reload();
  }

  return <main className="page"><PageHeader eyebrow="Team Access" title="Users and roles" description="Create teammates, assign workspace roles, and keep at least one active admin for this workspace." />
    <div className="grid three"><Metric label="Workspace" value={workspace?.name ?? '—'} /><Metric label="Members" value={members.length} /><Metric label="Admins" value={admins.length} /></div>
    <div className="grid two">
      <Card><h2>Create user</h2>{!signedIn ? <EmptyState text="Sign in as an admin to manage team access." /> : !canManageTeam ? <EmptyState text="Your account can view this team, but an owner or admin must invite and assign roles." /> : <form className="grid" onSubmit={createMember}>
        <Field label="Name"><input className="input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Jane Doe" /></Field>
        <Field label="Email"><input className="input" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="jane@example.com" required /></Field>
        <Field label="Temporary password"><input className="input" type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} placeholder="At least 8 characters" /></Field>
        <Field label="Role"><select className="input" value={role} onChange={(event) => setRole(event.target.value as (typeof ROLES)[number])}>{ROLES.map((item) => <option key={item} value={item}>{item}</option>)}</select></Field>
        <button className="btn" disabled={busy}>{busy ? 'Creating…' : 'Create user'}</button>
      </form>}</Card>
      <Card><h2>Role guide</h2><ul className="muted"><li><strong>Owner/Admin</strong>: manage users, sources, quality gates, and agent settings.</li><li><strong>Member</strong>: operate sources and review context.</li><li><strong>Viewer</strong>: read workspace state without changing it.</li></ul><div className="notice">Multiple admins are supported. The system prevents disabling or downgrading the final active admin.</div></Card>
    </div>
    <Card><h2>Workspace members</h2>{members.length === 0 ? <EmptyState text="No members loaded yet." /> : <div className="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Joined</th>{canManageTeam ? <th>Actions</th> : null}</tr></thead><tbody>{members.map((member) => <tr key={member.id}><td><strong>{member.user.display_name || member.user.email}</strong><div className="muted">{member.user.email}</div></td><td>{canManageTeam ? <select className="input" value={member.role} onChange={(event) => void updateRole(member, event.target.value)}>{ROLES.map((item) => <option key={item} value={item}>{item}</option>)}</select> : member.role}</td><td><StatusChip value={member.user.is_active ? 'active' : 'disabled'} /></td><td>{fmt(member.created_at)}</td>{canManageTeam ? <td>{canManageGlobalUserState ? <button className="btn secondary" onClick={() => void toggleActive(member)}>{member.user.is_active ? 'Disable' : 'Enable'}</button> : <span className="muted">Role only</span>}</td> : null}</tr>)}</tbody></table></div>}</Card>
  </main>;
}
