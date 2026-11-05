// T2-C-6 — Coordination & Deliverable Review panel.
//
// A self-contained React component added inside the AI Team tab. It drives the
// T2-C-3/4/5 backend through the typed API layer (./coordination).
//
// Rules honored by the UI:
// - Every step is executed by an explicit human "Execute next step" click; there
//   is NO run-all, scheduler, or autonomous advance. Accepting a step's output
//   never dispatches the next step.
// - Step and deliverable reviews are discrete human actions (accept / request
//   revision / reject). Revision requires selecting specific rework steps.
// - The coordination-plan snapshot is read-only.
// - Deliverable version history is immutable and read-only.
// - The UI never overrides server-side authorization / permission ceilings.

import { useCallback, useEffect, useState } from "react";
import {
  listTeamGoals,
  listProjectGoals,
  proposeTeamGoal,
  reviewCoordinationPlan,
  authorizeCoordinationPlan,
  initiateExecution,
  executeNextStep,
  reviewStep,
  aggregateDeliverable,
  reviewDeliverable,
  getExecutionStatus,
  listDeliverableVersions,
  getDeliverableVersion,
  stepStatusLabel,
  execStatusLabel,
  versionStatusLabel,
  humanizeAgent,
  AGENT_SLUGS,
  type TeamGoalSummary,
  type TeamGoalStep,
  type CoordinationPlan,
  type ReviewPlan,
  type ExecutionSummary,
  type DeliverableVersion,
  type ProjectGoal,
  type ProposeTeamGoalInput,
} from "./coordination";

function Empty({ text }: { text: string }) {
  return <div className="empty" role="status">{text}</div>;
}

function ErrorBox({ msg }: { msg: string }) {
  return msg ? <p className="error" role="alert">{msg}</p> : null;
}

// Resolve the user-facing error message from an unknown thrown value.
function errMsg(e: unknown, fallback: string): string {
  return (e && typeof e === "object" && "message" in e && typeof (e as any).message === "string"
    ? (e as any).message
    : fallback);
}

// A draft step in the authoring form (seq is derived from array order).
interface StepDraft {
  agent_id: string;
  responsibility: string;
  depends_on_seq: number | null;
}

