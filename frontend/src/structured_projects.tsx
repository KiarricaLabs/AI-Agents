import { useCallback, useEffect, useState } from "react";

const API = (import.meta.env.VITE_API_BASE as string | undefined) || "http://127.0.0.1:8001";

type Summary = { id: string; goal: string; status: string };
type Task = { id: string; agent: string; instruction: string; depends_on: string[]; status: string; review_status: string; deliverable_type: string; acceptance_criteria: string[]; output?: string | null };
type Project = Summary & { tasks: Task[] };
type Action = { id: string; project_id: string; agent: string; type: string; payload: Record<string, unknown>; status: string };
type ProjectSummary = { summary: string; completed_tasks: { id: string; agent: string; output?: string | null }[]; pending_decisions: { id?: string; agent?: string; type?: string; kind?: string }[]; blocked_or_failed: { id: string; agent: string; status: string }[] };

function label(status: string) {
  return status.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Project request failed.");
  return body;
}

export function StructuredProjects() {
  const [projects, setProjects] = useState<Summary[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);
  const [feedback, setFeedback] = useState("");
  const [draftEdits, setDraftEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [actions, setActions] = useState<Action[]>([]);
  const [projectSummary, setProjectSummary] = useState<ProjectSummary | null>(null);

  const load = useCallback(async () => {
    try {
      setProjects((await request<{ items: Summary[] }>("/projects")).items || []);
      setActions((await request<{ items: Action[] }>("/actions?status=pending")).items || []);
    }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load projects."); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function open(id: string) {
    setError("");
    try {
      setSelected(await request<Project>(`/projects/${id}`));
      setProjectSummary(await request<ProjectSummary>(`/projects/${id}/summary`));
    }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load the plan."); }
  }

  async function act(action: "approve" | "reject") {
    if (!selected) return;
    setBusy(action); setError("");
    try {
      const body = action === "reject" ? JSON.stringify({ feedback: feedback.trim() || "Please revise this plan." }) : undefined;
      const next = await request<Project>(`/projects/${selected.id}/plan/${action}`, {
        method: "POST", body,
      });
      setSelected(next); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not update the plan."); }
    finally { setBusy(""); }
  }

  async function run() {
    if (!selected) return;
    setBusy("run"); setError("");
    try {
      setSelected(await request<Project>(`/projects/${selected.id}/run`, { method: "POST" }));
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not run the project."); }
    finally { setBusy(""); }
  }

  async function review(taskId: string, action: "approve" | "edit" | "send_back") {
    if (!selected) return;
    const notes = feedback.trim();
    if (action === "send_back" && !notes) {
      setError("Add notes before sending a draft back.");
      return;
    }

    setBusy(`${action}-${taskId}`); setError("");
    try {
      const next = await request<Project>(`/projects/tasks/${taskId}/review`, {
        method: "POST",
        body: JSON.stringify({
          action,
          output: action === "edit" ? draftEdits[taskId] : undefined,
          notes: action === "send_back" ? notes : undefined,
        }),
      });
      setSelected(next); setFeedback(""); await load();
      setProjectSummary(await request<ProjectSummary>(`/projects/${selected.id}/summary`));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not review the draft."); }
    finally { setBusy(""); }
  }

  async function actionDecision(id: string, decision: "approve" | "reject") {
    setBusy(`${decision}-${id}`); setError("");
    try {
      await request(`/actions/${id}/${decision}`, { method: "POST" });
      await load();
      if (selected) setProjectSummary(await request<ProjectSummary>(`/projects/${selected.id}/summary`));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not update the action."); }
    finally { setBusy(""); }
  }

  return (
    <section className="structured-projects" data-testid="structured-projects">
      <div className="structured-projects__head">
        <div>
          <h3 className="section-title">Structured plans</h3>
          <p className="panel__sub">Approve a task-by-task plan before the runner can begin.</p>
        </div>
        <button className="btn btn--sm btn--ghost" onClick={load}>Refresh</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {actions.length > 0 && (
        <div className="structured-projects__actions-panel">
          <h4>Pending approvals</h4>
          <p className="panel__sub">These actions stay local until you approve them. The current executor is a safe simulation.</p>
          {actions.map((action) => (
            <div className="structured-projects__action-card" key={action.id}>
              <div><strong>{label(action.type)} · {action.agent}</strong><pre>{JSON.stringify(action.payload, null, 2)}</pre></div>
              <div className="structured-projects__review-actions">
                <button className="btn btn--primary btn--sm" onClick={() => actionDecision(action.id, "approve")} disabled={!!busy}>{busy === `approve-${action.id}` ? "Approving…" : "Approve action"}</button>
                <button className="btn btn--sm btn--danger-ghost" onClick={() => actionDecision(action.id, "reject")} disabled={!!busy}>Reject</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {!projects.length ? <p className="muted">No structured projects yet. Ask the team to create a plan.</p> : (
        <div className="structured-projects__layout">
          <ul className="structured-projects__list">
            {projects.map((project) => (
              <li key={project.id}>
                <button className={`structured-projects__item${selected?.id === project.id ? " is-selected" : ""}`} onClick={() => open(project.id)}>
                  <strong>{project.goal}</strong>
                  <span>{label(project.status)}</span>
                </button>
              </li>
            ))}
          </ul>
          {selected && (
            <div className="structured-projects__card">
              <div className="workflow-next">
                <strong>{selected.status === "awaiting_plan_approval" ? "Review this plan before work begins" : `Plan ${label(selected.status)}`}</strong>
                <span>Nothing is sent or published from this plan review.</span>
              </div>
              {projectSummary && (
                <div className="structured-projects__summary">
                  <strong>Coordinator summary</strong>
                  <p>{projectSummary.summary}</p>
                  {projectSummary.pending_decisions.length > 0 && (
                    <small>Needs your decision: {projectSummary.pending_decisions.map((item) => item.agent || item.type).join(", ")}</small>
                  )}
                  {projectSummary.blocked_or_failed.length > 0 && (
                    <small className="structured-projects__summary-warning">Blocked or failed: {projectSummary.blocked_or_failed.map((item) => item.agent).join(", ")}</small>
                  )}
                </div>
              )}
              <ol className="structured-projects__tasks">
                {selected.tasks.map((task) => (
                  <li key={task.id}>
                    <div><strong>{task.agent} · {label(task.status)}</strong><span>{task.instruction}</span></div>
                    <small>Deliverable: {task.deliverable_type} · Acceptance: {task.acceptance_criteria.join(" · ") || "Defined in task brief"}</small>
                    {task.depends_on.length > 0 && <small>After: {task.depends_on.join(", ")}</small>}
                    {task.output && <div className="structured-projects__output">
                      <b>Draft output · {label(task.review_status)}</b>
                      <textarea value={draftEdits[task.id] ?? task.output} onChange={(e) => setDraftEdits((prev) => ({ ...prev, [task.id]: e.target.value }))} />
                      {selected.status === "awaiting_review" && task.review_status !== "approved" && (
                        <div className="structured-projects__review-actions">
                          <button className="btn btn--primary btn--sm" onClick={() => review(task.id, "approve")} disabled={!!busy}>{busy === `approve-${task.id}` ? "Approving…" : "Approve draft"}</button>
                          <button className="btn btn--sm btn--ghost" onClick={() => review(task.id, "edit")} disabled={!!busy}>Save edit</button>
                          <button className="btn btn--sm btn--danger-ghost" onClick={() => review(task.id, "send_back")} disabled={!!busy}>Send back</button>
                        </div>
                      )}
                    </div>}
                  </li>
                ))}
              </ol>
              {selected.status === "running" && (
                <button className="btn btn--primary btn--sm" onClick={run} disabled={!!busy}>
                  {busy === "run" ? "Running tasks…" : "Run approved tasks"}
                </button>
              )}
              {selected.status === "awaiting_plan_approval" && (
                <div className="structured-projects__actions">
                  <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="Optional feedback if you want changes." />
                  <button className="btn btn--primary btn--sm" onClick={() => act("approve")} disabled={!!busy}>{busy === "approve" ? "Approving…" : "Approve plan"}</button>
                  <button className="btn btn--sm btn--danger-ghost" onClick={() => act("reject")} disabled={!!busy}>{busy === "reject" ? "Sending back…" : "Reject / send back"}</button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
