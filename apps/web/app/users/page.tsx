'use client';

import { PageHeader, Card, Metric, EmptyState, StatusChip } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import { fmt, short } from '../../lib/api';

export default function UsersPage() {
  const { members, tokens, workspace } = usePlatform();
  return <main className="page"><PageHeader eyebrow="User Management" title="Users, roles, and token permissions" description="See who can review, configure, and query this workspace's agents, and how each API token is scoped — all by name." />
    <div className="grid three"><Metric label="Workspace" value={workspace?.name ?? '—'} /><Metric label="Members" value={members.length} /><Metric label="API tokens" value={tokens.length} /></div>
    <div className="grid two"><Card><h2>Workspace members</h2>{members.length === 0 ? <EmptyState text="No member API data available yet, or the current principal is not a workspace admin." /> : <div className="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Joined</th></tr></thead><tbody>{members.map((member) => <tr key={member.id}><td><strong>{member.user.display_name || member.user.email}</strong><div className="code">{member.user.email} · {short(member.user.id)}</div></td><td><StatusChip value={member.role} /></td><td>{fmt(member.created_at)}</td></tr>)}</tbody></table></div>}</Card>
    <Card><h2>Token permissions</h2>{tokens.length === 0 ? <EmptyState text="No tokens created or token admin permission unavailable." /> : <div className="table-wrap"><table><thead><tr><th>Name</th><th>Scopes</th><th>Bounds</th><th>Status</th></tr></thead><tbody>{tokens.map((token) => <tr key={token.id}><td><strong>{token.name}</strong><div className="code">{short(token.id)}</div></td><td className="code">{token.scopes.join(', ')}</td><td className="code">projects {token.allowed_project_ids?.map(short).join(', ') ?? 'all'}<br />resources {token.allowed_resource_ids?.map(short).join(', ') ?? 'all'}</td><td><StatusChip value={token.revoked_at ? 'revoked' : 'active'} /></td></tr>)}</tbody></table></div>}</Card></div>
  </main>;
}
