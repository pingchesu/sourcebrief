import { expect, test } from '@playwright/test';

test('published graph picker renders one selectable row per source', async ({ page }) => {
  const workspaceId = 'workspace-graph-layout';
  const projectId = 'project-graph-layout';
  const graphs = Array.from({ length: 20 }, (_, index) => ({
    id: `graph-${index}`,
    workspace_id: workspaceId,
    project_id: projectId,
    resource_id: `resource-${index}`,
    graph_key: `source-graph-${index + 1}`,
    title: `Published source ${index + 1}`,
    description: null,
    graph_type: 'resource',
    status: 'active',
    current_version_id: `version-${index}`,
    current: { id: `version-${index}`, graph_id: `graph-${index}`, resource_id: `resource-${index}`, source_snapshot_id: `snapshot-${index}`, version: 1, status: 'published', version_hash: `hash-${index}`, node_count: 1, edge_count: 0, membership_json: {}, provenance_json: {}, summary_json: {}, validation_json: { ok: true }, status_reason: null, published_at: '2026-07-13T00:00:00Z', invalidated_at: null, created_at: '2026-07-13T00:00:00Z' },
    versions: [],
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:00Z',
  }));

  await page.addInitScript(({ workspaceId, projectId }) => {
    window.localStorage.setItem('sourcebrief.platform.settings.v2', JSON.stringify({ apiBaseUrl: '', workspaceId, projectId }));
    window.sessionStorage.setItem('sourcebrief.platform.session.v2', 'test-session');
  }, { workspaceId, projectId });
  await page.route('**/*', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/auth/me') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: { id: 'user-1', email: 'admin@example.test', role: 'admin' }, default_workspace_id: workspaceId, default_project_id: projectId, workspaces: [{ id: workspaceId, name: 'Test workspace' }], projects_by_workspace: { [workspaceId]: [{ id: projectId, name: 'Test project' }] }, memberships: [] }) });
    if (path === '/provider-health') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', embedding: { namespace: 'test', dev_quality: true, status: 'ok', provider: 'test', model: 'test' } }) });
    if (path === `/workspaces/${workspaceId}/agents` || path === `/workspaces/${workspaceId}/members` || path === `/workspaces/${workspaceId}/audit-events`) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/agent-profile`) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'agent-profile', name: 'Test agent', description: '', default_runtime: 'hermes', resource_count: 0, current_snapshot_count: 0, graph_node_count: 0, graph_edge_count: 0 }) });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/resources` || path === `/workspaces/${workspaceId}/projects/${projectId}/resource-review` || path === `/workspaces/${workspaceId}/projects/${projectId}/resource-usage`) return route.fulfill({ status: 200, contentType: 'application/json', body: path.endsWith('/resources') ? '[]' : JSON.stringify({ resources: [] }) });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/graphs`) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(graphs) });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/graph-merges`) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    return route.continue();
  });

  await page.goto('/graph-merge');
  await page.waitForTimeout(500);
  expect((await page.pageErrors()).map((error) => error.message)).toEqual([]);
  const rows = page.locator('.graph-source-row');
  await expect(rows).toHaveCount(20);
  await expect(rows.first()).toBeVisible();
  const yPositions = await rows.evaluateAll((items) => items.map((item) => Math.round(item.getBoundingClientRect().y)));
  expect(new Set(yPositions).size).toBe(20);
  await expect(page.locator('.graph-source-list')).toHaveCSS('overflow-y', 'auto');
  await rows.nth(0).click();
  await rows.nth(1).click();
  await expect(rows.nth(0).locator('input')).toBeChecked();
  await expect(rows.nth(1).locator('input')).toBeChecked();
  await expect(page.getByRole('button', { name: 'Compile draft' })).toBeEnabled();
});