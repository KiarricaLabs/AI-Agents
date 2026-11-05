// T2-C-6 — Coordination & Deliverable Review typed API layer.
//
// Thin, typed wrappers around the backend T2-C-3 (team goals + coordination
// plans), T2-C-4 (execution / step review), and T2-C-5 (deliverable version)
// endpoints. It does NOT add new backend capabilities, execute anything
// autonomously, or bypass server-side authorization.
//
// Every execution step remains human-initiated: this module exposes one
// function per discrete human action (execute the next step, review a step,
// aggregate, review the deliverable). Nothing here auto-advances a step after
// an accepted output.

export const API = (import.meta.env?.VITE_API_BASE as string | undefined) || "http://127.0.0.1:8001";

// ---------------------------------------------------------------------------
// Types (mirroring the backend response shapes)
// ---------------------------------------------------------------------------

export interface TeamGoalSummary {
  id: string;
  title: string;
  coordinator_agent: string;
  status: string;
  expected_deliverable?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface TeamGoalStep {
  seq: number;
  agent_id: string;
  responsibility: string | null;
  depends_on_seq: number | null;
  capability_ok: boolean;
  delegation_ok: boolean;
  valid: boolean;
  error: string | null;
  status: string;
  effective_permissions?: string[];
}

export interface CoordinationPlan {
  plan_id: string;
  team_goal_id: string;
  goal_id?: string | null;
  coordinator: string;
  expected_deliverable?: string | null;
  status: string;
  steps: TeamGoalStep[];
  reused?: boolean;
}

export interface ReviewPlan {
  team_goal_id: string;
  coordinator: string;
  goal_id?: string | null;
  expected_deliverable?: string | null;
  steps: TeamGoalStep[];
  plan_valid: boolean;
  errors: string[];
  warnings: string[];
  transient: boolean;
}

export interface ExecutionSummary {
  execution_id: string;
  plan_id: string;
  team_goal_id: string;
  status: string;
  initiated_by?: string | null;
  initiated_at?: string | null;
  reused?: boolean;
  steps?: Array<{
    seq: number;
    status: string;
    error?: string | null;
    has_evidence?: boolean;
  }>;
  deliverable?: any | null;
}

export interface StepReviewResult {
  execution_id: string;
  step: number;
  decision: string;
  run_status: string;
  note?: string | null;
}

export interface DeliverableReviewResult {
  execution_id: string;
  decision: string;
  run_status: string;
  version_id?: string;
  version?: number;
  approval?: any[];
  steps?: number[];
}

export interface DeliverableVersion {
  version_id: string;
  deliverable_id: string;
  execution_id: string;
  version: number;
  content: any;
  status: string;
  review_note?: string | null;
  revision_of?: string | null;
  created_at: string;
  updated_at: string;
  approvals?: any[];
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

class ApiError extends Error {
  status: number;
  detail?: unknown;
  constructor(status: number, detail?: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  if (!r.ok) {
    const detail = (body as any)?.detail ?? null;
    throw new ApiError(r.status, detail);
  }
  return body as T;
}

function post<T>(url: string, payload?: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// T2-C-3: Team Goals + coordination plans
// ---------------------------------------------------------------------------

export function listTeamGoals(): Promise<{ items: TeamGoalSummary[] }> {
  return request<{ items: TeamGoalSummary[] }>(`${API}/team/goals`);
}

export function reviewCoordinationPlan(teamGoalId: string): Promise<ReviewPlan> {
  return request<ReviewPlan>(`${API}/team/goals/${encodeURIComponent(teamGoalId)}/coordination-plan`);
}

export function authorizeCoordinationPlan(teamGoalId: string): Promise<CoordinationPlan> {
  return post<CoordinationPlan>(`${API}/team/goals/${encodeURIComponent(teamGoalId)}/coordination-plan/authorize`);
}

// ---------------------------------------------------------------------------
// T2-C-4: execution (human-initiated, one eligible step at a time)
// ---------------------------------------------------------------------------

export function initiateExecution(planId: string): Promise<ExecutionSummary> {
  return post<ExecutionSummary>(`${API}/team/goals/plans/${encodeURIComponent(planId)}/execution/initiate`);
}

export function executeNextStep(planId: string, executionId: string): Promise<any> {
  return post<any>(`${API}/team/goals/plans/${encodeURIComponent(planId)}/execution/${encodeURIComponent(executionId)}/step/execute`);
}

export function reviewStep(planId: string, executionId: string, seq: number,
                           decision: string, note?: string): Promise<StepReviewResult> {
  return post<StepReviewResult>(
    `${API}/team/goals/plans/${encodeURIComponent(planId)}/execution/${encodeURIComponent(executionId)}/step/${seq}/review`,
    { decision, note: note ?? undefined });
}

export function aggregateDeliverable(planId: string, executionId: string): Promise<any> {
  return post<any>(`${API}/team/goals/plans/${encodeURIComponent(planId)}/execution/${encodeURIComponent(executionId)}/aggregate`);
}

export function reviewDeliverable(planId: string, executionId: string,
                                  decision: string, note?: string,
                                  reworkSteps?: number[]): Promise<DeliverableReviewResult> {
  return post<DeliverableReviewResult>(
    `${API}/team/goals/plans/${encodeURIComponent(planId)}/execution/${encodeURIComponent(executionId)}/deliverable/review`,
    { decision, note: note ?? undefined, rework_steps: reworkSteps ?? undefined });
}

export function getExecutionStatus(planId: string, executionId: string): Promise<ExecutionSummary> {
  return request<ExecutionSummary>(`${API}/team/goals/plans/${encodeURIComponent(planId)}/execution/${encodeURIComponent(executionId)}`);
}

// ---------------------------------------------------------------------------
// T2-C-5: deliverable version history
// ---------------------------------------------------------------------------

export function listDeliverableVersions(planId: string, executionId: string): Promise<{ execution_id: string; versions: DeliverableVersion[] }> {
  return request<{ execution_id: string; versions: DeliverableVersion[] }>(
    `${API}/team/goals/plans/${encodeURIComponent(planId)}/execution/${encodeURIComponent(executionId)}/deliverable/versions`);
}

export function getDeliverableVersion(planId: string, executionId: string,
                                      versionId: string): Promise<DeliverableVersion> {
  return request<DeliverableVersion>(
    `${API}/team/goals/plans/${encodeURIComponent(planId)}/execution/${encodeURIComponent(executionId)}/deliverable/versions/${encodeURIComponent(versionId)}`);
}

// ---------------------------------------------------------------------------
// T2-C-8: TeamGoal authoring (propose + project-goal picker)
// ---------------------------------------------------------------------------

export interface ProjectGoal {
  id: string;
  title: string;
  priority?: number;
  project_id?: string;
  status?: string;
}

export interface ProposeStepInput {
  seq: number;
  agent_id: string;
  responsibility?: string | null;
  depends_on_seq?: number | null;
}

export interface ProposeTeamGoalInput {
  title: string;
  coordinator_agent: string;
  goal_id?: string | null;
  thread_id?: string | null;
  summary?: string | null;
  expected_deliverable?: string | null;
  steps?: ProposeStepInput[];
  idempotency_key?: string;
}

export interface ProposeTeamGoalResult {
  team_goal_id: string;
  status: string;
  reused?: boolean;
}

// Owner-scoped project goals used to power the coordination authoring picker.
// Reuses the existing GET /workspaces/goals endpoint (no new backend surface).
export function listProjectGoals(): Promise<{ items: ProjectGoal[] }> {
  return request<{ items: ProjectGoal[] }>(`${API}/workspaces/goals`);
}

// Human-only TeamGoal proposal (intent only): creates a 'proposed' goal and
// never approves, authorizes a plan, or starts execution.
export function proposeTeamGoal(input: ProposeTeamGoalInput): Promise<ProposeTeamGoalResult> {
  return post<ProposeTeamGoalResult>(`${API}/team/goals`, input);
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

// Known agent slugs usable for team-goal coordinator/step selection. This is a
// UI picker list only; server-side validation remains authoritative.
export const AGENT_SLUGS = [
  "workspace_architect",
  "strategist",
  "tutor",
  "executive_assistant",
  "communications",
  "soundboard",
];

const STEP_STATUS_LABEL: Record<string, string> = {
  pending: "Planned",
  in_progress: "In progress",
  awaiting_review: "Ready for review",
  accepted: "Accepted",
  revision_requested: "Revision requested",
  rejected: "Rejected",
  failed: "Failed",
};

const EXEC_STATUS_LABEL: Record<string, string> = {
  running: "Running",
  ready_for_review: "Ready for review",
  completed: "Completed",
  rejected: "Rejected",
  revision_requested: "Revision requested",
};

const VERSION_STATUS_LABEL: Record<string, string> = {
  pending: "Pending review",
  approved: "Approved",
  rejected: "Rejected",
  revision_requested: "Revision requested",
};

export function stepStatusLabel(s: string): string {
  return STEP_STATUS_LABEL[s] || s.replace(/_/g, " ");
}

export function execStatusLabel(s: string): string {
  return EXEC_STATUS_LABEL[s] || s.replace(/_/g, " ");
}

export function versionStatusLabel(s: string): string {
  return VERSION_STATUS_LABEL[s] || s.replace(/_/g, " ");
}

export function humanizeAgent(slug: string | undefined | null): string {
  if (!slug) return "Unknown agent";
  return slug.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
