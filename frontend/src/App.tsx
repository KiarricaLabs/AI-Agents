import { useEffect, useState, type ReactNode } from "react";
import { diffLines } from "./diff";
import "./App.css";

const API = "http://127.0.0.1:8001";

type Tab =
  | "workspaces"
  | "projects"
  | "goals"
  | "assignments"
  | "deliverables"
  | "episodes"
  | "agents";

const NAV: { id: Tab; icon: string }[] = [
  { id: "workspaces", icon: "grid" },
  { id: "projects", icon: "briefcase" },
  { id: "goals", icon: "target" },
  { id: "assignments", icon: "checklist" },
  { id: "deliverables", icon: "file" },
  { id: "episodes", icon: "activity" },
  { id: "agents", icon: "bot" },
];

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const children: Record<string, ReactNode> = {
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

export default function App() {
  const [tab, setTab] = useState<Tab>("workspaces");
  const [health, setHealth] = useState("checking...");
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [goals, setGoals] = useState<any[]>([]);
  const [assignments, setAssignments] = useState<any[]>([]);
  const [versions, setVersions] = useState<any[]>([]);
  const [episodes, setEpisodes] = useState<any[]>([]);
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
    if (offline || !selectedAgent || !task.trim()) return;
    setAgentRunning(true);
    setAgentError("");
    setAgentResult(null);
    const payload: any = { task: task.trim() };
    try {
      const r = await fetch(`${API}/agents/${selectedAgent}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAgentError(body.detail || `request failed (${r.status})`);
      } else {
        setAgentResult(body);
      }
    } catch (e: any) {
      setAgentError(e?.message || "network error");
    } finally {
      setAgentRunning(false);
    }
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
    if (offline || workspaces.length === 0) return;
    await fetch(`${API}/workspaces/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: workspaces[0].id, name: "New Project" }),
    });
    refresh();
  };

  const createGoal = async () => {
    if (offline || projects.length === 0) return;
    await fetch(`${API}/workspaces/goals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projects[0].id, title: "New Goal", priority: 1 }),
    });
    refresh();
  };

  const createDeliverable = async () => {
    if (offline || projects.length === 0) return;
    const r = await fetch(`${API}/workspaces/deliverables`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projects[0].id, title: "New Deliverable" }),
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
        {tab === "workspaces" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Workspaces</h2>
                <p className="panel__sub">Isolated spaces for teams and projects.</p>
              </div>
            </div>
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
            {workspaces.length === 0 ? (
              <Empty text="No workspaces yet." />
            ) : (
              <ul className="list">
                {workspaces.map((w) => (
                  <li key={w.id} className="list__item">
                    <span className="list__icon">
                      <Icon name="grid" size={16} />
                    </span>
                    <span className="list__name">{w.name}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {tab === "projects" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Projects</h2>
                <p className="panel__sub">Track work within a workspace.</p>
              </div>
              <button className="btn btn--primary" onClick={createProject} disabled={offline || workspaces.length === 0}>
                Create Project
              </button>
            </div>
            {projects.length === 0 ? (
              <Empty text="No projects yet." />
            ) : (
              <ul className="list">
                {projects.map((p) => (
                  <li key={p.id} className="list__item">
                    <span className="list__icon">
                      <Icon name="briefcase" size={16} />
                    </span>
                    <span className="list__name">{p.name}</span>
                    <span className={`badge badge--${p.status || "neutral"}`}>{p.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {tab === "goals" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Goals</h2>
                <p className="panel__sub">Objectives for a project.</p>
              </div>
              <button className="btn btn--primary" onClick={createGoal} disabled={offline || projects.length === 0}>
                Create Goal
              </button>
            </div>
            {goals.length === 0 ? (
              <Empty text="No goals yet." />
            ) : (
              <ul className="list">
                {goals.map((g) => (
                  <li key={g.id} className="list__item">
                    <span className="list__icon">
                      <Icon name="target" size={16} />
                    </span>
                    <span className="list__name">{g.title}</span>
                    <span className="badge badge--neutral">p{g.priority}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {tab === "assignments" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Assignments</h2>
                <p className="panel__sub">Agent task allocations.</p>
              </div>
            </div>
            {assignments.length === 0 ? (
              <Empty text="No assignments yet." />
            ) : (
              <ul className="list">
                {assignments.map((a) => (
                  <li key={a.id} className="list__item">
                    <span className="list__icon">
                      <Icon name="checklist" size={16} />
                    </span>
                    <span className="list__name">{a.agent_id}</span>
                    <span className="badge badge--neutral">p{a.priority}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {tab === "deliverables" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Deliverables</h2>
                <p className="panel__sub">Versioned work with approval workflow.</p>
              </div>
              <button className="btn btn--primary" onClick={createDeliverable} disabled={offline || projects.length === 0}>
                Create Deliverable
              </button>
            </div>
            {deliverablesList.length === 0 ? (
              <Empty text="No deliverables yet." />
            ) : (
              <ul className="list">
                {deliverablesList.map((d) => (
                  <li
                    key={d.id}
                    className={`list__item list__item--clickable${selectedDeliverable === d.id ? " list__item--selected" : ""}`}
                    onClick={() => loadVersions(d.id)}
                  >
                    <span className="list__icon">
                      <Icon name="file" size={16} />
                    </span>
                    <span className="list__name">{d.title}</span>
                    <span className="badge badge--faint">#{d.id.slice(0, 6)}</span>
                  </li>
                ))}
              </ul>
            )}

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
          </section>
        )}

        {tab === "episodes" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Episodes</h2>
                <p className="panel__sub">Agent execution runs and progress.</p>
              </div>
            </div>
            {episodes.length === 0 ? (
              <Empty text="No episodes." />
            ) : (
              <ul className="list">
                {episodes.map((e) => (
                  <li key={e.id} className="list__item">
                    <span className="list__icon">
                      <Icon name="activity" size={16} />
                    </span>
                    <span className="list__name">{e.agent_id}</span>
                    <span className={`badge badge--${e.status || "neutral"}`}>{e.status}</span>
                    <span className="badge badge--faint">{Math.round((e.progress || 0) * 100)}%</span>
                    {!offline && e.status === "running" && (
                      <span className="list__actions">
                        <button className="btn btn--ghost" onClick={() => cancelEpisode(e.id)}>
                          Cancel
                        </button>
                        <button className="btn btn--ghost" onClick={() => resumeEpisode(e.id)}>
                          Resume
                        </button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
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
                const desc = [a.personality, a.capabilities?.length ? a.capabilities.join(", ") : ""]
                  .filter(Boolean)
                  .join(" · ");
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
                    <span className="agent-card__name">{humanize(a.name)}</span>
                    <span className="agent-card__role">{a.role}</span>
                    {desc && <span className="agent-card__desc">{desc}</span>}
                  </button>
                );
              })}
              {agents.length === 0 && <div className="agents-grid__empty">No agents available.</div>}
            </div>

            {!selectedAgent && agents.length > 0 && (
              <div className="empty">Select an agent to begin.</div>
            )}

            {selectedAgent && (
              <div className="task-panel">
                <div className="task-panel__head">
                  <div>
                    <h3 className="task-panel__title">{humanize(selectedAgent)}</h3>
                    <p className="task-panel__role">
                      {agents.find((x) => x.name === selectedAgent)?.role}
                    </p>
                  </div>
                </div>

                <textarea
                  className="task-input"
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  placeholder="Give your agent a task…"
                  rows={3}
                  disabled={offline || agentRunning}
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

                {agentResult && (
                  <div className="result">
                    <div className="result__meta">Processed at: {agentResult.location}</div>
                    <div className="result__body" data-testid="agent-reply">
                      {agentResult.reply}
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
