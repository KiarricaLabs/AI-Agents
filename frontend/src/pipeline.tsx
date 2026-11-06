// From-chat-to-deliverable pipeline view (option B).
//
// Shows the whole journey as one visible ladder for BOTH work paths:
//   1. Legacy Proposals  — Chat → Proposal → Approval → Created work → Tasks → Deliverable
//   2. Team Goal / coordination — Chat → Proposed → Approved → Plan authorized →
//      Steps run → Deliverable accepted → In Projects
//
// The legacy ladder reads GET /work/proposals; the coordination ladder reads
// GET /team/goals (enriched with plan_authorized / has_execution /
// deliverable_accepted / materialized flags). It never starts or approves
// anything itself and is read-only — it only navigates to the surface where a
// stage lives.
import { useCallback, useEffect, useState } from "react";
import { API } from "./coordination";

type Mode = "proposals" | "goals";

type StageKey = "chat" | "proposal" | "approval" | "created" | "tasks" | "deliverable";
type GoalStageKey = "chat" | "proposal" | "approved" | "plan" | "execute" | "deliverable" | "projects";

const STAGE_LABEL: Record<StageKey, string> = {
  chat: "Chat",
  proposal: "Proposal",
  approval: "Approval",
  created: "Created work",
  tasks: "Tasks",
  deliverable: "Deliverable",
};

const GOAL_STAGE_LABEL: Record<GoalStageKey, string> = {
  chat: "Chat",
  proposal: "Proposed",
  approved: "Approved",
  plan: "Plan authorized",
  execute: "Steps run",
  deliverable: "Deliverable accepted",
  projects: "In Projects",
};

const WORK_LABEL: Record<string, string> = {
  workspace: "Workspace",
  project: "Project",
  goal: "Goal",
  assignment: "Assignment",
  deliverable: "Deliverable",
};

interface Prop {
  id: string;
  work_type?: string;
  status?: string;
  title?: string;
  payload?: any;
  created_at?: string;
}

// Mirror of the enriched list response from GET /team/goals.
interface GoalItem {
  id: string;
  title?: string;
  status?: string;
  coordinator_agent?: string;
  expected_deliverable?: string | null;
  plan_authorized?: boolean;
  has_execution?: boolean;
  deliverable_accepted?: boolean;
  materialized?: boolean;
}

interface Stage { key: string; state: "done" | "now" | "upcoming"; note?: string }

