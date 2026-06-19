'use client';

import { PageHeader, Card, Metric, EmptyState, StatusChip } from '../../components/ui';
import { usePlatform } from '../../lib/platform-context';
import { fmt, short } from '../../lib/api';

export default function AdminPage() {
  const { auditEvents, provider, resources, reviewItems, indexRuns } = usePlatform();
  const stale = reviewItems.filter((item) => item.freshness_status !== 'fresh').length;
  const failedRuns = indexRuns.filter((run) => run.status === 'failed').length;
  return <main className="page"><PageHeader eyebrow="Admin" title="Operations and observability" description="Operations surface for provider health, indexing status, freshness risk, and audit events across the workspace." />
    <div className="grid four"><Metric label="Provider" value={provider?.status ?? '—'} /><Metric label="Resources" value={resources.length} /><Metric label="Freshness risks" value={stale} /><Metric label="Selected failed runs" value={failedRuns} /></div>
    <div className="grid two"><Card><h2>Provider health</h2>{provider ? <pre className="code-block light">{JSON.stringify(provider, null, 2)}</pre> : <EmptyState text="Provider health not loaded." />}</Card><Card><h2>Selected resource index runs</h2>{indexRuns.length === 0 ? <EmptyState text="Select a resource to inspect index-run status." /> : <div className="table-wrap"><table><thead><tr><th>Status</th><th>Trigger</th><th>Counts</th><th>Finished</th></tr></thead><tbody>{indexRuns.map((run) => <tr key={run.id}><td><StatusChip value={run.status} /></td><td>{run.trigger}</td><td className="code">docs {run.documents_seen} · chunks {run.chunks_created} · symbols {run.symbols_created}</td><td>{fmt(run.finished_at)}</td></tr>)}</tbody></table></div>}</Card></div>
    <Card><h2>Audit events</h2>{auditEvents.length === 0 ? <EmptyState text="No audit events returned or token admin permission unavailable." /> : <div className="table-wrap"><table><thead><tr><th>Action</th><th>Target</th><th>Actor</th><th>When</th></tr></thead><tbody>{auditEvents.slice(0, 80).map((event) => <tr key={event.id}><td><strong>{event.action}</strong><div className="code">{short(event.id)}</div></td><td>{event.target_type}<div className="code">{short(event.target_id)}</div></td><td className="code">{short(event.actor_user_id)} / {short(event.actor_token_id)}</td><td>{fmt(event.created_at)}</td></tr>)}</tbody></table></div>}</Card>
  </main>;
}
