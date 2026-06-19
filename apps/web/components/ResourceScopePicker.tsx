'use client';

import type { Resource } from '../lib/types';

export function ResourceScopePicker({
  resources,
  selectedIds,
  onChange,
  label = 'Context scope',
}: {
  resources: Resource[];
  selectedIds: string[];
  onChange: (resourceIds: string[]) => void;
  label?: string;
}) {
  const allSelected = selectedIds.length === 0;
  return <div className="scope-picker">
    <label><span className="label">{label} mode</span><select className="input" value={allSelected ? 'all' : 'selected'} onChange={(event) => onChange(event.target.value === 'all' ? [] : (resources[0] ? [resources[0].id] : []))}><option value="all">All resources</option><option value="selected">Selected resources</option></select></label>
    <label><span className="label">Resources</span><select className="input" multiple size={Math.min(10, Math.max(4, resources.length))} value={selectedIds} disabled={allSelected} onChange={(event) => onChange(Array.from(event.target.selectedOptions).map((option) => option.value))}>{resources.map((resource) => <option key={resource.id} value={resource.id}>{resource.name} — {resource.type} · review {resource.review_status} · retrieval {resource.retrieval_enabled ? 'enabled' : 'disabled'} · {resource.uri}</option>)}</select></label>
    <div className="muted">{allSelected ? 'All retrieval-enabled current resources are in scope.' : `${selectedIds.length} resource(s) selected.`}</div>
  </div>;
}

export function describeScope(resources: Resource[], selectedIds: string[]) {
  if (selectedIds.length === 0) return `All ${resources.length} current resources`;
  const names = selectedIds.map((id) => resources.find((resource) => resource.id === id)?.name ?? 'Selected source');
  return names.join(', ');
}
