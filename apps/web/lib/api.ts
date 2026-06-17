import type { PlatformSettings } from './settings';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function authHeaders(settings: PlatformSettings): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (settings.bearer.trim()) headers.Authorization = `Bearer ${settings.bearer.trim()}`;
  else if (settings.email.trim()) headers['X-User-Email'] = settings.email.trim();
  return headers;
}

export async function apiFetch<T>(settings: PlatformSettings, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${settings.apiBaseUrl}${path}`, { ...init, headers: { ...authHeaders(settings), ...(init.headers as Record<string, string> | undefined) } });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) throw new ApiError(response.status, body?.detail ? JSON.stringify(body.detail) : text || response.statusText);
  return body as T;
}

export async function apiFetchText(settings: PlatformSettings, path: string, init: RequestInit = {}): Promise<string> {
  const response = await fetch(`${settings.apiBaseUrl}${path}`, { ...init, headers: { ...authHeaders(settings), ...(init.headers as Record<string, string> | undefined) } });
  const text = await response.text();
  if (!response.ok) {
    let message = text || response.statusText;
    try {
      const body = text ? JSON.parse(text) : null;
      message = body?.detail ? JSON.stringify(body.detail) : message;
    } catch {}
    throw new ApiError(response.status, message);
  }
  return text;
}

export const short = (id?: string | null) => id ? id.slice(0, 8) : '—';
export const fmt = (value?: string | null) => value ? new Date(value).toLocaleString() : '—';
