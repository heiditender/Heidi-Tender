import type { JobStatus, JobStepRow, RulePayload } from "@/lib/api";

export type JobFlowState =
  | "idle"
  | "creating"
  | "created"
  | "uploading"
  | "ready"
  | "starting"
  | "running"
  | "succeeded"
  | "failed";

export type StepPhase = "pending" | "running" | "succeeded" | "failed";

export interface StepProgressState {
  stepName: string;
  displayName: string;
  phase: StepPhase;
  statusText: string;
  updatedAt: string | null;
  durationMs: number | null;
  summary: string;
  errorMessage: string | null;
  payload: Record<string, unknown> | null;
}

export interface JobEventItem {
  id: string;
  kind: string;
  stepName?: string;
  message: string;
  createdAt: string;
  rawPayload?: Record<string, unknown> | null;
}

export interface RuleValidationIssue {
  row: number;
  field: "field" | "operator" | "operator_confidence" | "hardness_confidence" | "rationale" | "row";
  message: string;
}

export interface RuleDraftValidationResult {
  valid: boolean;
  errors: RuleValidationIssue[];
  warnings: RuleValidationIssue[];
}

export interface RuleDiffSummary {
  added: number;
  removed: number;
  changed: number;
  unchanged: number;
}

export const ALLOWED_RULE_OPERATORS = ["eq", "gte", "lte", "gt", "lt", "between", "in", "contains"];

const STEP_LABELS: Record<string, string> = {
  schema_snapshot: "Schema Snapshot",
  step1_kb_bootstrap: "Step 1 Knowledge Base Bootstrap",
  step2_extract_requirements: "Step 2 Requirement Extraction",
  step3_external_field_rules: "Step 3 Field Rules",
  step4_merge_requirements_hardness: "Step 4 Constraint Merge",
  step5_build_sql: "Step 5 SQL Generation",
  step6_execute_sql: "Step 6 SQL Execution",
  step7_rank_candidates: "Step 7 Candidate Ranking"
};

function asRecord(input: unknown): Record<string, unknown> | null {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return null;
  }
  return input as Record<string, unknown>;
}

function asArray(input: unknown): unknown[] {
  return Array.isArray(input) ? input : [];
}

function getNumber(input: unknown): number | null {
  if (typeof input !== "number" || Number.isNaN(input)) {
    return null;
  }
  return input;
}

function getString(input: unknown): string | null {
  if (typeof input !== "string") {
    return null;
  }
  const text = input.trim();
  return text.length > 0 ? text : null;
}

export function formatDateTime(input: string | null | undefined): string {
  if (!input) {
    return "-";
  }
  const timestamp = Date.parse(input);
  if (Number.isNaN(timestamp)) {
    return input;
  }
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "short",
    timeStyle: "medium",
    hour12: false
  }).format(new Date(timestamp));
}

export function formatDuration(ms: number | null): string {
  if (ms == null || Number.isNaN(ms)) {
    return "-";
  }
  if (ms < 1000) {
    return `${ms}ms`;
  }
  if (ms < 60000) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  const minutes = Math.floor(ms / 60000);
  const seconds = ((ms % 60000) / 1000).toFixed(0);
  return `${minutes}m ${seconds}s`;
}

export function toGuidedError(error: unknown, nextStep: string): string {
  const reason = error instanceof Error ? error.message : String(error);
  return `Cause: ${reason}. Next step: ${nextStep}`;
}

export function mapJobStatusToFlow(status: JobStatus | null | undefined): JobFlowState {
  switch (status) {
    case "created":
      return "created";
    case "uploading":
      return "uploading";
    case "ready":
      return "ready";
    case "running":
      return "running";
    case "succeeded":
      return "succeeded";
    case "failed":
      return "failed";
    default:
      return "idle";
  }
}

export function stepDisplayName(stepName: string): string {
  return STEP_LABELS[stepName] ?? stepName;
}

