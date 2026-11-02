import { useEffect, useState, type ReactNode } from "react";
import { diffLines } from "./diff";
import { Markdown } from "./markdown";
import "./App.css";

const API = "http://127.0.0.1:8001";

type Tab =
  | "overview"
  | "workspace"
  | "work"
  | "episodes"
  | "agents";

const NAV: { id: Tab; icon: string }[] = [
  { id: "overview", icon: "home" },
  { id: "workspace", icon: "grid" },
  { id: "work", icon: "briefcase" },
  { id: "episodes", icon: "activity" },
  { id: "agents", icon: "bot" },
];

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const children: Record<string, ReactNode> = {
    home: (
      <>
        <path d="M3 11l9-7 9 7" />
        <path d="M5 10v10h14V10" />
        <path d="M9 20v-6h6v6" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="8" height="8" rx="1.6" />
        <rect x="13" y="3" width="8" height="8" rx="1.6" />
        <rect x="3" y="13" width="8" height="8" rx="1.6" />
        <rect x="13" y="13" width="8" height="8" rx="1.6" />
      </>
    ),
    briefcase: (
      <>
        <rect x="3" y="7" width="18" height="13" rx="2" />
        <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      </>
    ),
    target: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="4" />
        <circle cx="12" cy="12" r="0.5" />
      </>
    ),
    checklist: (
      <>
        <rect x="5" y="4" width="14" height="17" rx="2" />
        <path d="M9 11.5l2 2 4-4" />
      </>
    ),
    file: (
      <>
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
        <path d="M14 3v5h5" />
        <path d="M9 13h6M9 17h6" />
      </>
    ),
    activity: <path d="M3 12h4l2-7 4 14 2-7h6" />,
    bot: (
      <>
        <rect x="4" y="7" width="16" height="12" rx="3" />
        <path d="M12 7V4" />
        <circle cx="12" cy="3.4" r="0.9" />
        <circle cx="9" cy="12" r="0.9" />
        <circle cx="15" cy="12" r="0.9" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children[name]}
    </svg>
  );
}

function humanize(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function uniqueBy<T>(arr: T[], key: (x: T) => string): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const x of arr) {
    const k = key(x);
    if (!seen.has(k)) {
      seen.add(k);
      out.push(x);
    }
  }
  return out;
}

function Empty({ text }: { text: string }) {
  return <div className="empty">{text}</div>;
}

