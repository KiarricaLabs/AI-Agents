// From-chat-to-deliverable pipeline view (option B).
//
// For a selected work proposal, shows the whole journey as one visible ladder —
// Chat → Proposal → Approval → Created work → Tasks → Deliverable — with the
// current stage highlighted and a jump button into the surface where each stage
// lives. Driven entirely by the real proposal status (GET /work/proposals); it
// never starts or approves anything itself and is read-only.
import { useCallback, useEffect, useState } from "react";
import { API } from "./coordination";

type StageKey = "chat" | "proposal" | "approval" | "created" | "tasks" | "deliverable";

const STAGE_LABEL: Record<StageKey, string> = {
  chat: "Chat",
  proposal: "Proposal",
  approval: "Approval",
  created: "Created work",
  tasks: "Tasks",
  deliverable: "Deliverable",
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

export function Pipeline({ onJump }: { onJump?: (tab: "home" | "projects" | "tasks") => void }) {
  const [props, setProps] = useState<Prop[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${API}/work/proposals`);
      const b = await r.json().catch(() => ({}));
      const items: Prop[] = b.items || [];
      setProps(items);
      setSelected((prev) => (prev && items.some((p) => p.id === prev) ? prev : items[0]?.id || ""));
    } catch {
      setError("Could not load proposals.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const item = props.find((p) => p.id === selected) || null;
  const approved = item ? (item.status || "") !== "proposed" : false;
  const workType = item?.work_type || "";
  const createdLabel = WORK_LABEL[workType] || "Record";

  const stages: { key: StageKey; state: "done" | "now" | "upcoming"; note?: string }[] = [
    { key: "chat", state: "done", note: "Idea from your conversation" },
    { key: "proposal", state: "done", note: "Filed for your review" },
    { key: "approval", state: approved ? "done" : item ? "now" : "upcoming", note: approved ? "Approved" : "Waiting on you" },
    { key: "created", state: approved ? "done" : "upcoming", note: approved ? `${createdLabel} created` : `Creates ${createdLabel}` },
    { key: "tasks", state: approved ? "upcoming" : "upcoming", note: "Served in Task Center" },
    { key: "deliverable", state: approved ? "upcoming" : "upcoming", note: "Reviewed in Work" },
  ];

  const jump = (key: StageKey) => {
    if (!onJump) return;
    if (key === "tasks") onJump("tasks");
    else onJump("projects"); // proposals/approvals and created work live under Projects/Work
  };

  return (
    <section className="coord-block pipeline" data-testid="pipeline">
      <div className="panel__head">
        <div>
          <h3 className="section-title">From chat to deliverable</h3>
          <p className="panel__sub">Pick a proposal to see where it is in the pipeline.</p>
        </div>
        <button className="btn btn--sm btn--ghost" data-testid="pipeline-refresh" onClick={load}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <select className="select" data-testid="pipeline-select" value={selected}
        onChange={(e) => setSelected(e.target.value)} aria-label="Proposal">
        <option value="">Select a proposal…</option>
        {props.map((p) => (
          <option key={p.id} value={p.id}>
            {p.title || p.work_type || p.id.slice(0, 8)} — {p.status} ({p.work_type || "?"})
          </option>
        ))}
      </select>

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
                <span className="pipeline__label">{i + 1}. {STAGE_LABEL[s.key]}</span>
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
    </section>
  );
}