function normalizeStepPhase(status: string | null | undefined): StepPhase {
  const key = (status ?? "").toLowerCase();
  if (["ok", "success", "succeeded", "completed", "done"].includes(key)) {
    return "succeeded";
  }
  if (["running", "processing", "in_progress", "queued", "active"].includes(key)) {
    return "running";
  }
  if (["error", "failed", "fail"].includes(key)) {
    return "failed";
  }
  return "pending";
}

function extractDurationMs(payload: Record<string, unknown> | null): number | null {
  if (!payload) {
    return null;
  }

  const direct = getNumber(payload.elapsed_ms);
  if (direct != null) {
    return direct;
  }

  const data = asRecord(payload.data);
  if (!data) {
    return null;
  }

  const dataElapsed = getNumber(data.elapsed_ms);
  if (dataElapsed != null) {
    return dataElapsed;
  }

  const results = asArray(data.results);
  const summed = results.reduce<number>((sum, row) => {
    const info = asRecord(row);
    const value = info ? getNumber(info.elapsed_ms) : null;
    return sum + (value ?? 0);
  }, 0);
  return summed > 0 ? summed : null;
}

function extractErrorMessage(payload: Record<string, unknown> | null): string | null {
  if (!payload) {
    return null;
  }

  const directError = getString(payload.error) ?? getString(payload.message);
  if (directError) {
    return directError;
  }

  const errors = asArray(payload.errors);
  if (errors.length > 0) {
    const first = asRecord(errors[0]);
    if (first) {
      return getString(first.message) ?? getString(first.code);
    }
  }

  return null;
}

function summarizeStep(stepName: string, payload: Record<string, unknown> | null): string {
  if (!payload) {
    return "Waiting to run";
  }

  const errorMessage = extractErrorMessage(payload);
  if (errorMessage) {
    return errorMessage;
  }

  const data = asRecord(payload.data);
  if (!data) {
    return "Updated";
  }

  if (stepName === "step1_kb_bootstrap") {
    const sourceCount = getNumber(data.source_file_count);
    const store = asRecord(data.vector_store);
    const storeStatus = store ? getString(store.status) : null;
    if (sourceCount != null) {
      return `Knowledge base files: ${sourceCount}; vector store status: ${storeStatus ?? "unknown"}`;
    }
  }

  if (stepName === "step2_extract_requirements") {
    const items = asArray(data.tender_products);
    if (items.length > 0) {
      return `Extracted ${items.length} tender items`;
    }
    const merged = asArray(data.requirements);
    if (merged.length > 0) {
      return `Extracted ${merged.length} requirements`;
    }
  }

  if (stepName === "step3_external_field_rules") {
    const rules = asArray(data.field_rules);
    if (rules.length > 0) {
      return `Applied ${rules.length} field rules`;
    }
  }

  if (stepName === "step4_merge_requirements_hardness") {
    const merged = asArray(data.merged_requirements);
    if (merged.length > 0) {
      return `Merged ${merged.length} constraints`;
    }
  }

  if (stepName === "step5_build_sql") {
    const queries = asArray(data.queries);
    if (queries.length > 0) {
      return `Generated ${queries.length} SQL queries`;
    }
  }

  if (stepName === "step6_execute_sql") {
    const results = asArray(data.results);
    const totalRows = results.reduce<number>((sum, row) => {
      const record = asRecord(row);
      const count = record ? getNumber(record.row_count) : null;
      return sum + (count ?? 0);
    }, 0);
    if (results.length > 0) {
      return `Executed ${results.length} queries and returned ${totalRows} rows`;
    }
  }

  if (stepName === "step7_rank_candidates") {
    const matchResults = asArray(data.match_results);
    if (matchResults.length > 0) {
      return `Ranked candidates for ${matchResults.length} tender items`;
    }
  }

  const keys = Object.keys(data);
  return keys.length > 0 ? `Updated: ${keys.slice(0, 3).join(" / ")}` : "Updated";
}

