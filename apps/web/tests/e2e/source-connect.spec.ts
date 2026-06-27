import { expect, test } from '@playwright/test';
import fs from 'node:fs';

function loadEnv(path: string): Record<string, string> {
  if (!fs.existsSync(path)) return {};
  const out: Record<string, string> = {};
  for (const raw of fs.readFileSync(path, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const [key, ...rest] = line.split('=');
    out[key.trim()] = rest.join('=').trim().replace(/^['"]|['"]$/g, '');
  }
  return out;
}

const repoEnv = loadEnv('../../.env');
const adminEmail = process.env.SOURCEBRIEF_ADMIN_EMAIL ?? repoEnv.SOURCEBRIEF_ADMIN_EMAIL;
const adminPassword = process.env.SOURCEBRIEF_ADMIN_PASSWORD ?? repoEnv.SOURCEBRIEF_ADMIN_PASSWORD;

test.skip(!adminEmail || !adminPassword, 'SourceBrief admin credentials are required for the first-source browser smoke.');

test('login form signs in with configured admin credentials', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Email').fill(adminEmail ?? '');
  await page.getByLabel('Password').fill(adminPassword ?? '');
  await page.getByRole('button', { name: 'Sign in' }).click();

  await expect(page.locator('.notice').filter({ hasText: /Signed in as/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Logout' })).toBeVisible();
});

async function login(page: import('@playwright/test').Page) {
  const apiBaseUrl = process.env.SOURCEBRIEF_API_URL ?? 'http://localhost:18000';
  const response = await page.request.post(`${apiBaseUrl}/auth/login`, { data: { email: adminEmail, password: adminPassword } });
  expect(response.ok()).toBeTruthy();
  const identity = await response.json() as { session_token: string; default_workspace_id: string | null; default_project_id: string | null; workspaces: Array<{ id: string }>; projects_by_workspace: Record<string, Array<{ id: string }>> };
  const workspaceId = identity.default_workspace_id ?? identity.workspaces[0]?.id ?? '';
  const projectId = identity.default_project_id ?? identity.projects_by_workspace[workspaceId]?.[0]?.id ?? '';
  expect(workspaceId, 'workspace selected during API login').not.toBe('');
  expect(projectId, 'project selected during API login').not.toBe('');
  await page.goto('/');
  await page.evaluate(({ settings, token }) => {
    window.localStorage.setItem('sourcebrief.platform.settings.v2', JSON.stringify(settings));
    window.sessionStorage.setItem('sourcebrief.platform.session.v2', token);
  }, { settings: { apiBaseUrl, workspaceId, projectId }, token: identity.session_token });
}

async function fillSampleMarkdown(page: import('@playwright/test').Page) {
  const stamp = Date.now();
  await page.goto('/sources');
  await page.getByRole('button', { name: 'Use sample source' }).first().click();
  await expect(page.getByRole('form', { name: 'Connect source form' })).toBeVisible();
  await expect(page.getByLabel('Source type')).toHaveValue('markdown');
  await page.getByLabel('Name').fill(`Issue75 browser smoke ${stamp}`);
  await page.getByLabel('URI / path').fill(`doc://issue75-browser-smoke-${stamp}.md`);
  await page.getByLabel('Content').fill(`# Issue75 browser smoke ${stamp}\n\nThis deterministic markdown proves the first-source browser form submitted.`);
}

test('first-source form submits, refreshes, and shows next value actions', async ({ page }) => {
  await login(page);
  await fillSampleMarkdown(page);

  const resourceRequest = page.waitForRequest((request) => request.method() === 'POST' && /\/workspaces\/[^/]+\/projects\/[^/]+\/resources$/.test(new URL(request.url()).pathname));
  const refreshRequest = page.waitForRequest((request) => request.method() === 'POST' && /\/resources\/[^/]+\/refresh$/.test(new URL(request.url()).pathname));
  const resourceResponse = page.waitForResponse((response) => response.request().method() === 'POST' && /\/workspaces\/[^/]+\/projects\/[^/]+\/resources$/.test(new URL(response.url()).pathname));

  await page.getByRole('form', { name: 'Connect source form' }).getByRole('button', { name: 'Connect source' }).click();

  await resourceRequest;
  await expect((await resourceResponse).ok()).toBeTruthy();
  await refreshRequest;
  await expect(page.getByText('Source connected.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Preview this source' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Ask in Workbench' })).toBeVisible();
});

test('git connect supports public and private env-var flows before refresh', async ({ page }) => {
  const workspaceId = 'workspace-private-git';
  const projectId = 'project-private-git';
  const createdResources: Array<Record<string, unknown>> = [];
  await page.addInitScript(({ workspaceId, projectId }) => {
    window.localStorage.setItem('sourcebrief.platform.settings.v2', JSON.stringify({ apiBaseUrl: '', workspaceId, projectId }));
    window.sessionStorage.setItem('sourcebrief.platform.session.v2', 'test-session');
  }, { workspaceId, projectId });
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/auth/me') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: { id: 'user-1', email: 'admin@example.test', role: 'admin' }, default_workspace_id: workspaceId, default_project_id: projectId, workspaces: [{ id: workspaceId, name: 'Test workspace' }], projects_by_workspace: { [workspaceId]: [{ id: projectId, name: 'Test project' }] }, memberships: [] }) });
    if (path === '/provider-health') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', embedding: { namespace: 'test', dev_quality: true, status: 'ok', provider: 'test', model: 'test' } }) });
    if (path === `/workspaces/${workspaceId}/agents`) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/agent-profile`) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'agent-1', name: 'Test agent', description: '', default_runtime: 'hermes', resource_count: createdResources.length, current_snapshot_count: 0, graph_node_count: 0, graph_edge_count: 0 }) });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/resources` && request.method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(createdResources) });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/resource-review`) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resources: [] }) });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/resource-usage`) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resources: [] }) });
    if (path === `/workspaces/${workspaceId}/members` || path === `/workspaces/${workspaceId}/audit-events`) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/git-env`) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(createdResources.filter((item) => item.type === 'git').map((item) => ({ resource_id: item.id, name: item.name, uri: item.uri, branch: (item.source_config as Record<string, unknown>).branch ?? null, auth_token_env: (item.source_config as Record<string, unknown>).auth_token_env ?? null, clone_timeout: null, max_file_bytes: null, max_repo_files: null, max_repo_bytes: null, update_frequency: item.update_frequency, next_refresh_at: null }))) });
    if (path === `/workspaces/${workspaceId}/projects/${projectId}/resources` && request.method() === 'POST') {
      const body = request.postDataJSON();
      const resource = { id: `resource-${createdResources.length + 1}`, workspace_id: workspaceId, project_id: projectId, type: body.type, name: body.name, uri: body.uri, status: 'active', retrieval_enabled: true, update_frequency: body.update_frequency, current_snapshot_id: null, review_status: 'unreviewed', review_note: null, source_config: body.source_config, queryable: false, coverage_status: 'not_indexed', coverage_warnings: [], index_diagnostics: {}, source_family_label: null, version_label: null, last_refresh_finished_at: null };
      createdResources.push(resource);
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(resource) });
    }
    if (/\/workspaces\/[^/]+\/projects\/[^/]+\/resources\/[^/]+\/refresh$/.test(path)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'queued' }) });
    if (/\/workspaces\/[^/]+\/projects\/[^/]+\/resources\/[^/]+\/snapshots$/.test(path) || /\/workspaces\/[^/]+\/projects\/[^/]+\/resources\/[^/]+\/index-runs$/.test(path)) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    if (/\/workspaces\/[^/]+\/projects\/[^/]+\/resources\/[^/]+\/graph$/.test(path)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ node_count: 0, edge_count: 0 }) });
    return route.continue();
  });

  const privateStamp = Date.now();
  await page.goto('/sources');
  await page.getByRole('button', { name: 'Connect source' }).first().click();
  const form = page.getByRole('form', { name: 'Connect source form' });
  await expect(form.getByText(/environment variable name only/)).toBeVisible();
  await form.getByRole('textbox', { name: 'Name', exact: true }).fill(`Private Git ${privateStamp}`);
  await form.getByLabel('Git URL').fill(`https://github.com/example/private-${privateStamp}.git`);
  await form.getByLabel('Branch').fill('main');
  await form.getByPlaceholder('GITHUB_TOKEN_FOR_SOURCEBRIEF').fill('GITHUB_TOKEN_FOR_SOURCEBRIEF');

  const events: string[] = [];
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() === 'POST' && /\/workspaces\/[^/]+\/projects\/[^/]+\/resources$/.test(pathname)) events.push('resource');
    if (request.method() === 'POST' && /\/resources\/[^/]+\/refresh$/.test(pathname)) events.push('refresh');
  });
  const privateResourceRequest = page.waitForRequest((request) => request.method() === 'POST' && /\/workspaces\/[^/]+\/projects\/[^/]+\/resources$/.test(new URL(request.url()).pathname));
  const privateRefreshRequest = page.waitForRequest((request) => request.method() === 'POST' && /\/resources\/[^/]+\/refresh$/.test(new URL(request.url()).pathname));
  await form.getByRole('button', { name: 'Connect source' }).click();
  const privateCreate = await privateResourceRequest;
  expect(privateCreate.postDataJSON().source_config.auth_token_env).toBe('GITHUB_TOKEN_FOR_SOURCEBRIEF');
  await privateRefreshRequest;
  expect(events.slice(-2)).toEqual(['resource', 'refresh']);
  await expect(page.getByText('Source connected.')).toBeVisible();
  await expect(page.getByRole('form', { name: 'Git environment form' }).getByLabel('Git auth token env var')).toHaveValue('GITHUB_TOKEN_FOR_SOURCEBRIEF');

  const publicStamp = Date.now();
  await form.getByRole('textbox', { name: 'Name', exact: true }).fill(`Public Git ${publicStamp}`);
  await form.getByLabel('Git URL').fill(`https://github.com/example/public-${publicStamp}.git`);
  await form.getByLabel('Branch').fill('main');
  await form.getByPlaceholder('GITHUB_TOKEN_FOR_SOURCEBRIEF').fill('');
  await expect(form.getByPlaceholder('GITHUB_TOKEN_FOR_SOURCEBRIEF')).toHaveValue('');
  const publicResourceRequest = page.waitForRequest((request) => request.method() === 'POST' && /\/workspaces\/[^/]+\/projects\/[^/]+\/resources$/.test(new URL(request.url()).pathname));
  const publicRefreshRequest = page.waitForRequest((request) => request.method() === 'POST' && /\/resources\/[^/]+\/refresh$/.test(new URL(request.url()).pathname));
  await form.getByRole('button', { name: 'Connect source' }).click();
  const publicCreate = await publicResourceRequest;
  expect(publicCreate.postDataJSON().source_config.auth_token_env).toBeUndefined();
  await publicRefreshRequest;
});

