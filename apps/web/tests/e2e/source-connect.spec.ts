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
});
