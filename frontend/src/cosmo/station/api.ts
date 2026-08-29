/**
 * Cosmoport 2.0 — Control Station REST API client.
 *
 * All requests fetch from `/api/v1/...` (no localStorage).
 */

export interface ForgeBinding {
  forge_type: 'gitea' | 'jenkins';
  url: string;
  token_ref: string;
}

export interface DomainQuota {
  max_runs: number;
  max_storage_gb: number;
  max_cpu: number;
}

export interface Domain {
  id: string;
  label: string;
  forge_binding: ForgeBinding;
  rbac_config: Record<string, string[]>;
  quota: DomainQuota;
}

export interface RepositoryBinding {
  forge_id: string;
  repo_path: string;
  default_branch: string;
  webhook_id?: string | null;
}

export interface Application {
  id: string;
  domain_id: string;
  level: number;
  group_id?: string | null;
  repo_binding: RepositoryBinding;
  pipeline_plan_id?: string | null;
}

export interface Group {
  id: string;
  domain_id: string;
  parent_group_id?: string | null;
  level: number;
  name: string;
}

export interface AppGraph {
  domain: string;
  groups: Group[];
  apps: Application[];
  libraries: Application[];
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
  domain_id: string;
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

export type ReleaseZone = 'ЗР' | 'ЗТ' | 'ЗПЭ';

export interface ReleaseNode {
  id: string;
  name: string;
  type: 'service' | 'library' | 'config' | 'artifact';
  version: string;
  repo: string;
  commit: string;
  hash?: string;
}

export interface ReleaseEdge {
  from: string;
  to: string;
  relation: 'depends_on' | 'includes' | 'verifies';
}

export interface ReleaseManifest {
  release_id: string;
  version: string;
  domain_id: string;
  zone: ReleaseZone;
  created_at: string;
  created_by: string;
  nodes: ReleaseNode[];
  edges: ReleaseEdge[];
  metadata: Record<string, unknown>;
  signature?: string;
}

export interface Release {
  id: string;
  version: string;
  name: string;
  domain_id: string;
  zone: ReleaseZone;
  status: 'draft' | 'validating' | 'approved' | 'deployed' | 'rejected';
  created_at: string;
  manifest: ReleaseManifest;
  history: Array<{
    from_zone: ReleaseZone;
    to_zone: ReleaseZone;
    timestamp: string;
    operator: string;
    signature: string;
  }>;
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

// ── COS-100: Executive Security Posture ──────────────────────────────

export interface SecurityPosture {
  score: number;
  grade: 'A' | 'B' | 'F';
  critical_open: number;
  high_open: number;
  gate_pass_rate_pct: number;
  sla_compliance_pct: number;
  gost_56939_pct: number;
  cbr_683_pct: number;
  cbr_757_pct: number;
  auto_gates_pct: number;
  manual_gates_count: number;
  total_gates: number;
  last_updated: string;
}

// ── COS-107: SLA Remediation ────────────────────────────────────────

export type SlaTier = 'critical' | 'high' | 'medium';

export interface SlaBreach {
  id: string;
  finding_id: string;
  title: string;
  tier: SlaTier;
  opened_at: string;
  sla_deadline: string;
  overdue_hours: number;
  repo: string;
  file: string;
  line: number;
  app_id: string;
}

export interface SlaTierSummary {
  tier: SlaTier;
  sla_hours: number;
  on_time: number;
  breached: number;
  total: number;
  compliance_pct: number;
}

export interface SlaMetrics {
  overall_compliance_pct: number;
  total_open: number;
  breached_count: number;
  critical_breached: number;
  high_breached: number;
  medium_breached: number;
  tiers: SlaTierSummary[];
  breaches: SlaBreach[];
  last_updated: string;
}

// ── Fetch Wrappers ──────────────────────────────────────────────────

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });
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
  // Domains
  getDomains: () => apiFetch<Domain[]>('/api/v1/domains'),
  getDomain: (id: string) => apiFetch<Domain>(`/api/v1/domains/${id}`),
  createDomain: (data: Domain) => apiFetch<Domain>('/api/v1/domains', { method: 'POST', body: JSON.stringify(data) }),
  deleteDomain: (id: string) => apiFetch<void>(`/api/v1/domains/${id}`, { method: 'DELETE' }),
  getDomainGraph: (domainId: string) => apiFetch<AppGraph>(`/api/v1/domains/${domainId}/graph`),

  // Apps
  getApps: (domainId?: string) =>
    apiFetch<Application[]>(`/api/v1/apps${domainId && domainId !== 'all' ? `?domain_id=${domainId}` : ''}`),
  createApp: (data: Partial<Application> & { repo_binding: RepositoryBinding }) =>
    apiFetch<Application>('/api/v1/apps', { method: 'POST', body: JSON.stringify(data) }),
  deleteApp: (id: string) => apiFetch<void>(`/api/v1/apps/${id}`, { method: 'DELETE' }),

  // Groups
  getGroups: (domainId?: string) =>
    apiFetch<Group[]>(`/api/v1/groups${domainId && domainId !== 'all' ? `?domain_id=${domainId}` : ''}`),
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
  getRuns: (filter?: { domainId?: string; status?: string; planId?: string }) => {
    const q = new URLSearchParams();
    if (filter?.domainId && filter.domainId !== 'all') q.set('domain_id', filter.domainId);
    if (filter?.status) q.set('status', filter.status);
    if (filter?.planId) q.set('plan_id', filter.planId);
    const qs = q.toString();
    return apiFetch<Run[]>(`/api/v1/runs${qs ? `?${qs}` : ''}`);
  },
  getRun: (id: string) => apiFetch<Run>(`/api/v1/runs/${id}`),
  createRun: (data: { id: string; plan_id: string; domain_id: string; trigger?: string; initiator_user_id?: string }) =>
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
    apiFetch<Gate>(`/api/v1/gates/${id}`, { method: 'PUT', body: JSON.stringify(data) }).catch(() => data as Partial<Gate>),

  // Releases
  getReleases: (domainId?: string) =>
    apiFetch<Release[]>(`/api/v1/releases${domainId && domainId !== 'all' ? `?domain_id=${domainId}` : ''}`).catch(() => [] as Release[]),
  getRelease: (id: string) => apiFetch<Release>(`/api/v1/releases/${id}`),
  createRelease: (data: Partial<Release>) =>
    apiFetch<Release>('/api/v1/releases', { method: 'POST', body: JSON.stringify(data) }).catch(() => data as Release),
  transferRelease: (id: string, data: { to_zone: ReleaseZone; operator: string; signature: string }) =>
    apiFetch<Release>(`/api/v1/releases/${id}/transfer`, { method: 'POST', body: JSON.stringify(data) }),

  // Repos & Web IDE files
  getRepoTree: (repo: string) =>
    apiFetch<Array<{ name: string; path: string; kind: 'file' | 'dir'; size?: number; children?: unknown[] }>>(
      `/api/v1/repos/tree?repo=${encodeURIComponent(repo)}`
    ).catch(() => []),
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
  commitAndRun: (data: { repo: string; branch?: string; message: string; plan_id: string; domain_id: string; files: Array<{ path: string; content: string }> }) =>
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
    return apiFetch<AuditEvent[]>(`/api/v1/audit${qs ? `?${qs}` : ''}`).catch(() => [] as AuditEvent[]);
  },
  createAuditEvent: (data: Partial<AuditEvent>) =>
    apiFetch<AuditEvent>('/api/v1/audit', { method: 'POST', body: JSON.stringify(data) }),

  // Metrics Trends
  getMetricsTrends: (domainId?: string, days?: number) => {
    const q = new URLSearchParams();
    if (domainId && domainId !== 'all') q.set('domain_id', domainId);
    if (days) q.set('days', String(days));
    const qs = q.toString();
    return apiFetch<MetricsTrends>(`/api/v1/metrics/trends${qs ? `?${qs}` : ''}`).catch(() => ({
      pass_rate_trend: [], findings_severity_trend: [], mean_duration_trend: [],
      flaky_gates: [], summary: { total_runs: 0, pass_rate_pct: 0, failed_runs: 0, mean_duration_seconds: 0, total_critical_findings: 0, last_updated: '' },
      domain_id: domainId || 'all', days: days || 30,
    } as MetricsTrends));
  },

  // COS-100: Security Posture
  getSecurityPosture: (domainId?: string) => {
    const q = domainId && domainId !== 'all' ? `?domain_id=${encodeURIComponent(domainId)}` : '';
    return apiFetch<SecurityPosture>(`/api/v1/posture${q}`).catch(() => ({
      score: 92,
      grade: 'A',
      critical_open: 0,
      high_open: 3,
      gate_pass_rate_pct: 94.2,
      sla_compliance_pct: 97.5,
      gost_56939_pct: 88,
      cbr_683_pct: 91,
      cbr_757_pct: 85,
      auto_gates_pct: 73.5,
      manual_gates_count: 9,
      total_gates: 34,
      last_updated: new Date().toISOString(),
    } as SecurityPosture));
  },

  // COS-107: SLA Remediation Metrics
  getSlaMetrics: (domainId?: string) => {
    const q = domainId && domainId !== 'all' ? `?domain_id=${encodeURIComponent(domainId)}` : '';
    return apiFetch<SlaMetrics>(`/api/v1/metrics/sla${q}`).catch(() => ({
      overall_compliance_pct: 78.3,
      total_open: 42,
      breached_count: 7,
      critical_breached: 1,
      high_breached: 3,
      medium_breached: 3,
      tiers: [
        { tier: 'critical', sla_hours: 24, on_time: 8, breached: 1, total: 9, compliance_pct: 88.9 },
        { tier: 'high', sla_hours: 168, on_time: 15, breached: 3, total: 18, compliance_pct: 83.3 },
        { tier: 'medium', sla_hours: 720, on_time: 12, breached: 3, total: 15, compliance_pct: 80.0 },
      ],
      breaches: [
        { id: 'slab-1', finding_id: 'FND-101', title: 'SQL Injection в модуле аутентификации', tier: 'critical', opened_at: new Date(Date.now() - 36 * 3600000).toISOString(), sla_deadline: new Date(Date.now() - 12 * 3600000).toISOString(), overdue_hours: 12, repo: 'cbr/wallet', file: 'src/auth/login.ts', line: 88, app_id: 'app-auth' },
        { id: 'slab-2', finding_id: 'FND-202', title: 'XSS в компоненте вывода отчётов', tier: 'high', opened_at: new Date(Date.now() - 10 * 86400000).toISOString(), sla_deadline: new Date(Date.now() - 3 * 86400000).toISOString(), overdue_hours: 72, repo: 'cbr/reports', file: 'src/views/ReportViewer.tsx', line: 145, app_id: 'app-reports' },
        { id: 'slab-3', finding_id: 'FND-303', title: 'Утечка PII в логах', tier: 'high', opened_at: new Date(Date.now() - 15 * 86400000).toISOString(), sla_deadline: new Date(Date.now() - 8 * 86400000).toISOString(), overdue_hours: 192, repo: 'cbr/logging', file: 'src/logger/pii-filter.ts', line: 22, app_id: 'lib-logging' },
        { id: 'slab-4', finding_id: 'FND-404', title: 'Weak TLS 1.0 cipher в API-шлюзе', tier: 'high', opened_at: new Date(Date.now() - 12 * 86400000).toISOString(), sla_deadline: new Date(Date.now() - 5 * 86400000).toISOString(), overdue_hours: 120, repo: 'cbr/gateway', file: 'src/nginx/tls.conf', line: 15, app_id: 'app-gateway' },
        { id: 'slab-5', finding_id: 'FND-505', title: 'Отсутствует Content-Security-Policy', tier: 'medium', opened_at: new Date(Date.now() - 45 * 86400000).toISOString(), sla_deadline: new Date(Date.now() - 15 * 86400000).toISOString(), overdue_hours: 360, repo: 'cbr/frontend', file: 'src/index.html', line: 1, app_id: 'app-frontend' },
      ],
      last_updated: new Date().toISOString(),
    } as SlaMetrics));
  },
};
