import { useEffect, useState } from "react";
import { diffLines } from "./diff";

const API = "http://127.0.0.1:8001";

type Tab = "workspaces" | "projects" | "goals" | "assignments" | "deliverables" | "episodes";

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

  useEffect(() => {
    fetch(`${API}/health`).then(r => r.json()).then(d => setHealth(JSON.stringify(d))).catch(() => { setHealth("offline"); setOffline(true); });
    refresh();
  }, []);

  const refresh = async () => {
    try {
      const w = await fetch(`${API}/workspaces`).then(r => r.json());
      setWorkspaces(w.items || []);
      const p = await fetch(`${API}/workspaces/projects`).then(r => r.json());
      setProjects(p.items || []);
      const g = await fetch(`${API}/workspaces/goals`).then(r => r.json());
      setGoals(g.items || []);
      const a = await fetch(`${API}/workspaces/assignments`).then(r => r.json());
      setAssignments(a.items || []);
      try {
        const e = await fetch(`${API}/episodes`).then(r => r.json());
        setEpisodes(e.items || []);
        const d = await fetch(`${API}/workspaces/deliverables`).then(r => r.json());
        setDeliverablesList(d.items || []);
      } catch {}
    } catch { setOffline(true); }
  };

  const createWorkspace = async () => {
    if (!name || offline) return;
    await fetch(`${API}/workspaces`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    setName(""); refresh();
  };

  const createProject = async () => {
    if (offline || workspaces.length === 0) return;
    await fetch(`${API}/workspaces/projects`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspace_id: workspaces[0].id, name: "New Project" }) });
    refresh();
  };

  const createGoal = async () => {
    if (offline || projects.length === 0) return;
    await fetch(`${API}/workspaces/goals`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projects[0].id, title: "New Goal", priority: 1 }) });
    refresh();
  };

  const createDeliverable = async () => {
    if (offline || projects.length === 0) return;
    const r = await fetch(`${API}/workspaces/deliverables`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projects[0].id, title: "New Deliverable" }) });
    const d = await r.json();
    if (d.id) {
      await fetch(`${API}/workspaces/deliverables/${d.id}/versions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: "v1 content" }) });
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
    await fetch(`${API}/workspaces/versions/${vid}/reject`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "requested revision" }) });
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

  return (
    <div style={{ padding: 24, fontFamily: "system-ui" }}>
      <h1>Personal AI Team</h1>
      <p>Backend: {health} {offline && "(offline - read only)"}</p>
      <nav style={{ marginBottom: 12 }}>
        {(["workspaces","projects","goals","assignments","deliverables","episodes"] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ marginRight: 8, fontWeight: tab===t?"bold":"normal" }}>{t}</button>
        ))}
      </nav>

      {tab === "workspaces" && (
        <div>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Workspace name" disabled={offline} />
          <button onClick={createWorkspace} disabled={offline}>Create</button>
          <ul>{workspaces.map(w => <li key={w.id}>{w.name}</li>)}</ul>
        </div>
      )}
      {tab === "projects" && (
        <div>
          <button onClick={createProject} disabled={offline}>Create Project</button>
          <ul>{projects.map(p => <li key={p.id}>{p.name} ({p.status})</li>)}</ul>
        </div>
      )}
      {tab === "goals" && (
        <div>
          <button onClick={createGoal} disabled={offline}>Create Goal</button>
          <ul>{goals.map(g => <li key={g.id}>{g.title} (p{g.priority})</li>)}</ul>
        </div>
      )}
      {tab === "assignments" && (
        <ul>{assignments.map(a => <li key={a.id}>{a.agent_id} (p{a.priority})</li>)}</ul>
      )}
      {tab === "deliverables" && (
        <div>
          <button onClick={createDeliverable} disabled={offline}>Create Deliverable</button>
          <ul>
            {deliverablesList.map(d => (
              <li key={d.id} style={{ cursor: "pointer" }} onClick={() => loadVersions(d.id)}>
                {d.title} <span style={{ color: "#888" }}>(#{d.id.slice(0,6)})</span>
              </li>
            ))}
          </ul>
          {selectedDeliverable && (
            <div>
              <h3>Versions</h3>
              <ul>
                {versions.map(v => (
                  <li key={v.id}>
                    v{v.version}: {v.content} [{v.status}]
                    {!offline && v.status !== "approved" && (
                      <>
                        <button onClick={() => approveVersion(v.id)}>Approve</button>
                        <button onClick={() => rejectVersion(v.id)}>Reject</button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
              {versions.length >= 2 && (
                <div data-testid="diff">
                  <h4>Compare v1 vs v{versions[versions.length - 1].version}</h4>
                  <pre>{diffLines(versions[0].content, versions[versions.length - 1].content).changed.join("\n")}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {tab === "episodes" && (
        <div>
          <ul>
            {episodes.map(e => (
              <li key={e.id}>
                {e.agent_id} ({e.status}, progress {e.progress})
                {!offline && e.status === "running" && (
                  <>
                    <button onClick={() => cancelEpisode(e.id)}>Cancel</button>
                    <button onClick={() => resumeEpisode(e.id)}>Resume</button>
                  </>
                )}
              </li>
            ))}
          </ul>
          {episodes.length === 0 && <p>No episodes.</p>}
        </div>
      )}
    </div>
  );
}