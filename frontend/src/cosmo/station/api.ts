/**
 * Cosmoport 2.0 — Control Station REST API client.
 *
 * All requests fetch from `/api/v1/...` (no localStorage).
 */
import { getAccessToken, clearSessionOnUnauthorized } from '../auth/authStore';

export interface ForgeBinding {
  forge_type: 'gitea' | 'jenkins';
  url: string;
  token_ref: string;
}

export interface RepositoryBinding {
  forge_id: string;
  repo_path: string;
  default_branch: string;
  webhook_id?: string | null;
}

export interface Application {
  id: string;
  domain_id?: string;
  project_id?: string | null;
  level: number;
  group_id?: string | null;
  repo_binding: RepositoryBinding;
  pipeline_plan_id?: string | null;
  artifact_kind?: string;
  status?: string;
}

// ── COS-096: live forge surface ─────────────────────────────────────

export interface ForgeLastPush {
  app_id: string;
  repo_path: string;
  bound: boolean;
  last_push: {
    repo_path: string;
    branch: string;
    head_sha: string;
    pusher: string;
    commit_count: number;
    received_at: string;
    source: string;
  } | null;
  recent_commits: Array<{
    sha: string;
    message: string;
    author: string;
    timestamp: string;
  }>;
  forge_unreachable: string | null;
}

// ── FR-003: Project types ──────────────────────────────────────────

export interface Project {
  id: string;
  name: string;
  description?: string;
  kits_tags: string[];
  app_count: number;
  l0_count: number;
  l1_count: number;
  l2_count: number;
  status: 'active' | 'archived' | 'planning';
  last_release?: string;
  last_release_date?: string;
  updated_at: string;
  created_by?: string;
  team?: ProjectMember[];
}

export interface ProjectMember {
  id: string;
  name: string;
  email: string;
  role: 'it_leader' | 'developer' | 'secops' | 'devops' | 'qa';
  inherited: boolean;
}

export interface KitsTag {
  id: string;
  label: string;
  color?: string;
}

// ── NX-FLASH-05: Release Type ──────────────────────────────────────

export interface ReleaseStep {
  id: string;
  name: string;
  order: number;
  required: boolean;
  enabled: boolean;
  failure_policy: 'continue' | 'terminate';
}

export interface ReleaseType {
  id: string;
  name: string;
  applicable_app_kinds: string[];
  levels: number[];
  artifact_kind: string;
  steps: ReleaseStep[];
  gates: string[];
  prettyk_check_enabled: boolean;
  package_rules: Record<string, unknown>;
}

// ── NX-FLASH-06: Batch Release ─────────────────────────────────────

export interface BatchRelease {
  id: string;
  project_id: string;
  apps: BatchReleaseApp[];
  template_release_type_id?: string;
  status: 'pending' | 'running' | 'partial' | 'success' | 'failed';
  created_at: string;
}

export interface BatchReleaseApp {
  app_id: string;
  app_name?: string;
  release_type_id: string;
  overrides?: Record<string, unknown>;
  status: 'queued' | 'running' | 'success' | 'failed' | 'blocked';
  block_reason?: string;
  child_release_id?: string;
}

// ── NX-FLASH-03: Project Graph ─────────────────────────────────────

export interface ProjectGraph {
  project_id: string;
  nodes: ProjectGraphNode[];
  edges: ProjectGraphEdge[];
}

export interface ProjectGraphNode {
  id: string;
  label: string;
  type: 'app' | 'library';
  level: number;
  x: number;
  y: number;
  app_id: string;
  project_id: string;
  status?: string;
}

export interface ProjectGraphEdge {
  id: string;
  from: string;
  to: string;
  relation: 'depends_on' | 'uses_library';
}

export interface Group {
  id: string;
  project_id?: string;
  parent_group_id?: string | null;
  level: number;
  name: string;
}

export interface BrickDefinition {
  executor: 'woodpecker' | 'jenkins' | 'github-actions';
  image: string;
  timeout_s: number;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
}

export type BrickType = 'sast' | 'sca' | 'build' | 'deploy' | 'dast' | 'autotest' | 'gate';

export interface PipelineBrick {
  id: string;
  name: string;
  type: BrickType;
  source: string;
  definition: BrickDefinition;
  depends_on: string[];
  gates: string[];
}

