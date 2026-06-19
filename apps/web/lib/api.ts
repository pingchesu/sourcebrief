import type { PlatformSettings } from './settings';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function headers(settings: PlatformSettings, init?: RequestInit): Record<string, string> {
  const next: Record<string, string> = { 'Content-Type': 'application/json', ...((init?.headers as Record<string, string> | undefined) ?? {}) };
  if (settings.sessionToken.trim()) next.Authorization = `Bearer ${settings.sessionToken.trim()}`;
  return next;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) throw new ApiError(response.status, body?.detail ? String(body.detail) : text || response.statusText);
  return body as T;
}

export async function apiFetch<T>(settings: PlatformSettings, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${settings.apiBaseUrl}${path}`, { ...init, headers: headers(settings, init) });
  return parseResponse<T>(response);
}

export async function anonymousFetch<T>(settings: PlatformSettings, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${settings.apiBaseUrl}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...((init.headers as Record<string, string> | undefined) ?? {}) } });
  return parseResponse<T>(response);
}

export async function apiFetchText(settings: PlatformSettings, path: string, init: RequestInit = {}): Promise<string> {
  const response = await fetch(`${settings.apiBaseUrl}${path}`, { ...init, headers: headers(settings, init) });
  const text = await response.text();
  if (!response.ok) throw new ApiError(response.status, text || response.statusText);
  return text;
}

export async function apiFetchBlob(settings: PlatformSettings, path: string, init: RequestInit = {}): Promise<Blob> {
  const response = await fetch(`${settings.apiBaseUrl}${path}`, { ...init, headers: headers(settings, init) });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, text || response.statusText);
  }
  return response.blob();
}

export const short = (id?: string | null) => id ? id.slice(0, 8) : '—';
export const fmt = (value?: string | null) => value ? new Date(value).toLocaleString() : '—';
