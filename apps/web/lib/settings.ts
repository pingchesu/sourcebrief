export type PlatformSettings = {
  apiBaseUrl: string;
  sessionToken: string;
  workspaceId: string;
  projectId: string;
};

export const DEFAULT_SETTINGS: PlatformSettings = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:18000',
  sessionToken: '',
  workspaceId: '',
  projectId: '',
};

const STORAGE_KEY = 'sourcebrief.platform.settings.v2';
const LEGACY_STORAGE_KEY = 'contextsmith.platform.settings.v2';
const SESSION_SECRET_KEY = 'sourcebrief.platform.session.v2';
const LEGACY_SESSION_SECRET_KEY = 'contextsmith.platform.session.v2';

export function loadSettings(): PlatformSettings {
  if (typeof window === 'undefined') return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
      ?? window.localStorage.getItem(LEGACY_STORAGE_KEY);
    const sessionToken =
      window.sessionStorage.getItem(SESSION_SECRET_KEY)
      ?? window.sessionStorage.getItem(LEGACY_SESSION_SECRET_KEY)
      ?? '';
    const parsed = raw ? JSON.parse(raw) : {};
    return { ...DEFAULT_SETTINGS, ...parsed, sessionToken };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: PlatformSettings): void {
  if (typeof window === 'undefined') return;
  const { sessionToken, ...persisted } = settings;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  if (sessionToken) window.sessionStorage.setItem(SESSION_SECRET_KEY, sessionToken);
  else window.sessionStorage.removeItem(SESSION_SECRET_KEY);
}