export interface PipelinePlan {
  id: string;
  app_id: string;
  level: string;
  scope_id: string;
  compiled_at: string;
  compiled_hash: string;
  brick_ids: string[];
}

export type BatchStatus = 'pending' | 'running' | 'passed' | 'failed' | 'blocked';

export interface Batch {
  id: string;
  plan_id: string;
  type: string;
  status: BatchStatus;
  bricks: string[];
  artifacts: string[];
  evidence: string[];
}

export type RunStatus =
  | 'draft'
  | 'pending'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'blocked'
  | 'cancelled';

export interface Run {
  id: string;
  plan_id: string;
  trigger: 'scheduled' | 'pre_release' | 'emergency' | 'manual';
  initiator: string;
  domain_id?: string;
  project_id?: string;
  status: RunStatus;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  batches: Batch[];
  gates: string[];
  findings: string[];
  evidence_ledger_ref?: string | null;
}

export interface GatePolicyRule {
  finding_type: string;
  action: 'block' | 'warn' | 'pass';
  max_count?: number | null;
}

export interface GatePolicy {
  rules: GatePolicyRule[];
}

export interface Gate {
  id: string;
  type: 'automatic' | 'manual';
  position: number;
  policy: GatePolicy;
  decision?: 'pass' | 'block' | 'manual_required' | null;
  decided_by?: string | null;
  signature?: string | null;
  decided_at?: string | null;
}

export interface EvidenceEntry {
  id: string;
  run_id: string;
  batch_id?: string | null;
  type: 'screenshot' | 'raw_request' | 'raw_response' | 'log' | 'alert' | 'finding' | 'decision';
  content_ref?: string | null;
  content_hash?: string | null;
  provenance_json: Record<string, unknown>;
  created_at: string;
}

/**
 * COS-098 (контракт-первым): Release-типы сверены с backend
 * domain/release_model.Release + api/routes/releases.py (response_model).
 * Старый FE-прототип (name / manifest / zone 'ЗР' / history) на бэкенде
 * не существовал — удалён, чтобы UI не рендерил выдуманные поля.
 */
export type ReleaseZone = 'zr' | 'zt' | 'zpe';

export type ReleaseStatus =
  | 'draft'
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'deploying'
  | 'deployed'
  | 'rollback';

export type ReleaseTrigger = 'scheduled' | 'pre_release' | 'emergency' | 'manual';

export interface ReleaseApproval {
  decided_by: string;
  decision: 'approved' | 'rejected';
  comment: string;
  decided_at: string;
  signature?: string | null;
}

export interface TransferRecord {
  from_zone: ReleaseZone;
  to_zone: ReleaseZone;
  initiated_by: string;
  gate_check_passed: boolean;
  transferred_at: string;
  comment: string;
}

export interface Release {
  id: string;
  domain_id: string;
  plan_id: string;
  run_ids: string[];
  trigger: ReleaseTrigger;
  status: ReleaseStatus;
  changelog: string;
  version: string;
  artifacts: string[];
  approvals: ReleaseApproval[];
  current_zone: ReleaseZone;
  transfer_history: TransferRecord[];
}

/** COS-098: POST /api/v1/releases (CreateReleaseRequest). */
export interface CreateReleaseRequest {
  id: string;
  domain_id: string;
  plan_id: string;
  run_ids: string[];
  trigger?: ReleaseTrigger;
  changelog?: string;
  version?: string;
}

/** COS-098: POST /api/v1/releases/{id}/transfer (SAN-009 TransferReleaseRequest). */
export interface TransferReleaseRequest {
  target_zone: ReleaseZone;
  officer_name: string;
  sign_signature: string;
  token_2fa?: string;
  transfer_notes?: string;
}

/** COS-098: GET /api/v1/domains (domain_model.Domain). */
export interface CosmoDomain {
  id: string;
  label: string;
  forge_binding: Record<string, unknown>;
  rbac_config: Record<string, unknown>;
  quota: Record<string, unknown>;
}

