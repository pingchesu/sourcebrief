'use client';

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { anonymousFetch, apiFetch } from './api';
import { loadSettings, saveSettings, type PlatformSettings } from './settings';
import type { AgentProfile, AuditEvent, CurrentUserResponse, GraphRead, IndexRun, LoginResponse, Project, ProviderHealth, Resource, ReviewItem, Snapshot, UsageItem, User, Workspace, WorkspaceMember } from './types';

type PlatformState = {
  settings: PlatformSettings;
  currentUser: User | null;
  signedIn: boolean;
  workspaces: Workspace[];
  workspace: Workspace | null;
  projects: Project[];
  projectsByWorkspace: Record<string, Project[]>;
  project: Project | null;
  provider: ProviderHealth | null;
  agents: AgentProfile[];
  agent: AgentProfile | null;
  resources: Resource[];
  reviewItems: ReviewItem[];
  usageItems: UsageItem[];
  members: WorkspaceMember[];
  auditEvents: AuditEvent[];
  selectedResourceId: string;
  selectedResource: Resource | null;
  snapshots: Snapshot[];
  indexRuns: IndexRun[];
  graph: GraphRead | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: (settingsOverride?: PlatformSettings) => Promise<void>;
  chooseScope: (workspaceId: string, projectId?: string) => PlatformSettings;
  selectResource: (resourceId: string) => Promise<void>;
  client: <T>(path: string, init?: RequestInit) => Promise<T>;
};

const PlatformContext = createContext<PlatformState | null>(null);

function emptyData() {
  return {
    workspaces: [] as Workspace[], workspace: null as Workspace | null, projects: [] as Project[], project: null as Project | null,
    provider: null as ProviderHealth | null, agents: [] as AgentProfile[], agent: null as AgentProfile | null, resources: [] as Resource[], reviewItems: [] as ReviewItem[], usageItems: [] as UsageItem[], members: [] as WorkspaceMember[], auditEvents: [] as AuditEvent[], selectedResourceId: '', snapshots: [] as Snapshot[], indexRuns: [] as IndexRun[], graph: null as GraphRead | null,
  };
}

