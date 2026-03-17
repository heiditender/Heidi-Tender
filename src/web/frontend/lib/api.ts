export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1";

export type JobStatus = "created" | "uploading" | "ready" | "running" | "succeeded" | "failed";
export type RuleStatus = "draft" | "published" | "archived";
export type RuleSource = "manual" | "llm" | "seed";

export interface AuthUser {
  id: string;
  email: string;
  display_name?: string | null;
  avatar_url?: string | null;
}

export interface AuthSessionResponse {
  user: AuthUser;
}

export interface AuthProvidersResponse {
  google: boolean;
  microsoft: boolean;
  magic_link: boolean;
}

export interface MagicLinkRequestResponse {
  ok: boolean;
  detail: string;
}

export interface JobFileRow {
  id: string;
  relative_path: string;
  size_bytes: number;
  extension: string;
  created_at: string;
}

export interface JobStepRow {
  step_name: string;
  step_status: string;
  payload: Record<string, unknown>;
  updated_at: string;
}

export interface JobResponse {
  id: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
  runtime_dir?: string | null;
  final_output_path?: string | null;
  rule_version_id?: string | null;
  warnings?: string[];
  file_count: number;
  step_count: number;
  files: JobFileRow[];
  steps: JobStepRow[];
}

export interface PaginatedQuery {
  limit?: number;
  offset?: number;
}

export interface JobListQuery extends PaginatedQuery {
  status?: JobStatus;
  q?: string;
  updated_from?: string;
  updated_to?: string;
}

export interface RulePayload {
  field_rules: Array<{
    field: string;
    operator: string;
    is_hard: boolean;
    operator_confidence: number;
    hardness_confidence: number;
    rationale?: string | null;
  }>;
}

export interface CopilotExecutionSummary {
  step_name: string;
  request_started_at: string | null;
  request_finished_at: string | null;
  duration_ms: number | null;
  final_status: "succeeded" | "failed";
  response_received: boolean;
  fallback_used: boolean;
  failure_message: string | null;
  reasoning_summary: string | null;
  reasoning_chars: number;
  stream_event_counts: Record<string, number>;
  status_events: string[];
}

export interface CopilotLogPayload {
  prompt: string;
  model: string;
  reasoning_summary?: string | null;
  execution_summary: CopilotExecutionSummary;
}

export interface RuleVersion {
  id: string;
  version_number: number;
  status: RuleStatus;
  source: RuleSource;
  payload: RulePayload;
  validation_report: Record<string, unknown>;
  copilot_log?: CopilotLogPayload | null;
  note?: string | null;
  created_at: string;
  published_at?: string | null;
}

export interface RuleVersionListQuery extends PaginatedQuery {
  status?: RuleStatus;
  source?: RuleSource;
  q?: string;
}

export interface ModelSettingsResponse {
  current_model: "gpt-5.4" | "gpt-5-mini";
  allowed_models: Array<"gpt-5.4" | "gpt-5-mini">;
  has_api_key: boolean;
}

export interface RuleGenerateStreamEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface StatsDashboardQuery {
  days?: number;
  include_failed?: boolean;
  top_n?: number;
}

export interface StatsOverviewResponse {
  window_from: string;
  window_to: string;
  job_count: number;
  succeeded_count: number;
  failed_count: number;
  avg_job_duration_ms: number | null;
  p50_job_duration_ms: number | null;
  p90_job_duration_ms: number | null;
  avg_extracted_products: number | null;
}

export interface JobDurationStatRow {
  job_id: string;
  status: JobStatus;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  extracted_products: number | null;
}

export interface StepDurationStatRow {
  step_name: string;
  sample_count: number;
  avg_duration_ms: number | null;
  p50_duration_ms: number | null;
  p90_duration_ms: number | null;
}

export interface FieldFrequencyStatRow {
  field: string;
  count: number;
}

export interface StatsDashboardResponse {
  overview: StatsOverviewResponse;
  job_durations: JobDurationStatRow[];
  step_durations: StepDurationStatRow[];
  field_frequency: FieldFrequencyStatRow[];
}