export function buildStepProgressStates(stepOrder: string[], stepMap: Record<string, JobStepRow>): StepProgressState[] {
  return stepOrder.map((stepName) => {
    const row = stepMap[stepName];
    const payload = row?.payload ?? null;
    const phase = normalizeStepPhase(row?.step_status);
    const statusText = row?.step_status ?? "pending";

    return {
      stepName,
      displayName: stepDisplayName(stepName),
      phase,
      statusText,
      updatedAt: row?.updated_at ?? null,
      durationMs: extractDurationMs(payload),
      summary: summarizeStep(stepName, payload),
      errorMessage: extractErrorMessage(payload),
      payload
    };
  });
}

export function calculateProgressPercent(steps: StepProgressState[]): number {
  if (steps.length === 0) {
    return 0;
  }
  const succeededCount = steps.filter((row) => row.phase === "succeeded").length;
  return Math.floor((succeededCount / steps.length) * 100);
}

export function validateRuleDraft(payload: RulePayload): RuleDraftValidationResult {
  const errors: RuleValidationIssue[] = [];
  const warnings: RuleValidationIssue[] = [];
  const duplicateMap = new Map<string, number>();

  payload.field_rules.forEach((row, index) => {
    const normalizedField = row.field.trim();
    const key = normalizedField.toLowerCase();

    if (!normalizedField) {
      errors.push({ row: index, field: "field", message: "Field name cannot be empty" });
    }

    if (normalizedField && !normalizedField.startsWith("vw_bid_")) {
      warnings.push({ row: index, field: "field", message: "Fields should usually use the vw_bid_* prefix" });
    }

    if (!ALLOWED_RULE_OPERATORS.includes(row.operator)) {
      errors.push({ row: index, field: "operator", message: `Unsupported operator: ${row.operator}` });
    }

    if (typeof row.operator_confidence !== "number" || row.operator_confidence < 0 || row.operator_confidence > 1) {
      errors.push({ row: index, field: "operator_confidence", message: "Operator confidence must be between 0 and 1" });
    }

    if (typeof row.hardness_confidence !== "number" || row.hardness_confidence < 0 || row.hardness_confidence > 1) {
      errors.push({ row: index, field: "hardness_confidence", message: "Hardness confidence must be between 0 and 1" });
    }

    if (!row.rationale || row.rationale.trim().length === 0) {
      warnings.push({ row: index, field: "rationale", message: "Add a rationale to make later review easier" });
    }

    if (key) {
      const previous = duplicateMap.get(key);
      if (previous != null) {
        errors.push({ row: index, field: "field", message: `Duplicate field; already used on row ${previous + 1}` });
      } else {
        duplicateMap.set(key, index);
      }
    }
  });

  if (payload.field_rules.length === 0) {
    warnings.push({ row: -1, field: "row", message: "This draft is empty. Add at least one rule before publishing" });
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings
  };
}

function stableRowSignature(row: RulePayload["field_rules"][number]): string {
  return JSON.stringify({
    field: row.field.trim(),
    operator: row.operator,
    is_hard: row.is_hard,
    operator_confidence: row.operator_confidence,
    hardness_confidence: row.hardness_confidence,
    rationale: (row.rationale ?? "").trim()
  });
}

export function buildRuleDiffSummary(current: RulePayload | null, candidate: RulePayload): RuleDiffSummary {
  const currentMap = new Map<string, string>();
  const candidateMap = new Map<string, string>();

  (current?.field_rules ?? []).forEach((row) => {
    currentMap.set(row.field.trim().toLowerCase(), stableRowSignature(row));
  });

  candidate.field_rules.forEach((row) => {
    candidateMap.set(row.field.trim().toLowerCase(), stableRowSignature(row));
  });

  let added = 0;
  let removed = 0;
  let changed = 0;
  let unchanged = 0;

  for (const [field, signature] of candidateMap) {
    if (!currentMap.has(field)) {
      added += 1;
      continue;
    }
    if (currentMap.get(field) === signature) {
      unchanged += 1;
    } else {
      changed += 1;
    }
  }

  for (const field of currentMap.keys()) {
    if (!candidateMap.has(field)) {
      removed += 1;
    }
  }

  return { added, removed, changed, unchanged };
}
