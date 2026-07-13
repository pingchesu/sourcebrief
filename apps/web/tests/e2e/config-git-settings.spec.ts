import { expect, test } from '@playwright/test';

const workspaceId = '11111111-1111-4111-8111-111111111111';
const projectId = '22222222-2222-4222-8222-222222222222';
const resourceId = '33333333-3333-4333-8333-333333333333';

const gitEnv = {
  resource_id: resourceId,
  name: 'SourceBrief',
  uri: 'https://github.com/example/sourcebrief.git',
  branch: 'main',
  auth_token_env: 'SOURCEBRIEF_GITHUB_TOKEN',
  clone_timeout: 120,
  max_file_bytes: 1_000_000,
  max_repo_files: 1_000,
  max_repo_bytes: 20_000_000,
  max_chunks: 5_000,
  max_symbols: 5_000,
  update_frequency: 'daily',
  next_refresh_at: null,
};

test('validates and saves Git indexing settings from Settings', async ({ page }) => {
  let patchBody: Record<string, unknown> | null = null;
  await page.addInitScript(({ workspaceId: ws, projectId: project }) => {
    localStorage.setItem('sourcebrief.platform.settings.v2', JSON.stringify({
      apiBaseUrl: '',
      workspaceId: ws,
      projectId: project,
    }));
    sessionStorage.setItem('sourcebrief.platform.session.v2', 'test-session-token');
  }, { workspaceId, projectId });

  await page.route('**/*', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/auth/me') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: { id: 'user-1', email: 'admin@example.com', display_name: 'Admin', role: 'admin' }, workspaces: [{ id: workspaceId, name: 'Workspace' }], projects_by_workspace: { [workspaceId]: [{ id: projectId, name: 'Project' }] }, default_workspace_id: workspaceId, default_project_id: projectId }) });
    if (path.endsWith('/resources') && request.method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: resourceId, workspace_id: workspaceId, project_id: projectId, type: 'git', name: 'SourceBrief', uri: gitEnv.uri, source_config: { branch: 'main' }, status: 'ready', retrieval_enabled: true, queryable: true, coverage_status: 'full', coverage_warnings: [], index_diagnostics: {}, current_snapshot_id: 'snapshot-1', created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:00Z' }]) });
    if (path.endsWith('/git-env') && request.method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([gitEnv]) });
    if (path.endsWith(`/resources/${resourceId}/git-env`) && request.method() === 'PATCH') {
      patchBody = request.postDataJSON() as Record<string, unknown>;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...gitEnv, ...patchBody }) });
    }
    if (path.endsWith('/index-runs')) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    if (path === '/provider-health') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', embedding: { namespace: 'test', dev_quality: true, status: 'ok', provider: 'test', model: 'test' } }) });
    if (path.endsWith('/retrieval-profiles')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ profiles: [], default_profile_key: null }) });
    if (path.endsWith('/resource-review')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], summary: {} }) });
    if (path.endsWith('/api-tokens')) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    if (request.resourceType() === 'document' || path.startsWith('/_next/')) return route.continue();
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });

  await page.goto('/config');
  await expect(page.getByRole('heading', { name: 'Git indexing settings' })).toBeVisible();
  await expect(page.getByLabel('Git source')).toHaveValue(resourceId);
  await page.getByLabel('Max chunks').fill('1.5');
  await page.getByRole('button', { name: 'Save Git settings' }).click();
  await expect(page.getByText('Max chunks must be a positive whole number.')).toBeVisible();
  expect(patchBody).toBeNull();

  await page.getByLabel('Max chunks').fill('20000');
  await page.getByRole('button', { name: 'Save Git settings' }).click();
  await expect(page.getByText('Git settings saved.')).toBeVisible();
  expect(patchBody).toMatchObject({ max_chunks: 20000, max_symbols: 5000, branch: 'main' });
});