function Stat({ icon, label, value }: { icon: string; label: string; value: number }) {
  return (
    <div className="stat">
      <span className="stat__icon">
        <Icon name={icon} size={18} />
      </span>
      <span className="stat__value">{value}</span>
      <span className="stat__label">{label}</span>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [health, setHealth] = useState("checking...");
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [goals, setGoals] = useState<any[]>([]);
  const [assignments, setAssignments] = useState<any[]>([]);
  const [versions, setVersions] = useState<any[]>([]);
  const [episodes, setEpisodes] = useState<any[]>([]);
  const [selectedEpisode, setSelectedEpisode] = useState<string | null>(null);
  const [episodeDetail, setEpisodeDetail] = useState<any>(null);
  const [episodeEvents, setEpisodeEvents] = useState<any[]>([]);
  const [deliverablesList, setDeliverablesList] = useState<any[]>([]);
  const [selectedDeliverable, setSelectedDeliverable] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [offline, setOffline] = useState(false);
  const [agents, setAgents] = useState<any[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [task, setTask] = useState("");
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentResult, setAgentResult] = useState<any>(null);
  const [agentError, setAgentError] = useState("");
  const [threadIds, setThreadIds] = useState<Record<string, string>>({});
  const [contextCounts, setContextCounts] = useState<Record<string, number>>({});
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  // Independent filters + search for each Work-view subsection.
  const [goalStatusFilter, setGoalStatusFilter] = useState("");
  const [goalSearch, setGoalSearch] = useState("");
  const [assignmentAgentFilter, setAssignmentAgentFilter] = useState("");
  const [assignmentSearch, setAssignmentSearch] = useState("");
  const [deliverableStatusFilter, setDeliverableStatusFilter] = useState("");
  const [deliverableSearch, setDeliverableSearch] = useState("");

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then((d) => setHealth(JSON.stringify(d)))
      .catch(() => {
        setHealth("offline");
        setOffline(true);
      });
    refresh();
    fetchAgents();
  }, []);

  const fetchAgents = async () => {
    try {
      const r = await fetch(`${API}/agents`);
      const d = await r.json();
      setAgents(d.agents || []);
    } catch {
      /* offline or backend unavailable */
    }
  };

  const selectAgent = (agentName: string) => {
    setSelectedAgent(agentName);
    setAgentResult(null);
    setAgentError("");
  };

  const runAgent = async () => {
    if (offline || agentRunning || !selectedAgent || !task.trim()) return;
    const submitted = task.trim();
    setAgentRunning(true);
    setAgentError("");
    setAgentResult(null);
    const payload: any = { task: submitted };
    if (threadIds[selectedAgent]) payload.thread_id = threadIds[selectedAgent];
    // Clear the input immediately so it is ready for the next message while
    // the agent processes; it is restored below if the submission fails.
    setTask("");
    try {
      const r = await fetch(`${API}/agents/${selectedAgent}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAgentError(body.detail || `request failed (${r.status})`);
        setTask(submitted); // preserve the message on a rejected submission
      } else {
        setAgentResult(body);
        if (body.thread_id) {
          setThreadIds((prev) => ({ ...prev, [selectedAgent]: body.thread_id }));
        }
        if (typeof body.context_messages === "number") {
          setContextCounts((prev) => ({ ...prev, [selectedAgent]: body.context_messages }));
        }
      }
    } catch (e: any) {
      setAgentError(e?.message || "network error");
      setTask(submitted); // preserve the message on a network failure
    } finally {
      setAgentRunning(false);
    }
  };

  const newConversation = () => {
    setThreadIds((prev) => {
      const next = { ...prev };
      delete next[selectedAgent];
      return next;
    });
    setContextCounts((prev) => {
      const next = { ...prev };
      delete next[selectedAgent];
      return next;
    });
    setAgentResult(null);
    setAgentError("");
    setTask("");
  };

  const refresh = async () => {
    try {
      const w = await fetch(`${API}/workspaces`).then((r) => r.json());
      setWorkspaces(w.items || []);
      const p = await fetch(`${API}/workspaces/projects`).then((r) => r.json());
      setProjects(p.items || []);
      const g = await fetch(`${API}/workspaces/goals`).then((r) => r.json());
      setGoals(g.items || []);
      const a = await fetch(`${API}/workspaces/assignments`).then((r) => r.json());
      setAssignments(a.items || []);
      try {
        const e = await fetch(`${API}/episodes`).then((r) => r.json());
        setEpisodes(e.items || []);
        const d = await fetch(`${API}/workspaces/deliverables`).then((r) => r.json());
        setDeliverablesList(d.items || []);
      } catch {}
    } catch {
      setOffline(true);
    }
  };

  const createWorkspace = async () => {
    if (!name || offline) return;
    await fetch(`${API}/workspaces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    setName("");
    refresh();
  };

  const createProject = async () => {
    const wid = selectedWorkspaceId || workspaces[0]?.id;
    if (offline || !wid) return;
    await fetch(`${API}/workspaces/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: wid, name: "New Project" }),
    });
    refresh();
  };

  const createGoal = async () => {
    const pid = selectedProjectId || projects[0]?.id;
    if (offline || !pid) return;
    await fetch(`${API}/workspaces/goals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: pid, title: "New Goal", priority: 1 }),
    });
    refresh();
  };

  const createDeliverable = async () => {
    const pid = selectedProjectId || projects[0]?.id;
    if (offline || !pid) return;
    const r = await fetch(`${API}/workspaces/deliverables`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: pid, title: "New Deliverable" }),
    });
    const d = await r.json();
    if (d.id) {
      await fetch(`${API}/workspaces/deliverables/${d.id}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: "v1 content" }),
      });
    }
    refresh();
  };

  const loadVersions = async (did: string) => {
    setSelectedDeliverable(did);
    const r = await fetch(`${API}/workspaces/deliverables/${did}/versions`);
    const d = await r.json();
    setVersions(d.items || []);
  };

  const approveVersion = async (vid: string) => {
    if (offline) return;
    await fetch(`${API}/workspaces/versions/${vid}/approve`, { method: "POST" });
    if (selectedDeliverable) loadVersions(selectedDeliverable);
  };

  const rejectVersion = async (vid: string) => {
    if (offline) return;
    await fetch(`${API}/workspaces/versions/${vid}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "requested revision" }),
    });
    if (selectedDeliverable) loadVersions(selectedDeliverable);
  };

  const cancelEpisode = async (eid: string) => {
    if (offline) return;
    await fetch(`${API}/episodes/${eid}/cancel`, { method: "POST" });
    refresh();
  };

  const resumeEpisode = async (eid: string) => {
    if (offline) return;
    await fetch(`${API}/episodes/${eid}/resume`, { method: "POST" });
    refresh();
  };

  const loadEpisode = async (eid: string) => {
    setSelectedEpisode(eid);
    setEpisodeEvents([]);
    setEpisodeDetail(null);
    try {
      const r = await fetch(`${API}/episodes/${eid}`);
      const d = await r.json();
      setEpisodeDetail(d.episode || null);
      setEpisodeEvents(d.events || []);
    } catch {
      /* offline or backend unavailable */
    }
  };

  const formatStamp = (iso?: string) => {
    if (!iso) return "";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  };

  // Work-view scope selection. Changing the workspace invalidates any project
  // that belonged to the previous workspace and clears stale deliverable state.
  const selectWorkspaceForWork = (wid: string) => {
    setSelectedWorkspaceId(wid || null);
    setSelectedProjectId(null);
    setSelectedDeliverable(null);
    setGoalStatusFilter("");
    setGoalSearch("");
    setAssignmentAgentFilter("");
    setAssignmentSearch("");
    setDeliverableStatusFilter("");
    setDeliverableSearch("");
  };
  const selectProjectForWork = (pid: string) => {
    setSelectedProjectId(pid || null);
    setSelectedDeliverable(null);
  };

  const projectsIn = (wid: string) => projects.filter((p) => p.workspace_id === wid);
  const goalsIn = (pid: string) => goals.filter((g) => g.project_id === pid);
  const deliverablesIn = (pid: string) => deliverablesList.filter((d) => d.project_id === pid);
  const assignmentsIn = (pid: string) => {
    const goalIds = new Set(goalsIn(pid).map((g) => g.id));
    return assignments.filter((a) => goalIds.has(a.goal_id));
  };
  const agentLabel = (slug: string) => {
    const a = agents.find((x) => x.name === slug);
    return a ? a.display_name || humanize(a.name) : humanize(slug);
  };
  const agentArchetype = (slug: string) => agents.find((x) => x.name === slug)?.archetype || "";
  const titleOfGoal = (gid: string) => goals.find((g) => g.id === gid)?.title || gid;
  const workspaceName = (wid: string) => workspaces.find((w) => w.id === wid)?.name || "Unknown workspace";
  const openGoals = goals.filter((g) => g.status !== "done" && g.status !== "cancelled");
  const recentProjects = [...projects]
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
    .slice(0, 5);

  // Work view: scope records to the selected project, then apply per-section filters.
  const workGoals = selectedProjectId ? goalsIn(selectedProjectId) : [];
  const workAssignments = selectedProjectId ? assignmentsIn(selectedProjectId) : [];
  const workDeliverables = selectedProjectId ? deliverablesIn(selectedProjectId) : [];

  const filteredGoals = workGoals.filter(
    (g) =>
      (!goalStatusFilter || g.status === goalStatusFilter) &&
      (!goalSearch || (g.title || "").toLowerCase().includes(goalSearch.trim().toLowerCase()))
  );
  const goalStatusOptions = Array.from(new Set(workGoals.map((g) => g.status).filter(Boolean)));

  const filteredAssignments = workAssignments.filter(
    (a) =>
      (!assignmentAgentFilter || a.agent_id === assignmentAgentFilter) &&
      (!assignmentSearch || (titleOfGoal(a.goal_id) || "").toLowerCase().includes(assignmentSearch.trim().toLowerCase()))
  );
  const assignmentAgentOptions = Array.from(new Set(workAssignments.map((a) => a.agent_id)));

  const filteredDeliverables = workDeliverables.filter(
    (d) =>
      (!deliverableStatusFilter || (d.latest_status || "") === deliverableStatusFilter) &&
      (!deliverableSearch || (d.title || "").toLowerCase().includes(deliverableSearch.trim().toLowerCase()))
  );
  const deliverableStatusOptions = Array.from(
    new Set(workDeliverables.map((d) => d.latest_status).filter(Boolean))
  );

  const status: "checking" | "online" | "offline" =
    health === "offline" ? "offline" : health === "checking..." ? "checking" : "online";

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand__logo">
            <Icon name="bot" size={22} />
          </div>
          <div>
            <h1 className="brand__title">Personal AI Team</h1>
            <p className="brand__tagline">Local multi-agent workspace</p>
          </div>
        </div>
        <div className="status">
          <span className={`status__dot status__dot--${status}`} />
          <span className="status__label">
            {status === "checking" ? "Connecting" : status === "online" ? "Backend online" : "Offline"}
          </span>
          <span className="status__chip">local · Ollama</span>
        </div>
      </header>

      {offline && (
        <div className="banner">
          You&apos;re offline — read-only mode. Writes are disabled until the connection returns.
        </div>
      )}

      <nav className="nav" aria-label="Sections">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={`nav__btn${tab === n.id ? " nav__btn--active" : ""}`}
            onClick={() => setTab(n.id)}
          >
            <Icon name={n.icon} />
            <span className="nav__label">{n.id}</span>
          </button>
        ))}
      </nav>

      <main className="content">
        {tab === "overview" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Overview</h2>
                <p className="panel__sub">A summary of your AI team workspace and activity.</p>
              </div>
            </div>

            <div className="stats">
              <Stat icon="grid" label="Workspaces" value={workspaces.length} />
              <Stat icon="briefcase" label="Projects" value={projects.length} />
              <Stat icon="target" label="Open goals" value={openGoals.length} />
              <Stat icon="checklist" label="Assignments" value={assignments.length} />
              <Stat icon="file" label="Deliverables" value={deliverablesList.length} />
            </div>

            {workspaces.length === 0 ? (
              <Empty text="No workspaces yet. Open the Workspace section to create your first workspace and start organizing projects." />
            ) : (
              <div className="overview-grid">
                <div className="overview-col">
                  <h3 className="section-title">Recent projects</h3>
                  {recentProjects.length === 0 ? (
                    <Empty text="No projects yet — create one inside a workspace." />
                  ) : (
                    <ul className="list">
                      {recentProjects.map((p) => (
                        <li key={p.id} className="list__item">
                          <span className="list__icon"><Icon name="briefcase" size={16} /></span>
                          <span className="list__name">{p.name}</span>
                          <span className="badge badge--faint">{workspaceName(p.workspace_id)}</span>
                          <span className={`badge badge--${p.status || "neutral"}`}>{p.status}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="overview-col">
                  <h3 className="section-title">Open goals</h3>
                  {openGoals.length === 0 ? (
                    <Empty text="No open goals yet." />
                  ) : (
                    <ul className="list">
                      {openGoals.map((g) => (
                        <li key={g.id} className="list__item">
                          <span className="list__icon"><Icon name="target" size={16} /></span>
                          <span className="list__name">{g.title}</span>
                          <span className={`badge badge--${g.status || "open"}`}>{g.status}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </section>
        )}

        {tab === "workspace" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Workspaces</h2>
                <p className="panel__sub">Working environments, each containing projects and their work.</p>
              </div>
            </div>

            {(selectedWorkspaceId || selectedProjectId) && (
              <nav className="crumb" aria-label="Breadcrumb">
                <button
                  className="crumb__link"
                  onClick={() => {
                    setSelectedWorkspaceId(null);
                    setSelectedProjectId(null);
                  }}
                >
                  All workspaces
                </button>
                {selectedWorkspaceId && (
                  <>
                    <span className="crumb__sep">/</span>
                    <button className="crumb__link" onClick={() => setSelectedProjectId(null)}>
                      {workspaces.find((w) => w.id === selectedWorkspaceId)?.name || "Workspace"}
                    </button>
                  </>
                )}
                {selectedProjectId && (
                  <>
                    <span className="crumb__sep">/</span>
                    <span className="crumb__current">
                      {projects.find((p) => p.id === selectedProjectId)?.name || "Project"}
                    </span>
                  </>
                )}
              </nav>
            )}

            <div className="inline-form">
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Workspace name"
                disabled={offline}
              />
              <button className="btn btn--primary" onClick={createWorkspace} disabled={offline || !name.trim()}>
                Create
              </button>
            </div>

            {!selectedWorkspaceId &&
              (workspaces.length === 0 ? (
                <Empty text="No workspaces yet — create one above to get started." />
              ) : (
                <ul className="list">
                  {workspaces.map((w) => (
                    <li
                      key={w.id}
                      className="list__item list__item--clickable"
                      onClick={() => {
                        setSelectedWorkspaceId(w.id);
                        setSelectedProjectId(null);
                      }}
                    >
                      <span className="list__icon"><Icon name="grid" size={16} /></span>
                      <span className="list__name">{w.name}</span>
                      <span className="badge badge--neutral">{projectsIn(w.id).length} projects</span>
                    </li>
                  ))}
                </ul>
              ))}

            {selectedWorkspaceId && !selectedProjectId && (
              <div className="subsection">
                <div className="subsection__head">
                  <h3 className="section-title">Projects</h3>
                  <button className="btn btn--primary" onClick={createProject} disabled={offline}>
                    Create Project
                  </button>
                </div>
                {projectsIn(selectedWorkspaceId).length === 0 ? (
                  <Empty text="No projects in this workspace yet — create one to start tracking goals and work." />
                ) : (
                  <ul className="list">
                    {projectsIn(selectedWorkspaceId).map((p) => (
                      <li
                        key={p.id}
                        className="list__item list__item--clickable"
                        onClick={() => setSelectedProjectId(p.id)}
                      >
                        <span className="list__icon"><Icon name="briefcase" size={16} /></span>
                        <span className="list__name">{p.name}</span>
                        <span className="badge badge--neutral">{goalsIn(p.id).length} goals</span>
                        <span className={`badge badge--${p.status || "neutral"}`}>{p.status}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {selectedProjectId &&
              (() => {
                const p = projects.find((x) => x.id === selectedProjectId);
                const pGoals = goalsIn(selectedProjectId);
                const pAssignments = assignmentsIn(selectedProjectId);
                const pDeliverables = deliverablesIn(selectedProjectId);
                return (
                  <div className="project-detail">
                    <div className="project-detail__head">
                      <div>
                        <h3 className="section-title">{p?.name || "Project"}</h3>
                        <p className="panel__sub">
                          {pGoals.length} goals · {pAssignments.length} assignments · {pDeliverables.length} deliverables
                        </p>
                      </div>
                      <span className={`badge badge--${p?.status || "neutral"}`}>{p?.status || "—"}</span>
                    </div>

                    <h4 className="subsection-title">Goals</h4>
                    {pGoals.length === 0 ? (
                      <Empty text="No goals for this project yet." />
                    ) : (
                      <ul className="list">
                        {pGoals.map((g) => (
                          <li key={g.id} className="list__item">
                            <span className="list__icon"><Icon name="target" size={16} /></span>
                            <span className="list__name">{g.title}</span>
                            <span className={`badge badge--${g.status || "open"}`}>{g.status}</span>
                            <span className="badge badge--neutral">p{g.priority}</span>
                          </li>
                        ))}
                      </ul>
                    )}

                    <h4 className="subsection-title">Assignments</h4>
                    {pAssignments.length === 0 ? (
                      <Empty text="No agents assigned to this project's goals yet." />
                    ) : (
                      <ul className="list">
                        {pAssignments.map((a) => (
                          <li key={a.id} className="list__item">
                            <span className="list__icon"><Icon name="checklist" size={16} /></span>
                            <span className="list__name">{agentLabel(a.agent_id)}</span>
                            <span className="badge badge--faint">{titleOfGoal(a.goal_id)}</span>
                            <span className={`badge badge--${a.status || "queued"}`}>{a.status || "queued"}</span>
                          </li>
                        ))}
                      </ul>
                    )}

                    <h4 className="subsection-title">Deliverables</h4>
                    {pDeliverables.length === 0 ? (
                      <Empty text="No deliverables produced for this project yet." />
                    ) : (
                      <ul className="list">
                        {pDeliverables.map((d) => (
                          <li key={d.id} className="list__item">
                            <span className="list__icon"><Icon name="file" size={16} /></span>
                            <span className="list__name">{d.title}</span>
                            <span className="badge badge--faint">#{d.id.slice(0, 6)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })()}
          </section>
        )}

        {tab === "work" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Work</h2>
                <p className="panel__sub">Goals, assignments, and deliverables scoped to a project.</p>
              </div>
            </div>

            <div className="work-selector" aria-label="Project selector">
              <select
                className="select"
                value={selectedWorkspaceId || ""}
                onChange={(e) => selectWorkspaceForWork(e.target.value)}
                disabled={offline}
                aria-label="Workspace"
              >
                <option value="">Select a workspace…</option>
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
              <select
                className="select"
                value={selectedProjectId || ""}
                onChange={(e) => selectProjectForWork(e.target.value)}
                disabled={offline || !selectedWorkspaceId}
                aria-label="Project"
              >
                <option value="">Select a project…</option>
                {projectsIn(selectedWorkspaceId || "").map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            {!selectedProjectId ? (
              <Empty text="Select a workspace and project to see its goals, assignments, and deliverables." />
            ) : (
              <>
                <div className="subsection">
                  <div className="subsection__head">
                    <h3 className="subsection-title">Goals</h3>
                    <button className="btn btn--primary" onClick={createGoal} disabled={offline}>
                      Create Goal
                    </button>
                  </div>
                  <div className="work-toolbar">
                    <select className="select select--small" value={goalStatusFilter} onChange={(e) => setGoalStatusFilter(e.target.value)} aria-label="Goal status filter">
                      <option value="">All statuses</option>
                      {goalStatusOptions.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                    <input className="input work-search" value={goalSearch} onChange={(e) => setGoalSearch(e.target.value)} placeholder="Search goals…" />
                  </div>
                  {workGoals.length === 0 ? (
                    <Empty text="No goals for this project yet — create one to start tracking progress." />
                  ) : filteredGoals.length === 0 ? (
                    <Empty text="No goals match your filters or search." />
                  ) : (
                    <ul className="list">
                      {filteredGoals.map((g) => (
                        <li key={g.id} className="list__item">
                          <span className="list__icon"><Icon name="target" size={16} /></span>
                          <span className="list__name">{g.title}</span>
                          <span className={`badge badge--${g.status || "open"}`}>{g.status || "open"}</span>
                          <span className="badge badge--neutral">p{g.priority}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="subsection">
                  <div className="subsection__head">
                    <h3 className="subsection-title">Assignments</h3>
                  </div>
                  <div className="work-toolbar">
                    <select className="select select--small" value={assignmentAgentFilter} onChange={(e) => setAssignmentAgentFilter(e.target.value)} aria-label="Assignment agent filter">
                      <option value="">All agents</option>
                      {assignmentAgentOptions.map((slug) => (
                        <option key={slug} value={slug}>{agentLabel(slug)}</option>
                      ))}
                    </select>
                    <input className="input work-search" value={assignmentSearch} onChange={(e) => setAssignmentSearch(e.target.value)} placeholder="Search by goal…" />
                  </div>
                  {workAssignments.length === 0 ? (
                    <Empty text="No agents assigned to this project's goals yet." />
                  ) : filteredAssignments.length === 0 ? (
                    <Empty text="No assignments match your filters or search." />
                  ) : (
                    <ul className="list">
                      {filteredAssignments.map((a) => (
                        <li key={a.id} className="list__item">
                          <span className="list__icon"><Icon name="checklist" size={16} /></span>
                          <span className="list__name">{agentLabel(a.agent_id)}</span>
                          {agentArchetype(a.agent_id) && <span className="badge badge--faint">{agentArchetype(a.agent_id)}</span>}
                          <span className="badge badge--faint">{titleOfGoal(a.goal_id)}</span>
                          <span className={`badge badge--${a.status || "queued"}`}>{a.status || "queued"}</span>
                          <span className="badge badge--neutral">p{a.priority}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="subsection">
                  <div className="subsection__head">
                    <h3 className="subsection-title">Deliverables</h3>
                    <button className="btn btn--primary" onClick={createDeliverable} disabled={offline}>
                      Create Deliverable
                    </button>
                  </div>
                  <div className="work-toolbar">
                    <select className="select select--small" value={deliverableStatusFilter} onChange={(e) => setDeliverableStatusFilter(e.target.value)} aria-label="Deliverable status filter">
                      <option value="">All statuses</option>
                      {deliverableStatusOptions.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                    <input className="input work-search" value={deliverableSearch} onChange={(e) => setDeliverableSearch(e.target.value)} placeholder="Search deliverables…" />
                  </div>
                  {workDeliverables.length === 0 ? (
                    <Empty text="No deliverables produced for this project yet." />
                  ) : filteredDeliverables.length === 0 ? (
                    <Empty text="No deliverables match your filters or search." />
                  ) : (
                    <ul className="list">
                      {filteredDeliverables.map((d) => (
                        <li
                          key={d.id}
                          className={`list__item list__item--clickable${selectedDeliverable === d.id ? " list__item--selected" : ""}`}
                          onClick={() => loadVersions(d.id)}
                        >
                          <span className="list__icon"><Icon name="file" size={16} /></span>
                          <span className="list__name">{d.title}</span>
                          <span className={`badge ${d.latest_status ? `badge--${d.latest_status}` : "badge--neutral"}`}>
                            {d.latest_status || "no versions"}
                          </span>
                          <span className="badge badge--faint">#{d.id.slice(0, 6)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {selectedDeliverable && (
                  <div className="versions">
                    <h3 className="versions__title">Versions</h3>
                    {versions.length === 0 ? (
                      <Empty text="No versions yet." />
                    ) : (
                      <ul className="versions__list">
                        {versions.map((v) => (
                          <li key={v.id} className="version">
                            <div className="version__meta">
                              <span className={`badge badge--${v.status || "neutral"}`}>v{v.version}</span>
                              <span className={`badge badge--${v.status || "neutral"}`}>{v.status}</span>
                            </div>
                            <div className="version__content">{v.content}</div>
                            {!offline && v.status !== "approved" && (
                              <div className="version__actions">
                                <button className="btn btn--ghost" onClick={() => approveVersion(v.id)}>
                                  Approve
                                </button>
                                <button className="btn btn--danger-ghost" onClick={() => rejectVersion(v.id)}>
                                  Reject
                                </button>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    {versions.length >= 2 && (
                      <div className="diff" data-testid="diff">
                        <h4 className="diff__title">
                          Compare v1 vs v{versions[versions.length - 1].version}
                        </h4>
                        <pre className="diff__body">
                          {diffLines(versions[0].content, versions[versions.length - 1].content).changed.join("\n")}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        )}

        {tab === "episodes" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Episodes</h2>
                <p className="panel__sub">Agent execution history — what ran, its status, and its progress.</p>
              </div>
            </div>
            {episodes.length === 0 ? (
              <Empty text="No agent runs recorded yet. Episodes appear here once an agent executes an instrumented run with progress checkpoints." />
            ) : (
              <ul className="list">
                {episodes.map((e) => (
                  <li
                    key={e.id}
                    className={`list__item list__item--clickable${selectedEpisode === e.id ? " list__item--selected" : ""}`}
                    onClick={() => loadEpisode(e.id)}
                  >
                    <span className="list__icon">
                      <Icon name="activity" size={16} />
                    </span>
                    <span className="list__name">{agentLabel(e.agent_id)}</span>
                    <span className={`badge badge--${e.status || "neutral"}`}>{e.status}</span>
                    <span className="badge badge--faint">{Math.round((e.progress || 0) * 100)}%</span>
                    <span className="badge badge--faint">{formatStamp(e.created_at)}</span>
                    {!offline && e.status === "running" && (
                      <span className="list__actions">
                        <button
                          className="btn btn--ghost"
                          onClick={(ev) => { ev.stopPropagation(); cancelEpisode(e.id); }}
                        >
                          Cancel
                        </button>
                        <button
                          className="btn btn--ghost"
                          onClick={(ev) => { ev.stopPropagation(); resumeEpisode(e.id); }}
                        >
                          Resume
                        </button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {selectedEpisode && (
              <div className="versions">
                <h3 className="versions__title">Episode detail</h3>
                {episodeDetail ? (
                  <>
                    <div className="episode-meta">
                      <span className={`badge badge--${episodeDetail.status || "neutral"}`}>{episodeDetail.status}</span>
                      <span className="badge badge--faint">{Math.round((episodeDetail.progress || 0) * 100)}% progress</span>
                      {episodeDetail.created_at && (
                        <span className="badge badge--faint">started {formatStamp(episodeDetail.created_at)}</span>
                      )}
                    </div>
                    {episodeEvents.length === 0 ? (
                      <Empty text="No events recorded for this episode yet." />
                    ) : (
                      <ul className="list">
                        {episodeEvents.map((ev, i) => (
                          <li key={i} className="list__item">
                            <span className="list__icon">
                              <Icon name="activity" size={16} />
                            </span>
                            <span className="list__name">{ev.status}</span>
                            {ev.detail && <span className="badge badge--faint">{ev.detail}</span>}
                            <span className="badge badge--faint">{formatStamp(ev.created_at)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <Empty text="Loading episode…" />
                )}
              </div>
            )}
          </section>
        )}

        {tab === "agents" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Agents</h2>
                <p className="panel__sub">Select an agent and give it a task.</p>
              </div>
            </div>

            <div className="agents-grid">
              {agents.map((a) => {
                return (
                  <button
                    key={a.name}
                    className={`agent-card${selectedAgent === a.name ? " agent-card--selected" : ""}`}
                    aria-label={a.name}
                    onClick={() => selectAgent(a.name)}
                  >
                    <span className="agent-card__avatar">
                      <Icon name="bot" size={18} />
                    </span>
                    <span className="agent-card__name">{a.display_name || humanize(a.name)}</span>
                    <span className="agent-card__role">{a.archetype || a.role}</span>
                    {a.archetype && a.role && a.role !== a.archetype && (
                      <span className="agent-card__subrole">{a.role}</span>
                    )}
                    {a.responsibilities && <span className="agent-card__desc">{a.responsibilities}</span>}
                  </button>
                );
              })}
              {agents.length === 0 && <div className="agents-grid__empty">No agents available.</div>}
            </div>

            {!selectedAgent && agents.length > 0 && (
              <div className="empty">Select an agent to begin.</div>
            )}

            {selectedAgent &&
              (() => {
                const a = agents.find((x) => x.name === selectedAgent);
                const agentAssignments = assignments.filter((x) => x.agent_id === selectedAgent);
                return (
                  <div className="agent-detail" data-testid="agent-detail">
                    <div className="agent-detail__head">
                      <span className="agent-detail__name">{a?.display_name || humanize(selectedAgent)}</span>
                      <span className="agent-detail__archetype">{a?.archetype || a?.role || ""}</span>
                      {a?.model && <span className="badge badge--faint">model · {a.model}</span>}
                    </div>
                    {a?.responsibilities && <p className="agent-detail__resp">{a.responsibilities}</p>}
                    {a?.capabilities?.length > 0 && (
                      <div className="agent-detail__section">
                        <span className="result__heading">Capabilities</span>
                        <ul className="chips">
                          {a.capabilities.map((c: string) => (
                            <li key={c} className="chip">{c}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {a?.tools?.length > 0 && (
                      <div className="agent-detail__section">
                        <span className="result__heading">Tools</span>
                        <ul className="chips">
                          {a.tools.map((t: string) => (
                            <li key={t} className="chip">{t}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div className="agent-detail__section">
                      <span className="result__heading">Assigned work</span>
                      {agentAssignments.length === 0 ? (
                        <Empty text="No goals currently assigned to this agent." />
                      ) : (
                        <ul className="list">
                          {agentAssignments.map((asg) => (
                            <li key={asg.id} className="list__item">
                              <span className="list__icon"><Icon name="target" size={16} /></span>
                              <span className="list__name">{titleOfGoal(asg.goal_id)}</span>
                              <span className={`badge badge--${asg.status || "queued"}`}>{asg.status || "queued"}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                );
              })()}

            {selectedAgent && (
              <div className="task-panel">
                <div className="task-panel__head">
                  <div>
                    <h3 className="task-panel__title">{agents.find((x) => x.name === selectedAgent)?.display_name || humanize(selectedAgent)}</h3>
                    <p className="task-panel__role">
                      {agents.find((x) => x.name === selectedAgent)?.archetype ||
                        agents.find((x) => x.name === selectedAgent)?.role}
                    </p>
                  </div>
                  <div className="task-panel__meta">
                    <span className="context-badge">
                      Context: {contextCounts[selectedAgent] ?? 0} messages
                    </span>
                    {threadIds[selectedAgent] && (
                      <button className="btn btn--ghost" onClick={newConversation}>
                        New conversation
                      </button>
                    )}
                  </div>
                </div>

                <textarea
                  className="task-input"
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      runAgent();
                    }
                  }}
                  placeholder="Give your agent a task…"
                  rows={3}
                  disabled={offline}
                />
                <div className="task-panel__actions">
                  <button
                    className="btn btn--primary btn--run"
                    onClick={runAgent}
                    disabled={offline || agentRunning || !task.trim()}
                  >
                    {agentRunning ? (
                      <>
                        <span className="spinner" aria-hidden="true" />
                        Running
                      </>
                    ) : (
                      "Run Agent"
                    )}
                  </button>
                  {agentRunning && (
                    <span className="task-panel__status">Generating response locally…</span>
                  )}
                </div>

                {agentError && <p className="error">Error: {agentError}</p>}
                {agentResult?.history_warning && (
                  <p className="warning">Warning: {agentResult.history_warning}</p>
                )}

                {agentResult && (
                  <div className="result">
                    <div className="result__meta">Processed at: {agentResult.location}</div>
                    <div className="result__body" data-testid="agent-reply">
                      <Markdown source={agentResult.reply} />
                    </div>
                    {agentResult.facts?.length > 0 &&
                      (() => {
                        const facts = uniqueBy(agentResult.facts, (f: any) => `${f.key ?? ""}|${f.value ?? ""}`);
                        return facts.length > 0 ? (
                          <div className="result__section">
                            <span className="result__heading">Known facts</span>
                            <ul className="chips">
                              {facts.map((f: any, i: number) => (
                                <li key={i} className="chip">
                                  {f.key || JSON.stringify(f)}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null;
                      })()}
                    {agentResult.proposals?.length > 0 && (
                      <div className="result__section">
                        <span className="result__heading">
                          Awaiting human approval: {agentResult.proposals.length} memory/goal proposal(s).
                        </span>
                      </div>
                    )}
                    {agentResult.tool_results?.length > 0 && (
                      <div className="result__section">
                        <span className="result__heading">Tool results</span>
                        <ul className="chips">
                          {agentResult.tool_results.map((t: any, i: number) => (
                            <li key={i} className="chip">
                              {t.tool}: {t.ok ? "ok" : `error: ${t.error}`}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
