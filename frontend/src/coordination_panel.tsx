// T2-C-6 — Coordination & Deliverable Review panel.
//
// A self-contained React component added inside the AI Team tab. It drives the
// T2-C-3/4/5 backend through the typed API layer (./coordination).
//
// Rules honored by the UI:
// - Execution is autonomous within a single human "Run all steps" action: every
//   eligible step runs in order and is auto-accepted, then the consolidated
//   deliverable is aggregated. There is no per-step manual gate and no
//   scheduler/background dispatch outside that one human-launched action.
// - The human reviews the final deliverable (accept / request revision / reject).
//   Revision invalidates the selected rework steps and re-runs them autonomously.
// - The coordination-plan snapshot is read-only.
// - Deliverable version history is immutable and read-only.
// - The UI never overrides server-side authorization / permission ceilings.

import { useCallback, useEffect, useState } from "react";
import {
  API,
  listTeamGoals,
  getTeamGoal,
  listProjectGoals,
  proposeTeamGoal,
  draftTeamGoalFromMessage,
  reviewCoordinationPlan,
  authorizeCoordinationPlan,
  initiateExecution,
  runAutonomously,
  approveTeamGoal,
  approveTeamGoalStep,
  reviewDeliverable,
  validateTeamGoalDraft,
  getExecutionStatus,
  listDeliverableVersions,
  getDeliverableVersion,
  stepStatusLabel,
  execStatusLabel,
  versionStatusLabel,
  humanizeAgent,
  AGENT_SLUGS,
  type TeamGoalSummary,
  type TeamGoalDetail,
  type TeamGoalStep,
  type CoordinationPlan,
  type ReviewPlan,
  type ExecutionSummary,
  type DeliverableVersion,
  type ProjectGoal,
  type ProposeTeamGoalInput,
  type TeamGoalDraft,
} from "./coordination";
import { Markdown } from "./markdown";

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

function goalStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    proposed: "Needs approval · proposed",
    approved: "Goal approved",
    rejected: "Rejected",
    in_progress: "In progress",
    ready_for_review: "Ready to review",
    completed: "Complete",
    revision_requested: "Changes requested",
  };
  return labels[status] || status.replaceAll("_", " ");
}

// A draft step in the authoring form (seq is derived from array order).
interface StepDraft {
  agent_id: string;
  responsibility: string;
  depends_on_seq: number | null;
}