/** COS-098: GET /api/v1/gates/trail/runs/{run_id} (gate_trail_repo._to_dict). */
export interface GateDecisionRecord {
  id: number;
  gate_id: string;
  plan_id: string;
  run_id: string | null;
  batch_id: string | null;
  decision: string;
  decided_by: string;
  initiator: string;
  signature: string | null;
  policy_snapshot: Record<string, unknown>;
  evidence_ids: string[];
  decided_at: string | null;
  created_at: string | null;
}

/** COS-098: GET /api/v1/runs/{run_id}/evidence (EvidenceLedger.verify_and_get). */
export interface EvidenceChain {
  entries: EvidenceEntry[];
  length: number;
  verified: boolean;
  last_hash: string | null;
}

export interface EvidenceTamperDetail {
  index: number;
  entry_id: string;
  reason: string;
  stored_hash: string | null;
  recomputed_hash: string | null;
}

export interface EvidenceBrokenLink {
  index: number;
  entry_id: string;
  expected_prev_hash: string | null;
  stored_prev_hash: string | null;
}

export interface EvidenceChainResult {
  chain: EvidenceChain;
  verified: boolean;
  integrity: 'ok' | 'tampered' | 'unsealed' | 'head_mismatch';
  anchor: {
    enabled: boolean;
    status: 'ok' | 'head_mismatch' | 'unknown_anchor' | 'disabled';
    anchored_head: string | null;
    computed_head: string | null;
    anchored_at: string | null;
    detail: string;
  } | null;
  head_mismatch: boolean;
  tampered_entries: number[];
  tampered_details: EvidenceTamperDetail[];
  broken_links: EvidenceBrokenLink[];
  unsealed_entries: string[];
  tampered_chain: boolean;
  replay_count: number;
  total_entries: number;
}

export interface AuditEvent {
  id: string;
  timestamp: string;
  user_id: string;
  role: string;
  action: string;
  resource_type: string;
  resource_id: string;
  status: 'success' | 'failed' | 'blocked';
  ip_address: string;
  details_json: Record<string, unknown>;
}

export interface TrendDataPoint {
  date: string;
  value: number;
}

export interface FlakyGate {
  gate_id: string;
  plan_id: string;
  total_decisions: number;
  blocks: number;
  block_rate: number;
  passes: number;
}

export interface MetricsTrends {
  domain_id: string;
  days: number;
  pass_rate_trend: TrendDataPoint[];
  findings_severity_trend: Array<{ date: string; critical: number; high: number; medium: number }>;
  mean_duration_trend: TrendDataPoint[];
  flaky_gates: FlakyGate[];
  summary: {
    total_runs: number;
    pass_rate_pct: number;
    failed_runs: number;
    mean_duration_seconds: number;
    total_critical_findings: number;
    last_updated: string;
  };
}

// ── SAN-017: Builds & Deployments ──────────────────────────────────

export interface Build {
  id: string;
  app_id: string;
  app_name?: string;
  title: string;
  commit_sha: string;
  branch: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'aborted';
  artifacts?: string[];
  started_at?: string;
  finished_at?: string;
  initiator?: string;
}

export interface Deployment {
  id: string;
  app_id: string;
  app_name?: string;
  build_id: string;
  segment: 'bare' | 'integration';
  target_zone: 'zr' | 'zt' | 'zpe';
  runtime_name: string;
  custom_url?: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'deleted';
  started_at?: string;
  operator?: string;
}

export type BuildStatus = Build['status'];
export type DeploymentStatus = Deployment['status'];

// ── Fetch Wrappers ──────────────────────────────────────────────────

/**
 * COS-158: auth token берётся из боевой сессии (authStore). Dev-stub удалён —
 * без сессии Authorization не шлётся вовсе.
 */
export function getCosmoAuthToken(): string {
  return getAccessToken() ?? '';
}

/**
 * COS-098: домен-контекст для domain-scoped REST (X-Cosmo-Domain).
 * system admin: заголовок = context switch (выбор домена в readiness-виде);
 * не-админ: сервер резолвит домен по identity, заголовок игнорирует —
 * обе роли безопасны (domain_guard.resolve_caller_domain).
 */