test('first-source form shows actionable backend errors and preserves input', async ({ page }) => {
  await login(page);
  await fillSampleMarkdown(page);
  await page.route('**/workspaces/*/projects/*/resources', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'forced source validation error' }) });
  });

  const resourceRequest = page.waitForRequest((request) => request.method() === 'POST' && /\/workspaces\/[^/]+\/projects\/[^/]+\/resources$/.test(new URL(request.url()).pathname));
  await page.getByRole('form', { name: 'Connect source form' }).getByRole('button', { name: 'Connect source' }).click();

  await resourceRequest;
  await expect(page.getByText(/forced source validation error/)).toBeVisible();
  await expect(page.getByLabel('Content')).toContainText('deterministic markdown proves');
  await expect(page.getByRole('form', { name: 'Connect source form' }).getByRole('button', { name: 'Connect source' })).toBeEnabled();
});

test('settings routes source creation to the canonical Sources page', async ({ page }) => {
  await login(page);
  await page.goto('/config');

  await expect(page.getByRole('heading', { name: 'Source lifecycle moved to Sources' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open Sources' })).toHaveAttribute('href', '/sources');
  await expect(page.getByRole('button', { name: 'Add source' })).toHaveCount(0);
  await expect(page.getByText(/named connections/i)).toHaveCount(0);
});