export function Coordination() {
  const [goals, setGoals] = useState<TeamGoalSummary[]>([]);
  const [goalPreviews, setGoalPreviews] = useState<Record<string, TeamGoalDetail>>({});
  const [goalsLoading, setGoalsLoading] = useState(false);
  const [goalsError, setGoalsError] = useState("");

  const [selectedGoalId, setSelectedGoalId] = useState<string | null>(null);
  const [selectedGoalDetail, setSelectedGoalDetail] = useState<TeamGoalDetail | null>(null);
  const [goalLoading, setGoalLoading] = useState(false);
  const [goalError, setGoalError] = useState("");
  const [goalApproveBusy, setGoalApproveBusy] = useState(false);
  const [stepApproveBusy, setStepApproveBusy] = useState<number | null>(null);

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
  const [agentQuestion, setAgentQuestion] = useState("");
  const [agentReply, setAgentReply] = useState("");
  const [agentQuestionBusy, setAgentQuestionBusy] = useState(false);
  const [selectedAgentForChat, setSelectedAgentForChat] = useState<string | null>(null);

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
  const [draftMsg, setDraftMsg] = useState("");
  const [draftBusy, setDraftBusy] = useState(false);

  const loadGoals = useCallback(async () => {
    setGoalsLoading(true);
    setGoalsError("");
    try {
      const r = await listTeamGoals();
      const items = r.items || [];
      setGoals(items);
    } catch (e) {
      setGoalsError(errMsg(e, "Could not load team goals."));
    } finally {
      setGoalsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGoals();
  }, [loadGoals]);

  // Refresh the goal list when a goal is created elsewhere (e.g. via the chat
  // "Delegate to the team" action) so the new goal is visible immediately.
  useEffect(() => {
    const onCreated = () => loadGoals();
    window.addEventListener("ai-team:goal-created", onCreated);
    return () => window.removeEventListener("ai-team:goal-created", onCreated);
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

  function applyDraft(d: TeamGoalDraft) {
    setFormTitle(d.title || "");
    setFormSummary(d.summary || "");
    setFormDeliverable(d.expected_deliverable || "");
    setFormCoordinator(d.coordinator_agent || formCoordinator);
    setFormSteps((d.steps || []).map((s) => ({
      agent_id: s.agent_id,
      responsibility: s.responsibility || "",
      depends_on_seq: s.depends_on_seq != null ? s.depends_on_seq : null,
    })));
  }

  async function doGenerateDraft() {
    if (!draftMsg.trim()) { setCreateError("Enter a discussion or idea to draft from."); return; }
    setDraftBusy(true);
    setCreateError("");
    try {
      const d = await draftTeamGoalFromMessage(draftMsg, formCoordinator);
      applyDraft(d);
    } catch (e) {
      setCreateError(errMsg(e, "Could not generate a draft."));
    } finally {
      setDraftBusy(false);
    }
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
      // Capability/delegation guidance BEFORE proposing (T2-C-8 gap): surface
      // which steps can\u2019t be fulfilled by a delegable, capable agent so the
      // author corrects them now instead of failing at plan authorization.
      try {
        const val = await validateTeamGoalDraft(formCoordinator, payload.steps as any[]);
        if (!val.plan_valid) {
          setCreateError(
            "This plan can\u2019t run yet \u2014 " +
            val.errors[0] +
            ". Assign each step to an agent the coordinator can delegate to with a matching capability (or change the coordinator).");
          return;
        }
      } catch { /* server unavailable — fall through to submit; plan review still enforces */ }
      const r = await proposeTeamGoal(payload);
      window.dispatchEvent(new CustomEvent("ai-team:goal-created"));
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
    setSelectedGoalDetail(null);
    setExecution(null);
    setVersions([]);
    setVersionDetail(null);
    setReworkSelected([]);
    setReviewMsg("");
    try {
      const detail = await getTeamGoal(goalId);
      setSelectedGoalDetail(detail);
      setGoalPreviews((prev) => ({ ...prev, [goalId]: detail }));
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
      window.dispatchEvent(new CustomEvent("ai-team:workflow-updated"));
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
      window.dispatchEvent(new CustomEvent("ai-team:workflow-updated"));
    } catch (e) {
      setRevError(errMsg(e, "Could not start execution."));
    } finally {
      setExecBusy(null);
    }
  }

  async function doRun() {
    // Autonomous run: executes every eligible step (in dependency order) and
    // aggregates the deliverable for the owner's final review in one action.
    if (!plan || !execution) return;
    setExecBusy("run");
    setRevError("");
    setReviewMsg("");
    try {
      await runAutonomously(plan.plan_id, execution.execution_id);
      await loadExecutionStatus(plan.plan_id, execution.execution_id);
      await loadVersions(plan.plan_id, execution.execution_id);
      window.dispatchEvent(new CustomEvent("ai-team:workflow-updated"));
    } catch (e) {
      setRevError(errMsg(e, "Could not run the execution."));
    } finally {
      setExecBusy(null);
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
        if (r.steps?.length) {
          setReviewMsg(`Rework required on: ${r.steps.join(", ")}. Re-running the affected steps…`);
        } else {
          setReviewMsg("Revision requested. Re-running the affected steps…");
        }
        setReworkSelected([]);
        // Autonomous rework: re-run only the invalidated steps and re-aggregate.
        await runAutonomously(plan.plan_id, execution.execution_id);
      } else {
        setReviewMsg(`Deliverable ${decision.replace(/_/g, " ")}.`);
      }
      await loadVersions(plan.plan_id, execution.execution_id);
      await loadExecutionStatus(plan.plan_id, execution.execution_id);
      window.dispatchEvent(new CustomEvent("ai-team:workflow-updated"));
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
  const proposedSteps = selectedGoalDetail?.steps || [];
  const selectedGoal = goals.find((g) => g.id === selectedGoalId);

  async function askAgent(agentId: string) {
    const question = agentQuestion.trim();
    if (!question || !selectedGoalDetail || agentQuestionBusy) return;
    const step = selectedGoalDetail.steps.find((item) => item.agent_id === agentId);
    const responsibility = step?.responsibility || "the assigned responsibility";
    const sharedPlan = selectedGoalDetail.steps
      .map((item) => {
        const dependency = item.depends_on_seq == null
          ? "no dependency"
          : `after step ${item.depends_on_seq}`;
        return `Step ${item.seq} — ${humanizeAgent(item.agent_id)} — ${item.responsibility || "responsibility not specified"} (${dependency})`;
      })
      .join("\n");
    setAgentQuestionBusy(true);
    setAgentReply("");
    try {
      const r = await fetch(`${API}/team/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: `[Plan review for ${selectedGoalDetail.title}]

SHARED TEAM PLAN — this is the complete plan all agents are reviewing:
${sharedPlan}

YOUR ASSIGNED RESPONSIBILITY:
Step ${step?.seq ?? "?"} — ${humanizeAgent(agentId)} — ${responsibility}

Explain how your responsibility fits with the other agents' responsibilities, what you depend on, and what you will hand off or produce next. Use the shared plan above instead of asking the user to repeat it. Stay within your assigned responsibility. Do not invent agents, roles, capabilities, deadlines, tools, credentials, publishing, sending, booking, payments, ad launches, or other work outside this assignment. For this local credential-free review, describe analysis, drafts, recommendations, or simulated local artifacts only.

User question: ${question}`,
          thread_id: selectedGoalDetail.thread_id || undefined,
          subject_agent: agentId,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAgentReply(body.detail || "The agent could not respond right now.");
        return;
      }
      const response = (body.responses || []).find((item: any) => item.agent === agentId)
        || (body.responses || [])[0];
      if (response?.reply) {
        setAgentReply(response.reply);
      } else if ((body.errors || []).length) {
        const detail = (body.errors || [])
          .map((item: any) => item.detail || item.code || "unknown error")
          .join("; ");
        setAgentReply(`The agent could not respond: ${detail}`);
      } else {
        setAgentReply("The agent did not return a response. Try the check-in again.");
      }
    } catch {
      setAgentReply("Could not reach the agent. Please try again.");
    } finally {
      setAgentQuestionBusy(false);
    }
  }

  async function doApproveGoal() {
    if (!selectedGoal) return;
    setGoalApproveBusy(true);
    setGoalError("");
    try {
      for (const step of selectedGoalDetail?.steps || []) {
        if (step.status !== "approved") await approveTeamGoalStep(selectedGoal.id, step.seq);
      }
      await approveTeamGoal(selectedGoal.id);
      await loadGoals();
      await openGoal(selectedGoal.id);
    } catch (e) {
      setGoalError(errMsg(e, "Could not approve the team goal."));
    } finally {
      setGoalApproveBusy(false);
    }
  }
  async function doApproveStep(seq: number) {
    if (!selectedGoalId) return;
    setStepApproveBusy(seq);
    try {
      await approveTeamGoalStep(selectedGoalId, seq);
      const detail = await getTeamGoal(selectedGoalId);
      setSelectedGoalDetail(detail);
    } catch (e) {
      setGoalError(errMsg(e, "Could not approve this agent plan."));
    } finally {
      setStepApproveBusy(null);
    }
  }
  const blocked = execution ? blockedStep(execution) : null;
  const phase = workflowPhase(selectedGoal, plan, execution);

  return (
    <section className="panel coordination-panel" data-testid="coordination-panel">
      <div className="panel__head">
        <div>
          <h3 className="section-title">Team workflow</h3>
          <p className="panel__sub">Review the team’s plan, then choose when work can begin.</p>
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
            <span>Generate from a discussion (optional)</span>
            <textarea data-testid="coord-draft-message" value={draftMsg}
              onChange={(e) => setDraftMsg(e.target.value)}
              placeholder={"Paste a discussion or idea, e.g.\n- strategist: research the market\n- tutor: explain findings\ndeliverable: a one-page plan"} />
          </label>
          <div className="coord-actions">
            <button className="btn btn--sm btn--ghost" data-testid="coord-draft-gen"
              onClick={doGenerateDraft} disabled={draftBusy}>
              {draftBusy ? "Drafting…" : "Generate draft"}
            </button>
          </div>

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
              <div className="coord-goal-row">
                <button
                  className="origin-link coord-goal-row__open"
                data-testid={`coord-goal-${g.id}`}
                onClick={() => openGoal(g.id)}
                >
                  <span>{g.title}</span>
                  <span className={`status-chip status-chip--${g.status}`}>{goalStatusLabel(g.status)}</span>
                </button>
                <span className="coord-goal-row__owner">Coordinator: {humanizeAgent(g.coordinator_agent)}</span>
                <button className="btn btn--sm btn--ghost" onClick={() => openGoal(g.id)}>
                  View agent plans
                </button>
              </div>
              {goalPreviews[g.id] && (
                <ol className="coord-goal-preview" aria-label={`Agent plans for ${g.title}`}>
                  {(goalPreviews[g.id].steps || []).map((step) => (
                    <li key={step.seq}>
                      <strong>{humanizeAgent(step.agent_id)}</strong>
                      <span>{step.responsibility || "Plan responsibility not specified yet."}</span>
                      <em>{stepStatusLabel(step.status)}</em>
                    </li>
                  ))}
                </ol>
              )}
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
            {selectedGoal && (
              <p className="panel__sub">
                Owner: {humanizeAgent(selectedGoal.coordinator_agent)} · Review each agent plan below before authorizing work.
              </p>
            )}
          </div>
          {goalLoading && <Empty text="Loading goal…" />}
          <ErrorBox msg={goalError} />
          {selectedGoal && (
            <div className="coord-flow" data-testid="coord-flow">
              <div className="coord-flow__steps" aria-label="Workflow progress">
                {["Review", "Approve", "Begin", "Run", "Result"].map((label, index) => (
                  <span key={label} className={index + 1 <= phase.number ? "is-active" : ""}>
                    <b>{index + 1}</b>{label}
                  </span>
                ))}
              </div>
              <strong>Next: {phase.label}</strong>
              <span>{phase.hint}</span>
            </div>
          )}

          {selectedGoal && selectedGoal.status === "proposed" && (
            <div className="coord-block">
              <div className="workflow-next">
                <strong>Next: approve this goal</strong>
                <span>Approval lets the coordinator prepare the work plan. Nothing runs yet.</span>
              </div>
              <button className="btn btn--primary btn--sm" data-testid="coord-approve"
                onClick={doApproveGoal} disabled={goalApproveBusy}>
                {goalApproveBusy ? "Approving…" : "Approve all plans"}
              </button>
            </div>
          )}

          {selectedGoal && selectedGoal.status === "proposed" && proposedSteps.length > 0 && (
            <div className="coord-block plan-review-card" data-testid="coord-proposed-plan">
              <div className="workflow-next">
                <strong>Plan from the team</strong>
                <span>Review each responsibility before approving. You can ask an agent to clarify or critique its approach.</span>
              </div>
              <ol className="agent-plan-list">
                {proposedSteps.map((step) => (
                  <li key={step.seq} className="agent-plan-item">
                    <div className="agent-plan-item__body">
                      <strong>Step {step.seq}: {humanizeAgent(step.agent_id)}</strong>
                      <span>{step.responsibility || "Responsibility not specified."}</span>
                      {step.depends_on_seq != null && <small>Starts after step {step.depends_on_seq}</small>}
                      {step.plan && (
                        <div className="agent-plan-item__plan">
                          <strong>Agent plan</strong>
                          <Markdown source={step.plan} />
                        </div>
                      )}
                    </div>
                    <button className="btn btn--sm btn--ghost" onClick={() => {
                      setSelectedAgentForChat(step.agent_id);
                      setAgentQuestion(`What is your approach for step ${step.seq}, and what would you need from me before starting?`);
                      setAgentReply("");
                    }}>
                      Check with {humanizeAgent(step.agent_id)}
                    </button>
                    <button className="btn btn--sm btn--primary" disabled={step.status === "approved" || stepApproveBusy === step.seq}
                      onClick={() => doApproveStep(step.seq)}>
                      {step.status === "approved" ? "Approved" : stepApproveBusy === step.seq ? "Approving…" : "Approve plan"}
                    </button>
                  </li>
                ))}
              </ol>
              {selectedAgentForChat && (
                <div className="agent-plan-chat" data-testid="coord-agent-chat">
                  <strong>Check in with {humanizeAgent(selectedAgentForChat)}</strong>
                  <textarea value={agentQuestion} onChange={(e) => setAgentQuestion(e.target.value)}
                    placeholder="Ask about the approach, assumptions, or expected result." />
                  <div className="coord-actions">
                    <button className="btn btn--sm btn--primary" onClick={() => askAgent(selectedAgentForChat)}
                      disabled={agentQuestionBusy || !agentQuestion.trim()}>
                      {agentQuestionBusy ? `Waiting for ${humanizeAgent(selectedAgentForChat)}…` : "Ask agent"}
                    </button>
                    <button className="btn btn--sm btn--ghost" onClick={() => setSelectedAgentForChat(null)}>Close</button>
                  </div>
                  {agentReply && <div className="agent-plan-chat__reply"><Markdown source={agentReply} /></div>}
                </div>
              )}
            </div>
          )}

          {!plan && review && review.plan_valid && (
            <div className="coord-block">
              <div className="workflow-next">
                <strong>Next: review and authorize the plan</strong>
                <span>Check who is doing what. Authorizing freezes the plan; it does not run it.</span>
              </div>
              <p className="muted">Coordinator: {humanizeAgent(review.coordinator)}</p>
              <StepList steps={planSteps} />
              <button className="btn btn--primary btn--sm" data-testid="coord-authorize"
                onClick={doAuthorize} disabled={planBusy}>
                {planBusy ? <><span className="spinner" aria-hidden="true" /> Locking plan…</> : "Lock plan & continue"}
              </button>
              <ErrorBox msg={planError} />
            </div>
          )}

          {plan && (
            <div className="coord-block">
              <div className="coord-plan-head">
                <div className="workflow-next workflow-next--complete">
                  <strong>Plan authorized</strong>
                  <span>{plan.expected_deliverable ? `The team will create: ${plan.expected_deliverable}` : "The team is ready to work."} Coordinator: {humanizeAgent(plan.coordinator)}.</span>
                </div>
              </div>
              {!execution && (
                <button className="btn btn--primary btn--sm" data-testid="coord-start-exec"
                  onClick={doStartExecution} disabled={execBusy === "start"}>
                  {execBusy === "start" ? <><span className="spinner" aria-hidden="true" /> Starting…</> : "Begin work"}
                </button>
              )}
            </div>
          )}

          {plan && execution && (
            <div className="coord-exec" data-testid="coord-exec">
              <div className="workflow-status">
                <strong>{execution.status === "ready_for_review" ? "Work completed — review the result" : `Work status: ${execStatusLabel(execution.status)}`}</strong>
                <span>{execution.status === "ready_for_review" ? "The team’s output is below. Accept it or request changes." : "This runs the approved steps locally. Nothing is published or sent."}</span>
              </div>
              {execution.status === "running" && <div className="coord-actions">
                <button className="btn btn--primary btn--sm" data-testid="coord-run"
                  onClick={doRun} disabled={execBusy !== null || execBusy === "run" ||
                    !hasRunnable(execution)}>
                  {execBusy === "run" ? "Working…" : "Run team steps"}
                </button>
              </div>}
              <StepList steps={planSteps} execution={execution} />

              {execution.status === "ready_for_review" && execution.deliverable?.status === "pending" && (
                <div className="deliverable-review" data-testid="coord-deliv">
                  <h5 className="section-title">Team result</h5>
                  {execution.deliverable && execution.deliverable.status === "pending" && (
                    <div className="deliverable-actions">
                      <button className="btn btn--sm" data-testid="coord-accept"
                        onClick={() => doReviewDeliverable("accepted")} disabled={revBusy !== null}>
                        Accept result
                      </button>
                      <button className="btn btn--sm btn--ghost" data-testid="coord-revision"
                        onClick={() => doReviewDeliverable("revision_requested")} disabled={revBusy !== null}>
                        Request changes
                      </button>
                      <button className="btn btn--sm btn--danger-ghost" data-testid="coord-reject"
                        onClick={() => doReviewDeliverable("rejected")} disabled={revBusy !== null}>
                        Reject result
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
                  A revision was requested. Run again to re-execute the invalidated steps, then re-review.
                </p>
              </div>
            )}

          {execution?.deliverable?.status === "pending" && (
            <div className="rework-select" data-testid="coord-rework">
              <h5 className="section-title">What should be redone?</h5>
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
              <h5 className="section-title">Previous results</h5>
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

function StepList({ steps, execution }: {
  steps: TeamGoalStep[];
  execution?: ExecutionSummary | null;
}) {
  if (!steps.length) return <Empty text="This plan has no steps." />;
  return (
    <ul className="list coord-steps" data-testid="coord-steps">
      {steps.map((s) => {
        const cur = execution?.steps?.find((x) => x.seq === s.seq)?.status ?? s.status;
        const label = stepStatusLabel(cur);
        return (
          <li key={s.seq} className="list__item coord-step" data-testid={`coord-step-${s.seq}`}>
            <div className="coord-step__main">
              <span className="badge badge--neutral">{s.seq}</span>
              <span className="coord-step__agent">{humanizeAgent(s.agent_id)}</span>
              <span className="coord-step__resp">{s.responsibility || "—"}</span>
              <span className={
                `badge badge--${cur === "accepted" ? "approved"
                  : cur === "rejected" || cur === "failed" ? "rejected" : "neutral"}`}>
                {label}
              </span>
              {s.depends_on_seq != null && (
                <span className="muted coord-step__dep">after step {s.depends_on_seq}</span>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function workflowPhase(goal: { status: string } | null | undefined, plan: CoordinationPlan | null,
                      execution: ExecutionSummary | null): { number: number; label: string; hint: string } {
  if (execution?.status === "ready_for_review") {
    return { number: 5, label: "Review the result", hint: "The team finished. Review the combined result below." };
  }
  if (execution?.status === "running") {
    const active = execution.steps?.find((step) => step.status === "in_progress");
    return {
      number: 4,
      label: active ? `Running step ${active.seq}` : "Run the team steps",
      hint: "The approved steps run locally in order. Nothing is published or sent.",
    };
  }
  if (plan) return { number: 3, label: "Begin the work", hint: "The plan is locked. Start execution when you are ready." };
  if (goal?.status === "approved") {
    return { number: 2, label: "Authorize the plan", hint: "Review the assignments, then lock the plan before work begins." };
  }
  return { number: 1, label: "Review and approve the plans", hint: "Read each agent’s plan. Nothing runs until you approve it." };
}