export function PlatformProvider({ children }: { children: ReactNode }) {
  const [settings, setSettingsState] = useState<PlatformSettings>(loadSettings);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsByWorkspace, setProjectsByWorkspace] = useState<Record<string, Project[]>>({});
  const [project, setProject] = useState<Project | null>(null);
  const [provider, setProvider] = useState<ProviderHealth | null>(null);
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [agent, setAgent] = useState<AgentProfile | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [usageItems, setUsageItems] = useState<UsageItem[]>([]);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [selectedResourceId, setSelectedResourceId] = useState('');
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [indexRuns, setIndexRuns] = useState<IndexRun[]>([]);
  const [graph, setGraph] = useState<GraphRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const client = useCallback(<T,>(path: string, init?: RequestInit) => apiFetch<T>(settings, path, init), [settings]);

  const applySession = useCallback((next: PlatformSettings) => {
    setSettingsState(next);
    saveSettings(next);
  }, []);

  const clearPlatformData = useCallback(() => {
    const data = emptyData();
    setWorkspaces(data.workspaces); setWorkspace(data.workspace); setProjects(data.projects); setProjectsByWorkspace({}); setProject(data.project); setProvider(data.provider); setAgents(data.agents); setAgent(data.agent); setResources(data.resources); setReviewItems(data.reviewItems); setUsageItems(data.usageItems); setMembers(data.members); setAuditEvents(data.auditEvents); setSelectedResourceId(data.selectedResourceId); setSnapshots(data.snapshots); setIndexRuns(data.indexRuns); setGraph(data.graph);
  }, []);

  const chooseScope = useCallback((workspaceId: string, projectId?: string) => {
    const next = { ...settings, workspaceId, projectId: projectId ?? settings.projectId };
    applySession(next);
    return next;
  }, [applySession, settings]);

  const loadResourceDetails = useCallback(async (resourceId: string) => {
    if (!resourceId || !settings.workspaceId || !settings.projectId) return;
    const { workspaceId, projectId } = settings;
    const [nextSnapshots, nextRuns, nextGraph] = await Promise.all([
      client<Snapshot[]>(`/workspaces/${workspaceId}/projects/${projectId}/resources/${resourceId}/snapshots`),
      client<IndexRun[]>(`/workspaces/${workspaceId}/projects/${projectId}/resources/${resourceId}/index-runs`),
      client<GraphRead>(`/workspaces/${workspaceId}/projects/${projectId}/resources/${resourceId}/graph`).catch(() => null),
    ]);
    setSnapshots(nextSnapshots);
    setIndexRuns(nextRuns);
    setGraph(nextGraph);
  }, [client, settings]);

  const hydrateIdentity = useCallback(async (baseSettings: PlatformSettings): Promise<PlatformSettings | null> => {
    if (!baseSettings.sessionToken.trim()) return null;
    const identity = await apiFetch<CurrentUserResponse>(baseSettings, '/auth/me');
    setCurrentUser(identity.user);
    const workspaceId = baseSettings.workspaceId || identity.default_workspace_id || identity.workspaces[0]?.id || '';
    const projectOptions = workspaceId ? identity.projects_by_workspace[workspaceId] ?? [] : [];
    const projectId = baseSettings.projectId || identity.default_project_id || projectOptions[0]?.id || '';
    const next = { ...baseSettings, workspaceId, projectId };
    applySession(next);
    setWorkspaces(identity.workspaces);
    setProjectsByWorkspace(identity.projects_by_workspace);
    setMembers(identity.memberships);
    setWorkspace(identity.workspaces.find((item) => item.id === workspaceId) ?? null);
    setProjects(projectOptions);
    setProject(projectOptions.find((item) => item.id === projectId) ?? null);
    return next;
  }, [applySession]);

  const reload = useCallback(async (settingsOverride?: PlatformSettings) => {
    const baseSettings = settingsOverride ?? settings;
    setLoading(true); setError(null);
    try {
      const activeSettings = await hydrateIdentity(baseSettings);
      if (!activeSettings?.sessionToken.trim() || !activeSettings.workspaceId || !activeSettings.projectId) {
        clearPlatformData();
        return;
      }
      const { workspaceId, projectId } = activeSettings;
      const activeClient = <T,>(path: string, init?: RequestInit) => apiFetch<T>(activeSettings, path, init);
      const [providerHealth, nextAgents, nextAgent, nextResources, review, usage, memberList, events] = await Promise.all([
        activeClient<ProviderHealth>('/provider-health').catch((err) => ({ status: 'degraded', embedding: { namespace: 'unavailable', dev_quality: true, status: 'error', provider: 'unknown', model: String(err) } })),
        activeClient<AgentProfile[]>(`/workspaces/${workspaceId}/agents`),
        activeClient<AgentProfile>(`/workspaces/${workspaceId}/projects/${projectId}/agent-profile`),
        activeClient<Resource[]>(`/workspaces/${workspaceId}/projects/${projectId}/resources`),
        activeClient<{ resources: ReviewItem[] }>(`/workspaces/${workspaceId}/projects/${projectId}/resource-review`),
        activeClient<{ resources: UsageItem[] }>(`/workspaces/${workspaceId}/projects/${projectId}/resource-usage`),
        activeClient<WorkspaceMember[]>(`/workspaces/${workspaceId}/members`).catch(() => []),
        activeClient<AuditEvent[]>(`/workspaces/${workspaceId}/audit-events`).catch(() => []),
      ]);
      setProvider(providerHealth); setAgents(nextAgents); setAgent(nextAgent); setResources(nextResources); setReviewItems(review.resources); setUsageItems(usage.resources); setMembers(memberList); setAuditEvents(events);
      const current = nextResources.find((resource) => resource.id === selectedResourceId && resource.status === 'active');
      const preferred = current ?? nextResources.find((resource) => resource.name.includes('AngiBrain') && resource.status === 'active') ?? nextResources[0];
      if (preferred) { setSelectedResourceId(preferred.id); await loadResourceDetails(preferred.id); }
    } catch (err) {
      setError(String(err));
    } finally { setLoading(false); }
  }, [clearPlatformData, hydrateIdentity, loadResourceDetails, selectedResourceId, settings]);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true); setError(null);
    try {
      const response = await anonymousFetch<LoginResponse>(settings, '/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
      const workspaceId = response.default_workspace_id ?? response.workspaces[0]?.id ?? '';
      const projectId = response.default_project_id ?? (workspaceId ? response.projects_by_workspace[workspaceId]?.[0]?.id : '') ?? '';
      const next = { ...settings, sessionToken: response.session_token, workspaceId, projectId };
      applySession(next);
      setCurrentUser(response.user);
      setWorkspaces(response.workspaces);
      setProjectsByWorkspace(response.projects_by_workspace);
      setMembers(response.memberships);
      setWorkspace(response.workspaces.find((item) => item.id === workspaceId) ?? null);
      const projectOptions = workspaceId ? response.projects_by_workspace[workspaceId] ?? [] : [];
      setProjects(projectOptions);
      setProject(projectOptions.find((item) => item.id === projectId) ?? null);
      if (workspaceId && projectId) {
        const activeClient = <T,>(path: string, init?: RequestInit) => apiFetch<T>(next, path, init);
        const [providerHealth, nextAgents, nextAgent, nextResources, review, usage, memberList, events] = await Promise.all([
          activeClient<ProviderHealth>('/provider-health').catch((err) => ({ status: 'degraded', embedding: { namespace: 'unavailable', dev_quality: true, status: 'error', provider: 'unknown', model: String(err) } })),
          activeClient<AgentProfile[]>(`/workspaces/${workspaceId}/agents`),
          activeClient<AgentProfile>(`/workspaces/${workspaceId}/projects/${projectId}/agent-profile`),
          activeClient<Resource[]>(`/workspaces/${workspaceId}/projects/${projectId}/resources`),
          activeClient<{ resources: ReviewItem[] }>(`/workspaces/${workspaceId}/projects/${projectId}/resource-review`),
          activeClient<{ resources: UsageItem[] }>(`/workspaces/${workspaceId}/projects/${projectId}/resource-usage`),
          activeClient<WorkspaceMember[]>(`/workspaces/${workspaceId}/members`).catch(() => []),
          activeClient<AuditEvent[]>(`/workspaces/${workspaceId}/audit-events`).catch(() => []),
        ]);
        setProvider(providerHealth); setAgents(nextAgents); setAgent(nextAgent); setResources(nextResources); setReviewItems(review.resources); setUsageItems(usage.resources); setMembers(memberList); setAuditEvents(events);
      }
    } catch (err) { setError(String(err)); throw err; }
    finally { setLoading(false); }
  }, [applySession, settings]);

  const logout = useCallback(async () => {
    try { if (settings.sessionToken) await client('/auth/logout', { method: 'POST' }); } catch {}
    const next = { ...settings, sessionToken: '', workspaceId: '', projectId: '' };
    applySession(next); setCurrentUser(null); clearPlatformData();
  }, [applySession, clearPlatformData, client, settings]);

  const selectResource = useCallback(async (resourceId: string) => {
    setSelectedResourceId(resourceId); setLoading(true); setError(null);
    try { await loadResourceDetails(resourceId); }
    catch (err) { setError(String(err)); }
    finally { setLoading(false); }
  }, [loadResourceDetails]);

  useEffect(() => { void reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedResource = resources.find((resource) => resource.id === selectedResourceId) ?? null;
  const signedIn = Boolean(settings.sessionToken.trim() && currentUser);
  const value = useMemo(() => ({ settings, currentUser, signedIn, workspaces, workspace, projects, projectsByWorkspace, project, provider, agents, agent, resources, reviewItems, usageItems, members, auditEvents, selectedResourceId, selectedResource, snapshots, indexRuns, graph, loading, error, login, logout, reload, chooseScope, selectResource, client }), [settings, currentUser, signedIn, workspaces, workspace, projects, projectsByWorkspace, project, provider, agents, agent, resources, reviewItems, usageItems, members, auditEvents, selectedResourceId, selectedResource, snapshots, indexRuns, graph, loading, error, login, logout, reload, chooseScope, selectResource, client]);
  return <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>;
}

export function usePlatform() {
  const value = useContext(PlatformContext);
  if (!value) throw new Error('usePlatform must be used inside PlatformProvider');
  return value;
}