export function Pipeline({ onJump }: { onJump?: (tab: "home" | "projects" | "tasks") => void }) {
  const [mode, setMode] = useState<Mode>("proposals");

  const [props, setProps] = useState<Prop[]>([]);
  const [goals, setGoals] = useState<GoalItem[]>([]);
  const [selected, setSelected] = useState("");
  const [selectedGoal, setSelectedGoal] = useState("");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (m: Mode) => {
    if (m !== mode) return; // avoid clobbering the other mode's data
    setLoading(true);
    setError("");
    try {
      if (m === "goals") {
        const r = await fetch(`${API}/team/goals`);
        const b = await r.json().catch(() => ({}));
        const items: GoalItem[] = b.items || [];
        setGoals(items);
        setSelectedGoal((prev) => (prev && items.some((p) => p.id === prev) ? prev : items[0]?.id || ""));
      } else {
        const r = await fetch(`${API}/work/proposals`);
        const b = await r.json().catch(() => ({}));
        const items: Prop[] = b.items || [];
        setProps(items);
        setSelected((prev) => (prev && items.some((p) => p.id === prev) ? prev : items[0]?.id || ""));
      }
    } catch {
      setError("Could not load the pipeline.");
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => { load(mode); }, [mode, load]);

  const item = props.find((p) => p.id === selected) || null;

  const deleteProp = async () => {
    if (!item) return;
    try {
      const r = await fetch(`${API}/work/proposals/${encodeURIComponent(item.id)}`, { method: "DELETE" });
      if (r.ok) { setSelected(""); await load("proposals"); }
    } catch { /* offline */ }
  };

  // ---- Legacy proposal ladder ----
  const approved = item ? (item.status || "") !== "proposed" : false;
  const workType = item?.work_type || "";
  const createdLabel = WORK_LABEL[workType] || "Record";

  const stages: Stage[] = [
    { key: "chat", state: "done", note: "Idea from your conversation" },
    { key: "proposal", state: "done", note: "Filed for your review" },
    { key: "approval", state: approved ? "done" : item ? "now" : "upcoming", note: approved ? "Approved" : "Waiting on you" },
    { key: "created", state: approved ? "done" : "upcoming", note: approved ? `${createdLabel} created` : `Creates ${createdLabel}` },
    { key: "tasks", state: "upcoming", note: "Served in Task Center" },
    { key: "deliverable", state: "upcoming", note: "Reviewed in Work" },
  ];

  const jump = (key: StageKey) => {
    if (!onJump) return;
    if (key === "tasks") onJump("tasks");
    else onJump("projects");
  };

  // ---- Team Goal / coordination ladder ----
  const goalItems: GoalItem[] = goals;
  const g = goalItems.find((x) => x.id === selectedGoal) || null;
  const goalApproved = g ? (g.status || "") !== "proposed" : false;

  const goalStages: Stage[] = [
    { key: "chat", state: "done", note: "Idea from your conversation" },
    { key: "proposal", state: "done", note: "Filed as a proposed team goal" },
    { key: "approved", state: goalApproved ? "done" : g ? "now" : "upcoming", note: goalApproved ? "Approved" : "Waiting on you" },
    { key: "plan", state: g?.plan_authorized ? "done" : goalApproved ? "now" : "upcoming",
      note: g?.plan_authorized ? "Plan authorized" : goalApproved ? "Waiting on you" : "Authorize the frozen plan" },
    { key: "execute", state: g?.has_execution ? "done" : g?.plan_authorized ? "now" : "upcoming",
      note: g?.has_execution ? "Steps run (human-controlled)" : g?.plan_authorized ? "Ready to run" : "Runs after plan authorization" },
    { key: "deliverable", state: g?.deliverable_accepted ? "done" : g?.has_execution ? "now" : "upcoming",
      note: g?.deliverable_accepted ? "Accepted" : g?.has_execution ? "Under review" : "After execution" },
    { key: "projects", state: g?.materialized ? "done" : g?.deliverable_accepted ? "now" : "upcoming",
      note: g?.materialized ? "Materialized into Projects" : g?.deliverable_accepted ? "Ready to materialize" : "After acceptance" },
  ];

  const goalJump = (key: string) => {
    if (!onJump) return;
    if (key === "projects") onJump("projects");
    else onJump("home"); // coordination panel / approval reviews live on Home
  };

  return (
    <section className="coord-block pipeline" data-testid="pipeline">
      <div className="panel__head">
        <div>
          <h3 className="section-title">From chat to deliverable</h3>
          <p className="panel__sub">Pick a proposal or team goal to see where it is in the pipeline.</p>
        </div>
        <div className="pipeline__modes" role="tablist" aria-label="Pipeline view">
          <button className={mode === "proposals" ? "btn btn--sm btn--ghost is-active" : "btn btn--sm btn--ghost"}
            data-testid="pipeline-mode-proposals" onClick={() => setMode("proposals")} role="tab"
            aria-selected={mode === "proposals"}>Proposals</button>
          <button className={mode === "goals" ? "btn btn--sm btn--ghost is-active" : "btn btn--sm btn--ghost"}
            data-testid="pipeline-mode-goals" onClick={() => setMode("goals")} role="tab"
            aria-selected={mode === "goals"}>Team Goals</button>
        </div>
        <button className="btn btn--sm btn--ghost" data-testid="pipeline-refresh" onClick={() => load(mode)}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      {mode === "proposals" ? (
        <>
          <div className="pipeline__toolbar">
            <select className="select" data-testid="pipeline-select" value={selected}
              aria-label="Proposal"
              onChange={(e) => setSelected(e.target.value)}>
              <option value="">Select a proposal…</option>
              {props.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title || p.work_type || p.id.slice(0, 8)} — {p.status} ({p.work_type || "?"})
                </option>
              ))}
            </select>
            {item && (
              <button className="btn btn--sm btn--ghost" data-testid="pipeline-delete"
                onClick={deleteProp} title="Delete this proposal from the list">Delete</button>
            )}
          </div>
          {!loading && props.length === 0 && (
            <p className="muted" data-testid="pipeline-empty">
              No proposals yet. Use Request a proposal in the AI Team chat to start one.
            </p>
          )}
          {item && (
            <ol className="pipeline__stages" data-testid="pipeline-stages">
              {stages.map((s, i) => (
                <li key={s.key} className={`pipeline__stage pipeline__stage--${s.state}`}
                  data-testid={`pipeline-${s.key}`}>
                  <span className="pipeline__dot" aria-hidden="true" />
                  <div className="pipeline__body">
                    <span className="pipeline__label">{i + 1}. {STAGE_LABEL[s.key as StageKey]}</span>
                    {s.note && <span className="muted">{s.note}</span>}
                    {s.key === "approval" && onJump && (
                      <button className="btn btn--sm btn--ghost" data-testid="pipeline-goto-approvals"
                        onClick={() => onJump("projects")}>Open Approvals</button>
                    )}
                    {s.key === "tasks" && onJump && (
                      <button className="btn btn--sm btn--ghost" data-testid="pipeline-goto-tasks"
                        onClick={() => onJump("tasks")}>Open Task Center</button>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </>
      ) : (
        <>
          <div className="pipeline__toolbar">
            <select className="select" data-testid="pipeline-goal-select" value={selectedGoal}
              aria-label="Team goal"
              onChange={(e) => setSelectedGoal(e.target.value)}>
              <option value="">Select a team goal…</option>
              {goalItems.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title || p.id.slice(0, 8)} — {p.status || "?"}
                </option>
              ))}
            </select>
          </div>
          {!loading && goalItems.length === 0 && (
            <p className="muted" data-testid="pipeline-goal-empty">
              No team goals yet. Use Delegate to the team in the AI Team chat to start a coordination goal.
            </p>
          )}
          {g && (
            <ol className="pipeline__stages" data-testid="pipeline-goal-stages">
              {goalStages.map((s, i) => (
                <li key={s.key} className={`pipeline__stage pipeline__stage--${s.state}`}
                  data-testid={`pipeline-goal-${s.key}`}>
                  <span className="pipeline__dot" aria-hidden="true" />
                  <div className="pipeline__body">
                    <span className="pipeline__label">{i + 1}. {GOAL_STAGE_LABEL[s.key as GoalStageKey]}</span>
                    {s.note && <span className="muted">{s.note}</span>}
                    {onJump && (s.key === "plan" || s.key === "approved" || s.key === "execute") && (
                      <button className="btn btn--sm btn--ghost" data-testid={`pipeline-goto-coord-${s.key}`}
                        onClick={() => goalJump(s.key)}>Open Coordination</button>
                    )}
                    {onJump && s.key === "projects" && (
                      <button className="btn btn--sm btn--ghost" data-testid="pipeline-goto-goal-projects"
                        onClick={() => goalJump("projects")}>Open Projects</button>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