export function Coordination() {
  const [goals, setGoals] = useState<TeamGoalSummary[]>([]);
  const [goalsLoading, setGoalsLoading] = useState(false);
  const [goalsError, setGoalsError] = useState("");

  const [selectedGoalId, setSelectedGoalId] = useState<string | null>(null);
  const [goalLoading, setGoalLoading] = useState(false);
  const [goalError, setGoalError] = useState("");

  // Plan state
  const [plan, setPlan] = useState<CoordinationPlan | null>(null);
  const [review, setReview] = useState<ReviewPlan | null>(null);
  const [planError, setPlanError] = useState("");
  const [planBusy, setPlanBusy] = useState(false);

  // Execution state
  const [execution, setExecution] = useState<ExecutionSummary | null>(null);
  const [execBusy, setExecBusy] = useState<string | null>(null);

  // Deliverable / versions (history is immutable and read-only)
  const [versions, setVersions] = useState<DeliverableVersion[]>([]);
  const [versionDetail, setVersionDetail] = useState<DeliverableVersion | null>(null);
  const [revError, setRevError] = useState("");
  const [revBusy, setRevBusy] = useState<string | null>(null);

  // Rework selection + confirmation
  const [reworkSelected, setReworkSelected] = useState<number[]>([]);
  const [reviewMsg, setReviewMsg] = useState("");

  // TeamGoal authoring form (T2-C-8-2)
  const [showCreate, setShowCreate] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createSuccess, setCreateSuccess] = useState("");
  const [projectGoals, setProjectGoals] = useState<ProjectGoal[]>([]);
  const [goalsOptionsLoading, setGoalsOptionsLoading] = useState(false);
  const [formTitle, setFormTitle] = useState("");
  const [formSummary, setFormSummary] = useState("");
  const [formDeliverable, setFormDeliverable] = useState("");
  const [formCoordinator, setFormCoordinator] = useState("workspace_architect");
  const [formGoalId, setFormGoalId] = useState("");
  const [formSteps, setFormSteps] = useState<StepDraft[]>([
    { agent_id: "strategist", responsibility: "", depends_on_seq: null },
  ]);

  const loadGoals = useCallback(async () => {
    setGoalsLoading(true);
    setGoalsError("");
    try {
      const r = await listTeamGoals();
      setGoals(r.items || []);
    } catch (e) {
      setGoalsError(errMsg(e, "Could not load team goals."));
    } finally {
      setGoalsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGoals();
  }, [loadGoals]);

  async function openCreate() {
    setShowCreate(true);
    setCreateError("");
    setCreateSuccess("");
    setGoalsOptionsLoading(true);
    try {
      const r = await listProjectGoals();
      setProjectGoals(r.items || []);
    } catch (e) {
      setCreateError(errMsg(e, "Could not load project goals."));
    } finally {
      setGoalsOptionsLoading(false);
    }
  }

  function closeCreate() {
    setShowCreate(false);
    setCreateError("");
    setCreateSuccess("");
  }

  function addStep() {
    setFormSteps((prev) => [
      ...prev,
      { agent_id: "strategist", responsibility: "", depends_on_seq: null },
    ]);
  }

  function removeStep(i: number) {
    setFormSteps((prev) => {
      const next = prev.filter((_, idx) => idx !== i);
      // clamp dependency references that no longer point at an earlier step
      return next.map((s, idx) => ({
        ...s,
        depends_on_seq: s.depends_on_seq != null && s.depends_on_seq <= idx ? s.depends_on_seq : null,
      }));
    });
  }

  function updateStep(i: number, patch: Partial<StepDraft>) {
    setFormSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }

  function validateForm(): string | null {
    if (!formTitle.trim()) return "A title is required.";
    if (!formCoordinator) return "Select a coordinator.";
    if (!formGoalId) return "Select a project goal to coordinate.";
    if (formSteps.length === 0) return "Add at least one step.";
    for (let i = 0; i < formSteps.length; i++) {
      const s = formSteps[i];
      if (!s.agent_id) return `Step ${i + 1}: choose an agent.`;
      if (s.depends_on_seq != null && (s.depends_on_seq < 1 || s.depends_on_seq > i)) {
        return `Step ${i + 1}: dependency must reference an earlier step.`;
      }
    }
    return null;
  }

  async function doPropose() {
    const err = validateForm();
    if (err) { setCreateError(err); return; }
    setCreateBusy(true);
    setCreateError("");
    setCreateSuccess("");
    try {
      const payload: ProposeTeamGoalInput = {
        title: formTitle.trim(),
        coordinator_agent: formCoordinator,
        goal_id: formGoalId,
        summary: formSummary.trim() || undefined,
        expected_deliverable: formDeliverable.trim() || undefined,
        steps: formSteps.map((s, idx) => ({
          seq: idx + 1,
          agent_id: s.agent_id,
          responsibility: s.responsibility.trim() || undefined,
          depends_on_seq: s.depends_on_seq ?? undefined,
        })),
      };
      const r = await proposeTeamGoal(payload);
      setCreateSuccess(
        `Team goal \u201c${formTitle.trim()}\u201d proposed (${r.status}). Approval is a separate human step.`);
      await loadGoals();
      setShowCreate(false);
      setFormTitle("");
      setFormSummary("");
      setFormDeliverable("");
      setFormGoalId("");
      setFormSteps([{ agent_id: "strategist", responsibility: "", depends_on_seq: null }]);
    } catch (e) {
      setCreateError(errMsg(e, "Could not propose the team goal."));
    } finally {
      setCreateBusy(false);
    }
  }

  async function openGoal(goalId: string) {
    setSelectedGoalId(goalId);
    setGoalLoading(true);
    setGoalError("");
    setPlan(null);
    setReview(null);
    setExecution(null);
    setVersions([]);
    setVersionDetail(null);
    setReworkSelected([]);
    setReviewMsg("");
    try {
      const r = await reviewCoordinationPlan(goalId);
      setReview(r);
    } catch (e) {
      setReview(null);
      const status = (e && typeof e === "object" && "status" in e) ? (e as any).status : null;
      // 422 = expected "not yet eligible for a plan" — the preview just stays
      // hidden. Anything else (network, 5xx, 404) is a real failure to surface.
      if (status !== 422) {
        setGoalError(errMsg(e, "Could not load this goal's plan."));
      }
    } finally {
      setGoalLoading(false);
    }
  }

  async function doAuthorize() {
    if (!selectedGoalId) return;
    setPlanBusy(true);
    setPlanError("");
    setRevError("");
    try {
      const p = await authorizeCoordinationPlan(selectedGoalId);
      setPlan(p);
      setReview(null);
    } catch (e) {
      setPlanError(errMsg(e, "Could not authorize the plan."));
    } finally {
      setPlanBusy(false);
    }
  }

  async function loadExecutionStatus(planId: string, executionId: string) {
    try {
      const s = await getExecutionStatus(planId, executionId);
      setExecution(s);
      return s;
    } catch (e) {
      setRevError(errMsg(e, "Could not load execution status."));
      return null;
    }
  }

  async function doStartExecution() {
    if (!plan) return;
    setExecBusy("start");
    setRevError("");
    try {
      const e = await initiateExecution(plan.plan_id);
      setExecution(e);
      // Load the run status (incl. step states) so the run is actionable; the
      // initiate response alone carries no step list, so skipping this would
      // leave the "Execute next eligible step" button permanently disabled.
      await loadExecutionStatus(plan.plan_id, e.execution_id);
      await loadVersions(plan.plan_id, e.execution_id);
    } catch (e) {
      setRevError(errMsg(e, "Could not start execution."));
    } finally {
      setExecBusy(null);
    }
  }

  async function doExecuteNext() {
    if (!plan || !execution) return;
    setExecBusy("execute");
    setRevError("");
    setReviewMsg("");
    try {
      await executeNextStep(plan.plan_id, execution.execution_id);
      await loadExecutionStatus(plan.plan_id, execution.execution_id);
    } catch (e) {
      setRevError(errMsg(e, "Could not execute the next step."));
    } finally {
      setExecBusy(null);
    }
  }

  async function doReviewStep(seq: number, decision: string) {
    if (!plan || !execution) return;
    setRevBusy(`step-${seq}-${decision}`);
    setRevError("");
    try {
      await reviewStep(plan.plan_id, execution.execution_id, seq, decision);
      await loadExecutionStatus(plan.plan_id, execution.execution_id);
      setReviewMsg(`Step ${seq} ${decision.replace(/_/g, " ")}.`);
    } catch (e) {
      setRevError(errMsg(e, "Could not review the step."));
    } finally {
      setRevBusy(null);
    }
  }

  async function doAggregate() {
    if (!plan || !execution) return;
    setRevBusy("aggregate");
    setRevError("");
    try {
      await aggregateDeliverable(plan.plan_id, execution.execution_id);
      await loadExecutionStatus(plan.plan_id, execution.execution_id);
      await loadVersions(plan.plan_id, execution.execution_id);
    } catch (e) {
      setRevError(errMsg(e, "Could not aggregate the deliverable."));
    } finally {
      setRevBusy(null);
    }
  }

  async function loadVersions(planId: string, executionId: string) {
    try {
      const r = await listDeliverableVersions(planId, executionId);
      setVersions(r.versions || []);
    } catch {
      setVersions([]);
    }
  }

  async function doReviewDeliverable(decision: string) {
    if (!plan || !execution) return;
    let rework: number[] | undefined;
    if (decision === "revision_requested") {
      if (reworkSelected.length === 0) {
        setRevError("Select at least one step to rework.");
        return;
      }
      rework = [...reworkSelected];
    }
    setRevBusy(`delivery-${decision}`);
    setRevError("");
    setReviewMsg("");
    try {
      const r = await reviewDeliverable(plan.plan_id, execution.execution_id, decision,
                                        undefined, rework);
      setExecution((prev) => prev ? { ...prev, status: r.run_status } : prev);
      if (decision === "revision_requested") {
        if (r.steps?.length) setReviewMsg(`Rework required on: ${r.steps.join(", ")}. Select and re-execute each step.`);
        else setReviewMsg("Revision requested. Re-execute the affected steps to continue.");
      } else {
        setReviewMsg(`Deliverable ${decision.replace(/_/g, " ")}.`);
      }
      await loadVersions(plan.plan_id, execution.execution_id);
      await loadExecutionStatus(plan.plan_id, execution.execution_id);
    } catch (e) {
      setRevError(errMsg(e, "Could not review the deliverable."));
    } finally {
      setRevBusy(null);
    }
  }

  async function openVersion(versionId: string) {
    if (!plan || !execution) return;
    try {
      const v = await getDeliverableVersion(plan.plan_id, execution.execution_id, versionId);
      setVersionDetail(v);
    } catch (e) {
      setRevError(errMsg(e, "Could not load the version."));
    }
  }

  const planSteps: TeamGoalStep[] = plan?.steps?.length ? plan!.steps : (review?.steps || []);
  const selectedGoal = goals.find((g) => g.id === selectedGoalId);
  const blocked = execution ? blockedStep(execution) : null;

  return (
    <section className="panel coordination-panel" data-testid="coordination-panel">
      <div className="panel__head">
        <div>
          <h3 className="section-title">Coordination &amp; Deliverables</h3>
          <p className="panel__sub">Authorized plans, per-step execution, and deliverable review.</p>
        </div>
        <div className="coord-actions">
          <button className="btn btn--sm btn--primary" data-testid="coord-new-goal"
            onClick={openCreate}>
            New team goal
          </button>
          <button className="btn btn--sm btn--ghost" data-testid="coord-refresh" onClick={loadGoals}>
            Refresh
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="coord-block coord-author-form" data-testid="coord-create">
          <h5 className="section-title">New team goal</h5>
          <ErrorBox msg={createError} />

          <label className="coord-field">
            <span>Project goal</span>
            <select data-testid="coord-goal-picker" value={formGoalId}
              onChange={(e) => setFormGoalId(e.target.value)} disabled={goalsOptionsLoading}>
              <option value="">Select a project goal…</option>
              {projectGoals.map((g) => (
                <option key={g.id} value={g.id}>{g.title}</option>
              ))}
            </select>
            {goalsOptionsLoading
              ? <span className="muted">Loading goals…</span>
              : !projectGoals.length && <span className="muted">No project goals available yet.</span>}
          </label>

          <label className="coord-field">
            <span>Title</span>
            <input data-testid="coord-form-title" value={formTitle}
              onChange={(e) => setFormTitle(e.target.value)} placeholder="Launch brief" />
          </label>

          <label className="coord-field">
            <span>Coordinator</span>
            <select data-testid="coord-form-coordinator" value={formCoordinator}
              onChange={(e) => setFormCoordinator(e.target.value)}>
              {AGENT_SLUGS.map((a) => (
                <option key={a} value={a}>{humanizeAgent(a)}</option>
              ))}
            </select>
          </label>

          <label className="coord-field">
            <span>Summary (optional)</span>
            <textarea data-testid="coord-form-summary" value={formSummary}
              onChange={(e) => setFormSummary(e.target.value)} />
          </label>

          <label className="coord-field">
            <span>Expected deliverable (optional)</span>
            <input data-testid="coord-form-deliverable" value={formDeliverable}
              onChange={(e) => setFormDeliverable(e.target.value)} />
          </label>

          <h6 className="section-title">Ordered steps</h6>
          {formSteps.map((s, idx) => (
            <div className="coord-step-editor" key={idx} data-testid={`coord-step-editor-${idx + 1}`}>
              <span className="coord-step-editor__seq">#{idx + 1}</span>
              <select data-testid={`coord-step-agent-${idx + 1}`} value={s.agent_id}
                onChange={(e) => updateStep(idx, { agent_id: e.target.value })}>
                {AGENT_SLUGS.map((a) => <option key={a} value={a}>{humanizeAgent(a)}</option>)}
              </select>
              <input data-testid={`coord-step-resp-${idx + 1}`} value={s.responsibility}
                placeholder="Responsibility"
                onChange={(e) => updateStep(idx, { responsibility: e.target.value })} />
              <select data-testid={`coord-step-dep-${idx + 1}`} value={s.depends_on_seq ?? ""}
                onChange={(e) => updateStep(idx, { depends_on_seq: e.target.value ? Number(e.target.value) : null })}>
                <option value="">No dependency</option>
                {Array.from({ length: idx }, (_, k) => k + 1).map((d) => (
                  <option key={d} value={d}>after #{d}</option>
                ))}
              </select>
              <button className="btn btn--sm btn--ghost" data-testid={`coord-step-remove-${idx + 1}`}
                onClick={() => removeStep(idx)} disabled={formSteps.length <= 1}>
                Remove
              </button>
            </div>
          ))}
          <button className="btn btn--sm btn--ghost" data-testid="coord-add-step" onClick={addStep}>
            Add step
          </button>

          <div className="coord-actions">
            <button className="btn btn--primary btn--sm" data-testid="coord-propose"
              onClick={doPropose} disabled={createBusy}>
              {createBusy ? "Proposing…" : "Propose team goal"}
            </button>
            <button className="btn btn--sm btn--ghost" data-testid="coord-cancel-create"
              onClick={closeCreate}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {createSuccess && <p className="success" role="status">{createSuccess}</p>}

      {goalsLoading && <Empty text="Loading team goals…" />}
      <ErrorBox msg={goalsError} />

      {!goalsLoading && !goalsError && goals.length === 0 && (
        <div className="empty">
          <p>No team goals yet. Create and approve a team goal to coordinate a plan.</p>
          <button className="btn btn--sm btn--primary" data-testid="coord-empty-create" onClick={openCreate}>
            New team goal
          </button>
        </div>
      )}

      {goals.length > 0 && (
        <ul className="list" data-testid="coord-goals">
          {goals.map((g) => (
            <li key={g.id} className={`list__item ${selectedGoalId === g.id ? "list__item--selected" : ""}`}>
              <button
                className="origin-link"
                data-testid={`coord-goal-${g.id}`}
                onClick={() => openGoal(g.id)}
              >
                {g.title} · {humanizeAgent(g.coordinator_agent)} · {g.status}
              </button>
            </li>
          ))}
        </ul>
      )}

      {!selectedGoalId && (
        <p className="muted">Select a team goal above to review its plan and execution.</p>
      )}

      {selectedGoalId && (
        <div className="coordination-detail" data-testid="coord-detail">
          <div className="coord-head">
            <h4 className="section-title">{selectedGoal?.title || "Team goal"}</h4>
          </div>
          {goalLoading && <Empty text="Loading goal…" />}
          <ErrorBox msg={goalError} />

          {!plan && review && review.plan_valid && (
            <div className="coord-block">
              <p className="muted">
                Read-only plan preview · Coordinator: {humanizeAgent(review.coordinator)}
              </p>
              <StepList steps={planSteps} />
              <button className="btn btn--primary btn--sm" data-testid="coord-authorize"
                onClick={doAuthorize} disabled={planBusy}>
                {planBusy ? <><span className="spinner" aria-hidden="true" /> Authorizing…</> : "Authorize coordination plan"}
              </button>
              <ErrorBox msg={planError} />
            </div>
          )}

          {plan && (
            <div className="coord-block">
              <div className="coord-plan-head">
                <p className="muted">
                  Authorized plan · Coordinator: {humanizeAgent(plan.coordinator)} ·{" "}
                  {plan.expected_deliverable ? `Expected: ${plan.expected_deliverable}` : "No declared deliverable"}
                </p>
              </div>
              {!execution && (
                <button className="btn btn--primary btn--sm" data-testid="coord-start-exec"
                  onClick={doStartExecution} disabled={execBusy === "start"}>
                  {execBusy === "start" ? <><span className="spinner" aria-hidden="true" /> Starting…</> : "Start execution"}
                </button>
              )}
            </div>
          )}

          {plan && execution && (
            <div className="coord-exec" data-testid="coord-exec">
              <p className="muted">Execution: {execStatusLabel(execution.status)}</p>
              <div className="coord-actions">
                <button className="btn btn--sm" data-testid="coord-exec-next"
                  onClick={doExecuteNext} disabled={execBusy !== null ||
                    execution.status !== "running" || !hasRunnable(execution)}>
                  {execBusy === "execute" ? "Executing…" : "Execute next eligible step"}
                </button>
              </div>
              <StepList steps={planSteps} execution={execution} onReview={doReviewStep}
                busy={revBusy} />

              {execution.status === "ready_for_review" && (
                <div className="deliverable-review" data-testid="coord-deliv">
                  <h5 className="section-title">Consolidated deliverable</h5>
                  <div className="coord-actions">
                    <button className="btn btn--primary btn--sm" data-testid="coord-aggregate"
                      onClick={doAggregate} disabled={revBusy !== null}>
                      {revBusy === "aggregate" ? "Aggregating…" : "Aggregate deliverable"}
                    </button>
                  </div>
                  {execution.deliverable && execution.deliverable.status === "pending" && (
                    <div className="deliverable-actions">
                      <button className="btn btn--sm" data-testid="coord-accept"
                        onClick={() => doReviewDeliverable("accepted")} disabled={revBusy !== null}>
                        Accept
                      </button>
                      <button className="btn btn--sm btn--ghost" data-testid="coord-revision"
                        onClick={() => doReviewDeliverable("revision_requested")} disabled={revBusy !== null}>
                        Request revision
                      </button>
                      <button className="btn btn--sm btn--danger-ghost" data-testid="coord-reject"
                        onClick={() => doReviewDeliverable("rejected")} disabled={revBusy !== null}>
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {blocked != null && (
            <p className="warning" role="alert" data-testid="coord-blocked">
              This execution cannot advance: step {blocked} was rejected, and the
              current workflow has no path to complete a run that includes a rejected step.
            </p>
          )}

          {plan && execution && execution.status === "running" &&
            execution.deliverable?.status === "revision_requested" && (
              <div className="deliverable-rework" data-testid="coord-revision-notice">
                <p className="warning" role="alert">
                  A revision was requested. Re-execute the invalidated steps one at a time, then re-aggregate.
                </p>
              </div>
            )}

          {execution?.deliverable?.status === "pending" && (
            <div className="rework-select" data-testid="coord-rework">
              <h5 className="section-title">Select steps to rework (for revision)</h5>
              {planSteps.map((s) => (
                <label key={s.seq} className="rework-option">
                  <input
                    type="checkbox"
                    data-testid={`coord-rework-${s.seq}`}
                    checked={reworkSelected.includes(s.seq)}
                    onChange={(e) => {
                      setReworkSelected((prev) =>
                        e.target.checked ? [...prev, s.seq] : prev.filter((x) => x !== s.seq));
                    }}
                  />
                  <span>Step {s.seq} · {humanizeAgent(s.agent_id)}</span>
                </label>
              ))}
            </div>
          )}

          <ErrorBox msg={revError} />
          {reviewMsg && <p className="success" role="status">{reviewMsg}</p>}

          {plan && execution && versions.length > 0 && (
            <div className="version-history" data-testid="coord-versions">
              <h5 className="section-title">Deliverable version history</h5>
              <ul className="list">
                {versions.map((v) => (
                  <li key={v.version_id} className="list__item">
                    <button className="origin-link" data-testid={`coord-version-${v.version_id}`}
                      onClick={() => openVersion(v.version_id)}>
                      v{v.version} · {versionStatusLabel(v.status)}
                    </button>
                  </li>
                ))}
              </ul>
              {versionDetail && (
                <div className="version-detail" data-testid="coord-version-detail">
                  <p className="muted">
                    v{versionDetail.version} · {versionStatusLabel(versionDetail.status)}
                    {versionDetail.revision_of ? ` · revises ${versionDetail.revision_of.slice(0, 8)}` : ""}
                  </p>
                  <pre className="version-content">{JSON.stringify(versionDetail.content, null, 2)}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function hasRunnable(execution: ExecutionSummary): boolean {
  return (execution.steps || []).some((s) =>
    s.status === "pending" || s.status === "revision_requested" || s.status === "failed");
}

// A running execution is blocked when a rejected step leaves it with no
// runnable step (<rejected> is not re-runnable) while no human action or
// dispatch is already pending. Returns the seq of the blocking rejected step.
function blockedStep(execution?: ExecutionSummary | null): number | null {
  const steps = execution?.steps || [];
  if (!execution || execution.status !== "running") return null;
  if (steps.some((s) => s.status === "awaiting_review" || s.status === "in_progress")) return null;
  if (hasRunnable(execution)) return null;
  const rejected = steps.find((s) => s.status === "rejected");
  return rejected ? rejected.seq : null;
}

function StepList({ steps, execution, onReview, busy }: {
  steps: TeamGoalStep[];
  execution?: ExecutionSummary | null;
  onReview?: (seq: number, decision: string) => void;
  busy?: string | null;
}) {
  if (!steps.length) return <Empty text="This plan has no steps." />;
  return (
    <ul className="list coord-steps" data-testid="coord-steps">
      {steps.map((s) => {
        const cur = execution?.steps?.find((x) => x.seq === s.seq)?.status ?? s.status;
        const label = stepStatusLabel(cur);
        const awaiting = cur === "awaiting_review";
        return (
          <li key={s.seq} className="list__item coord-step" data-testid={`coord-step-${s.seq}`}>
            <div className="coord-step__main">
              <span className="badge badge--neutral">{s.seq}</span>
              <span className="coord-step__agent">{humanizeAgent(s.agent_id)}</span>
              <span className="coord-step__resp">{s.responsibility || "—"}</span>
              <span className={`badge badge--${cur === "accepted" ? "approved" : cur === "rejected" || cur === "failed" ? "rejected" : "neutral"}`}>
                {label}
              </span>
              {s.depends_on_seq != null && (
                <span className="muted coord-step__dep">after step {s.depends_on_seq}</span>
              )}
            </div>
            {awaiting && onReview && (
              <div className="coord-step__actions">
                <button className="btn btn--sm" data-testid={`coord-accept-${s.seq}`}
                  onClick={() => onReview(s.seq, "accepted")} disabled={!!busy}>
                  Accept
                </button>
                <button className="btn btn--sm btn--ghost" data-testid={`coord-revise-${s.seq}`}
                  onClick={() => onReview(s.seq, "revision_requested")} disabled={!!busy}>
                  Revise
                </button>
                <button className="btn btn--sm btn--danger-ghost" data-testid={`coord-reject-${s.seq}`}
                  onClick={() => onReview(s.seq, "rejected")} disabled={!!busy}>
                  Reject
                </button>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