let cosmoDomainHeader: string | null = null;
export function setCosmoDomain(domainId: string | null): void {
  cosmoDomainHeader = domainId;
  try {
    if (domainId) globalThis.localStorage?.setItem('cosmo_domain', domainId);
    else globalThis.localStorage?.removeItem('cosmo_domain');
  } catch { /* no localStorage (tests) */ }
}
try {
  cosmoDomainHeader = globalThis.localStorage?.getItem('cosmo_domain') ?? null;
} catch { /* no localStorage (tests) */ }

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (init?.headers) {
    const extra = init.headers as Record<string, string>;
    Object.assign(headers, extra);
  }
  const token = getCosmoAuthToken();
  if (!headers.Authorization && token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (!headers['X-Cosmo-Domain'] && cosmoDomainHeader) {
    headers['X-Cosmo-Domain'] = cosmoDomainHeader;
  }
  const res = await fetch(url, { ...init, headers });
  if (res.status === 401) {
    // COS-158: токен больше не валиден → сброс сессии (UI вернётся на login).
    clearSessionOnUnauthorized();
  }
  if (!res.ok) {
    let errDetail = `${res.status} ${res.statusText}`;
    try {
      const json = await res.json();
      if (json && json.detail) errDetail = typeof json.detail === 'string' ? json.detail : JSON.stringify(json.detail);
    } catch {
      // ignore
    }
    throw new Error(errDetail);
  }
  if (res.status === 204) {
    return undefined as unknown as T;
  }
  return res.json();
}