export class UnauthorizedError extends Error {
  constructor(message = "Authentication required") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

function emitAuthRequired() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("heidi:auth-required"));
}

async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  return fetch(input, {
    credentials: "include",
    ...init,
  });
}

async function ensureOk<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const message = await response.text();
    if (response.status === 401) {
      emitAuthRequired();
      throw new UnauthorizedError(message || "Authentication required");
    }
    throw new Error(message || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function buildAuthLoginUrl(provider: "google" | "microsoft", nextPath?: string): string {
  const params = new URLSearchParams();
  if (nextPath) params.set("next_path", nextPath);
  const suffix = params.size ? `?${params.toString()}` : "";
  return `${API_BASE}/auth/login/${provider}${suffix}`;
}

export function isAbsoluteApiBase(): boolean {
  return API_BASE.startsWith("http://") || API_BASE.startsWith("https://");
}

export async function getAuthSession(): Promise<AuthSessionResponse> {
  const response = await apiFetch(`${API_BASE}/auth/session`, { cache: "no-store" });
  return ensureOk(response);
}

export async function getAuthOptions(): Promise<AuthProvidersResponse> {
  const response = await apiFetch(`${API_BASE}/auth/options`, { cache: "no-store" });
  return ensureOk(response);
}

export async function logout(): Promise<void> {
  const response = await apiFetch(`${API_BASE}/auth/logout`, { method: "POST" });
  if (!response.ok && response.status !== 401) {
    const message = await response.text();
    throw new Error(message || `HTTP ${response.status}`);
  }
}

export async function requestMagicLink(email: string, nextPath?: string): Promise<MagicLinkRequestResponse> {
  const response = await apiFetch(`${API_BASE}/auth/magic-link/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, next_path: nextPath ?? null }),
  });
  return ensureOk(response);
}

export async function createJob(): Promise<{ id: string; status: JobStatus; created_at: string }> {
  const response = await apiFetch(`${API_BASE}/jobs`, { method: "POST" });
  return ensureOk(response);
}

export async function uploadJobFile(jobId: string, file: File, relativePath: string): Promise<JobResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("relative_path", relativePath);
  const response = await apiFetch(`${API_BASE}/jobs/${jobId}/file`, { method: "POST", body: form });
  return ensureOk(response);
}

export async function uploadJobArchive(jobId: string, file: File): Promise<JobResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await apiFetch(`${API_BASE}/jobs/${jobId}/archive`, { method: "POST", body: form });
  return ensureOk(response);
}

export async function startJob(jobId: string, ruleVersionId?: string): Promise<JobResponse> {
  const response = await apiFetch(`${API_BASE}/jobs/${jobId}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rule_version_id: ruleVersionId ?? null }),
  });
  return ensureOk(response);
}

export async function getJob(jobId: string): Promise<JobResponse> {
  const response = await apiFetch(`${API_BASE}/jobs/${jobId}`, { cache: "no-store" });
  return ensureOk(response);
}

export async function listJobs(query: JobListQuery = {}): Promise<JobResponse[]> {
  const params = new URLSearchParams();
  if (typeof query.limit === "number") params.set("limit", String(query.limit));
  if (typeof query.offset === "number") params.set("offset", String(query.offset));
  if (query.status) params.set("status", query.status);
  if (query.q) params.set("q", query.q);
  if (query.updated_from) params.set("updated_from", query.updated_from);
  if (query.updated_to) params.set("updated_to", query.updated_to);
  const suffix = params.size ? `?${params.toString()}` : "";
  const response = await apiFetch(`${API_BASE}/jobs${suffix}`, { cache: "no-store" });
  return ensureOk(response);
}

export async function getJobResult(jobId: string): Promise<Record<string, unknown>> {
  const response = await apiFetch(`${API_BASE}/jobs/${jobId}/result`, { cache: "no-store" });
  return ensureOk(response);
}