export const api = {
  // Apps
  getApps: (projectId?: string, kitsTag?: string) => {
    const q = new URLSearchParams();
    if (projectId) q.set('project_id', projectId);
    if (kitsTag) q.set('kits_tag', kitsTag);
    const qs = q.toString();
    return apiFetch<Application[]>(`/api/v1/apps${qs ? `?${qs}` : ''}`);
  },
  createApp: (data: Partial<Application> & { repo_binding: RepositoryBinding }) =>
    apiFetch<Application>('/api/v1/apps', { method: 'POST', body: JSON.stringify(data) }),
  deleteApp: (id: string) => apiFetch<void>(`/api/v1/apps/${id}`, { method: 'DELETE' }),

  // COS-096: live forge surface (ПУ видит коммиты)
  getAppForgeLastPush: (appId: string) =>
    apiFetch<ForgeLastPush>(`/api/v1/apps/${encodeURIComponent(appId)}/forge/last-push`),

  // Groups
  getGroups: (projectId?: string) =>
    apiFetch<Group[]>(`/api/v1/groups${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`),
  createGroup: (data: Group) => apiFetch<Group>('/api/v1/groups', { method: 'POST', body: JSON.stringify(data) }),
  deleteGroup: (id: string) => apiFetch<void>(`/api/v1/groups/${id}`, { method: 'DELETE' }),

  // Bricks
  getBricks: (type?: BrickType) =>
    apiFetch<PipelineBrick[]>(`/api/v1/bricks${type ? `?type=${type}` : ''}`),
  createBrick: (data: PipelineBrick) =>
    apiFetch<PipelineBrick>('/api/v1/bricks', { method: 'POST', body: JSON.stringify(data) }),
  deleteBrick: (id: string) => apiFetch<void>(`/api/v1/bricks/${id}`, { method: 'DELETE' }),

  // Plans
  getPlans: (appId?: string) =>
    apiFetch<PipelinePlan[]>(`/api/v1/plans${appId ? `?app_id=${appId}` : ''}`),
  createPlan: (data: { id: string; app_id: string; brick_ids: string[]; level?: string }) =>
    apiFetch<PipelinePlan>('/api/v1/plans', { method: 'POST', body: JSON.stringify(data) }),
  compilePlan: (data: { plan_id: string; app_id: string; brick_ids: string[]; level?: string }) =>
    apiFetch<PipelinePlan>('/api/v1/plans/compile', { method: 'POST', body: JSON.stringify(data) }),
  deletePlan: (id: string) => apiFetch<void>(`/api/v1/plans/${id}`, { method: 'DELETE' }),

  // Runs
  getRuns: (filter?: { projectId?: string; status?: string; planId?: string }) => {
    const q = new URLSearchParams();
    if (filter?.projectId) q.set('project_id', filter.projectId);
    if (filter?.status) q.set('status', filter.status);
    if (filter?.planId) q.set('plan_id', filter.planId);
    const qs = q.toString();
    return apiFetch<Run[]>(`/api/v1/runs${qs ? `?${qs}` : ''}`);
  },
  getRun: (id: string) => apiFetch<Run>(`/api/v1/runs/${id}`),
  createRun: (data: { id: string; plan_id: string; project_id?: string; trigger?: string; initiator_user_id?: string }) =>
    apiFetch<Run>('/api/v1/runs', { method: 'POST', body: JSON.stringify(data) }),
  updateRunStatus: (id: string, status: RunStatus) =>
    apiFetch<Run>(`/api/v1/runs/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  cancelRun: (id: string) =>
    apiFetch<Run>(`/api/v1/runs/${id}/cancel`, { method: 'POST' }),

  // Batches
  getBatches: (planId?: string) =>
    apiFetch<Batch[]>(`/api/v1/batches${planId ? `?plan_id=${planId}` : ''}`),
  updateBatchStatus: (id: string, status: BatchStatus) =>
    apiFetch<Batch>(`/api/v1/batches/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),

  // Gates
  getGates: (planId?: string) =>
    apiFetch<Gate[]>(`/api/v1/gates${planId ? `?plan_id=${planId}` : ''}`),
  createGate: (data: { id: string; plan_id: string; type: 'automatic' | 'manual'; position: number; policy: GatePolicy }) =>
    apiFetch<Gate>('/api/v1/gates', { method: 'POST', body: JSON.stringify(data) }),
  submitGateDecision: (id: string, data: { decision: 'pass' | 'block' | 'manual_required'; decided_by?: string; signature?: string }) =>
    apiFetch<Gate>(`/api/v1/gates/${id}/decision`, { method: 'POST', body: JSON.stringify(data) }),
  updateGate: (id: string, data: { type?: 'automatic' | 'manual'; position?: number; policy?: GatePolicy }) =>
    apiFetch<Gate>(`/api/v1/gates/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Releases (COS-098: контракт сверён с api/routes/releases.py)
  getReleases: (statusFilter?: string) =>
    apiFetch<Release[]>(`/api/v1/releases${statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : ''}`),
  getRelease: (id: string) => apiFetch<Release>(`/api/v1/releases/${id}`),
  createRelease: (data: CreateReleaseRequest) =>
    apiFetch<Release>('/api/v1/releases', { method: 'POST', body: JSON.stringify(data) }),
  transferRelease: (id: string, data: TransferReleaseRequest) =>
    apiFetch<Release>(`/api/v1/releases/${id}/transfer`, { method: 'POST', body: JSON.stringify(data) }),

  // COS-098: domains (для выборки домена в readiness-поверхности и SSE-стрима)
  getDomains: () => apiFetch<CosmoDomain[]>('/api/v1/domains'),

  // COS-098: evidence chain + gate decision trail
  getEvidenceChain: (runId: string) =>
    apiFetch<EvidenceChainResult>(`/api/v1/runs/${encodeURIComponent(runId)}/evidence`),
  getRunTrail: (runId: string) =>
    apiFetch<GateDecisionRecord[]>(`/api/v1/gates/trail/runs/${encodeURIComponent(runId)}`),

  // Repos & Web IDE files
  getRepoTree: (repo: string) =>
    apiFetch<Array<{ name: string; path: string; kind: 'file' | 'dir'; size?: number; children?: unknown[] }>>(
      `/api/v1/repos/tree?repo=${encodeURIComponent(repo)}`
    ),
  getRepoFile: (repo: string, path: string) =>
    apiFetch<{ repo: string; path: string; content: string; sha: string }>(
      `/api/v1/repos/file?repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}`
    ),
  saveRepoFile: (data: { repo: string; path: string; content: string; message?: string }) =>
    apiFetch<{ repo: string; path: string; content: string; sha: string }>('/api/v1/repos/file', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  commitAndPush: (data: { repo: string; branch?: string; message: string; files: Array<{ path: string; content: string }> }) =>
    apiFetch<{ ok: boolean; commit_hash: string; branch: string; repo: string; message: string }>('/api/v1/repos/commit', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  commitAndRun: (data: { repo: string; branch?: string; message: string; plan_id: string; project_id?: string; files: Array<{ path: string; content: string }> }) =>
    apiFetch<{ ok: boolean; commit_hash: string; branch: string; repo: string; message: string; run_id: string }>('/api/v1/repos/commit-and-run', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Audit Logs
  getAuditEvents: (filter?: { userId?: string; action?: string; resourceType?: string; status?: string }) => {
    const q = new URLSearchParams();
    if (filter?.userId) q.set('user_id', filter.userId);
    if (filter?.action && filter.action !== 'all') q.set('action', filter.action);
    if (filter?.resourceType && filter.resourceType !== 'all') q.set('resource_type', filter.resourceType);
    if (filter?.status && filter.status !== 'all') q.set('status', filter.status);
    const qs = q.toString();
    return apiFetch<AuditEvent[]>(`/api/v1/audit${qs ? `?${qs}` : ''}`);
  },
  createAuditEvent: (data: Partial<AuditEvent>) =>
    apiFetch<AuditEvent>('/api/v1/audit', { method: 'POST', body: JSON.stringify(data) }),

  // Metrics Trends
  getMetricsTrends: (projectId?: string, days?: number) => {
    const q = new URLSearchParams();
    if (projectId) q.set('project_id', projectId);
    if (days) q.set('days', String(days));
    const qs = q.toString();
    return apiFetch<MetricsTrends>(`/api/v1/metrics/trends${qs ? `?${qs}` : ''}`);
  },

  // ── SAN-017: Builds API ──────────────────────────────────────────
  getAppBuilds: (appId: string) =>
    apiFetch<Build[]>(`/api/v1/builds?app_id=${encodeURIComponent(appId)}`),

  createBuild: (appId: string, data: { title: string; branch: string; commit_sha: string }) =>
    apiFetch<Build>(`/api/v1/builds`, {
      method: 'POST',
      body: JSON.stringify({ ...data, app_id: appId }),
    }),

  getAllBuilds: (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    return apiFetch<Build[]>(`/api/v1/builds${q}`);
  },

  // ── SAN-017: Deployments API ─────────────────────────────────────
  getAppDeployments: (appId: string) =>
    apiFetch<Deployment[]>(`/api/v1/deployments?app_id=${encodeURIComponent(appId)}`),

  createDeployment: (appId: string, data: { build_id: string; target_zone: string; segment: string; runtime_id: string }) =>
    apiFetch<Deployment>(`/api/v1/deployments`, {
      method: 'POST',
      body: JSON.stringify({ ...data, app_id: appId }),
    }),

  getAllDeployments: (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    return apiFetch<Deployment[]>(`/api/v1/deployments${q}`);
  },

  rollbackDeployment: (deployId: string) =>
    apiFetch<void>(`/api/v1/deployments/${encodeURIComponent(deployId)}/rollback`, { method: 'POST' }),

  // ── SAN-017: App Settings ────────────────────────────────────────
  updateAppSettings: (appId: string, settings: Record<string, unknown>) =>
    apiFetch<void>(`/api/v1/apps/${encodeURIComponent(appId)}/settings`, {
      method: 'PUT',
      body: JSON.stringify(settings),
    }),

  // ── FR-003/004: Projects API ─────────────────────────────────────
  getProjects: (kitsTag?: string) => {
    const q = kitsTag && kitsTag !== 'all' ? `?kits_tag=${encodeURIComponent(kitsTag)}` : '';
    return apiFetch<Project[]>(`/api/v1/projects${q}`);
  },
  getProject: (id: string) => apiFetch<Project>(`/api/v1/projects/${encodeURIComponent(id)}`),
  createProject: (data: { name: string; description?: string; kits_tags: string[] }) =>
    apiFetch<Project>('/api/v1/projects', { method: 'POST', body: JSON.stringify(data) }),
  deleteProject: (id: string) => apiFetch<void>(`/api/v1/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  updateProject: (id: string, data: Partial<Project>) =>
    apiFetch<Project>(`/api/v1/projects/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }),

  getKitsTags: () =>
    apiFetch<KitsTag[]>('/api/v1/kits/tags'),

  // ── NX-FLASH-03: Project Graph ────────────────────────────────────
  getProjectGraph: (projectId: string) =>
    apiFetch<ProjectGraph>(`/api/v1/projects/${encodeURIComponent(projectId)}/graph`),
  createProjectEdge: (projectId: string, data: { from: string; to: string; relation: string }) =>
    apiFetch<ProjectGraphEdge>(`/api/v1/projects/${encodeURIComponent(projectId)}/edges`, { method: 'POST', body: JSON.stringify(data) }),
  deleteProjectEdge: (projectId: string, edgeId: string) =>
    apiFetch<void>(`/api/v1/projects/${encodeURIComponent(projectId)}/edges/${encodeURIComponent(edgeId)}`, { method: 'DELETE' }),

  // ── NX-FLASH-04: Flat Applications ────────────────────────────────
  getAllApps: (filter?: { projectId?: string; kitsTag?: string; level?: number; status?: string }) => {
    const q = new URLSearchParams();
    if (filter?.projectId) q.set('project_id', filter.projectId);
    if (filter?.kitsTag) q.set('kits_tag', filter.kitsTag);
    if (filter?.level !== undefined) q.set('level', String(filter.level));
    if (filter?.status) q.set('status', filter.status);
    const qs = q.toString();
    return apiFetch<Application[]>(`/api/v1/apps${qs ? `?${qs}` : ''}`);
  },

  // ── NX-FLASH-05: Release Types ────────────────────────────────────
  getReleaseTypes: () => apiFetch<ReleaseType[]>('/api/v1/release-types'),
  createReleaseType: (data: Partial<ReleaseType>) =>
    apiFetch<ReleaseType>('/api/v1/release-types', { method: 'POST', body: JSON.stringify(data) }),
  updateReleaseType: (id: string, data: Partial<ReleaseType>) =>
    apiFetch<ReleaseType>(`/api/v1/release-types/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteReleaseType: (id: string) =>
    apiFetch<void>(`/api/v1/release-types/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // ── NX-FLASH-06: Batch Releases ───────────────────────────────────
  getBatchReleases: (projectId: string) =>
    apiFetch<BatchRelease[]>(`/api/v1/projects/${encodeURIComponent(projectId)}/batch-releases`),
  createBatchRelease: (projectId: string, data: { apps: Array<{ app_id: string; release_type_id: string; overrides?: Record<string, unknown> }>; template_release_type_id?: string }) =>
    apiFetch<BatchRelease>(`/api/v1/projects/${encodeURIComponent(projectId)}/batch-releases`, { method: 'POST', body: JSON.stringify(data) }),
  retryChildRelease: (batchId: string, appId: string) =>
    apiFetch<BatchReleaseApp>(`/api/v1/batch-releases/${encodeURIComponent(batchId)}/apps/${encodeURIComponent(appId)}/retry`, { method: 'POST' }),

  // ── POST-FLASH-001: Project Composition ─────────────────────────────
  createProjectCompose: (data: ProjectComposeRequest) =>
    apiFetch<ProjectComposeResult>('/api/v1/projects/compose', { method: 'POST', body: JSON.stringify(data) }),

  // ── POST-FLASH-001: Standalone App ──────────────────────────────────
  createStandaloneApp: (data: StandaloneAppRequest) =>
    apiFetch<Application>('/api/v1/apps/standalone', { method: 'POST', body: JSON.stringify(data) }),

  // ── POST-FLASH-001: Public Library ──────────────────────────────────
  createPublicLibrary: (data: PublicLibraryRequest) =>
    apiFetch<Application>('/api/v1/libraries', { method: 'POST', body: JSON.stringify(data) }),

  // ── COS-061: Durable Notification Inbox ──────────────────────────
  getInbox: (unreadOnly = false, limit = 100): Promise<InboxNotification[]> => {
    const q = new URLSearchParams({ unread_only: String(unreadOnly), limit: String(limit) });
    return apiFetch<InboxNotification[]>(`/api/v1/notifications/inbox?${q}`).then((rows) =>
      // Backend InboxItem contract: event_type + is_read → frontend shape
      (rows || []).map((r) => ({
        ...r,
        notification_type: (r as unknown as { event_type?: string }).event_type ?? (r as unknown as InboxNotification).notification_type ?? '',
        read: (r as unknown as { is_read?: boolean }).is_read ?? (r as unknown as InboxNotification).read ?? false,
      })),
    );
  },
  getUnreadCount: () => apiFetch<UnreadCount>('/api/v1/notifications/inbox/unread-count'),
  markNotificationRead: (notificationId: string) =>
    apiFetch<ReadResult>(`/api/v1/notifications/inbox/${encodeURIComponent(notificationId)}/read`, { method: 'POST' }),
  markAllNotificationsRead: () =>
    apiFetch<ReadResult>('/api/v1/notifications/inbox/read-all', { method: 'POST' }),

  // ── COS-075: SSE stream ticket (auth without bearer-in-URL) ──────────
  // EventSource не умеет custom headers — стрим открывается по short-TTL
  // ticket, привязанному к principal (bearer уходит только в этот POST).
  getSseTicket: () =>
    apiFetch<SseTicket>('/api/v1/notifications/sse-ticket', { method: 'POST' }),

  // ── COS-079: DLQ (dead letter queue) — operator surface ──────────────
  getDlq: (limit = 100): Promise<DlqItem[]> =>
    apiFetch<DlqItem[]>(`/api/v1/notifications/dlq?limit=${limit}`),
  replayDlq: (notificationId: string): Promise<DlqReplayResult> =>
    apiFetch<DlqReplayResult>(
      `/api/v1/notifications/dlq/${encodeURIComponent(notificationId)}/replay`,
      { method: 'POST' },
    ),
};

// ── POST-FLASH-001: Type definitions ──────────────────────────────────

export interface ProjectComposeRequest {
  name: string;
  description?: string;
  kits_tags: string[];
  folders: ComposeFolder[];
  team?: ComposeTeamMember[];
  enable_manifest?: boolean;
  artifact_kind?: string;
}

export interface ComposeFolder {
  name: string;
  path: string;
  proposed_apps: ComposeAppCandidate[];
}

export interface ComposeAppCandidate {
  name: string;
  kind: 'microservice' | 'gateway' | 'frontend' | 'library' | 'database' | 'broker';
  level: number;
  repo_path: string;
  branch: string;
  artifact_kind?: string;
  dependencies?: string[];
}

export interface ComposeTeamMember {
  name: string;
  email: string;
  role: 'it_leader' | 'developer' | 'secops' | 'devops' | 'qa';
}

export interface ProjectComposeResult {
  project_id: string;
  project_name: string;
  apps_created: number;
  repos_created: number;
  apps: Array<{ app_id: string; repo_path: string; status: string }>;
  validation_errors?: string[];
  graph_preview?: ProjectGraph;
}

export interface StandaloneAppRequest {
  id: string;
  level?: number;
  repo_path: string;
  branch: string;
  artifact_kind?: string;
  detected_profile?: string;
}

export interface PublicLibraryRequest {
  id: string;
  name: string;
  repo_path: string;
  branch: string;
  description?: string;
  team?: ComposeTeamMember[];
  visibility: 'internal' | 'public';
}

// ── COS-061: Durable Notification Inbox ──────────────────────────────

export type NotificationSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';
export type NotificationChannel = 'in_app' | 'email';
export type NotificationState = 'created' | 'pending' | 'sending' | 'sent' | 'delivered' | 'retryable_failure' | 'failed';

export interface InboxNotification {
  id: string;
  event_id: string;
  notification_type: string;
  severity: NotificationSeverity;
  title: string;
  message: string;
  channel: NotificationChannel;
  state: NotificationState;
  read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface UnreadCount {
  unread: number;
}

export interface ReadResult {
  ok: boolean;
  marked: number;
}

// COS-075: short-TTL ticket для SSE-стрима уведомлений
export interface SseTicket {
  ticket: string;
  recipient_id: string;
  expires_in: number;
}

// ── COS-079: DLQ (dead letter queue) — operator surface ──────────────

export interface DlqItem {
  id: string;
  event_id: string;
  event_type: string;
  severity: NotificationSeverity;
  title: string;
  recipient_id: string;
  channel: string;
  state: NotificationState;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface DlqReplayResult {
  id: string;
  state: NotificationState;
  attempts: number;
  last_error: string | null;
}