export async function getRuleVersions(query: RuleVersionListQuery = {}): Promise<RuleVersion[]> {
  const params = new URLSearchParams();
  if (typeof query.limit === "number") params.set("limit", String(query.limit));
  if (typeof query.offset === "number") params.set("offset", String(query.offset));
  if (query.status) params.set("status", query.status);
  if (query.source) params.set("source", query.source);
  if (query.q) params.set("q", query.q);
  const suffix = params.size ? `?${params.toString()}` : "";
  const response = await apiFetch(`${API_BASE}/rules/versions${suffix}`, { cache: "no-store" });
  return ensureOk(response);
}

export async function getCurrentRule(): Promise<RuleVersion> {
  const response = await apiFetch(`${API_BASE}/rules/current`, { cache: "no-store" });
  return ensureOk(response);
}

export async function saveRuleDraft(
  payload: RulePayload,
  note?: string,
  source: RuleSource = "manual",
  copilotLog?: CopilotLogPayload
): Promise<RuleVersion> {
  const response = await apiFetch(`${API_BASE}/rules/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload, note, source, copilot_log: copilotLog ?? null }),
  });
  return ensureOk(response);
}

export async function generateRuleDraft(note?: string): Promise<RuleVersion> {
  const response = await apiFetch(`${API_BASE}/rules/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  return ensureOk(response);
}

export async function publishRuleVersion(versionId: string): Promise<{ id: string; status: string; published_at: string }> {
  const response = await apiFetch(`${API_BASE}/rules/${versionId}/publish`, { method: "POST" });
  return ensureOk(response);
}

export async function getModelSettings(): Promise<ModelSettingsResponse> {
  const response = await apiFetch(`${API_BASE}/settings/model`, { cache: "no-store" });
  return ensureOk(response);
}

export async function setModelSettings(model: "gpt-5.4" | "gpt-5-mini"): Promise<ModelSettingsResponse> {
  const response = await apiFetch(`${API_BASE}/settings/model`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  return ensureOk(response);
}

export async function streamRuleDraftPreview(
  prompt: string,
  onEvent: (event: RuleGenerateStreamEvent) => void
): Promise<void> {
  const response = await apiFetch(`${API_BASE}/rules/generate/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!response.ok) {
    const message = await response.text();
    if (response.status === 401) {
      emitAuthRequired();
      throw new UnauthorizedError(message || "Authentication required");
    }
    throw new Error(message || `HTTP ${response.status}`);
  }
  if (!response.body) {
    throw new Error("stream response body is missing");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";
  let dataLines: string[] = [];

  const flush = () => {
    if (dataLines.length === 0) {
      currentEvent = "message";
      return;
    }
    const dataRaw = dataLines.join("\n").trim();
    dataLines = [];
    if (!dataRaw) {
      currentEvent = "message";
      return;
    }
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(dataRaw) as Record<string, unknown>;
    } catch {
      data = { message: dataRaw };
    }
    onEvent({ event: currentEvent, data });
    currentEvent = "message";
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    while (true) {
      const index = buffer.indexOf("\n");
      if (index === -1) {
        break;
      }
      const line = buffer.slice(0, index).replace(/\r$/, "");
      buffer = buffer.slice(index + 1);
      if (!line) {
        flush();
        continue;
      }
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim() || "message";
        continue;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
  }
  if (buffer.trim()) {
    dataLines.push(buffer.trim());
  }
  flush();
}

export async function getStatsDashboard(query: StatsDashboardQuery = {}): Promise<StatsDashboardResponse> {
  const params = new URLSearchParams();
  if (typeof query.days === "number") params.set("days", String(query.days));
  if (typeof query.include_failed === "boolean") params.set("include_failed", String(query.include_failed));
  if (typeof query.top_n === "number") params.set("top_n", String(query.top_n));
  const suffix = params.size ? `?${params.toString()}` : "";
  const response = await apiFetch(`${API_BASE}/stats/dashboard${suffix}`, { cache: "no-store" });
  return ensureOk(response);
}
