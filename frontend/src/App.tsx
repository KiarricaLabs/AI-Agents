import { useEffect, useState } from "react";

const API = "http://127.0.0.1:8000";

type Tab = "workspaces" | "projects" | "goals" | "deliverables" | "episodes";

export default function App() {
  const [tab, setTab] = useState<Tab>("workspaces");
  const [health, setHealth] = useState("checking...");
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [goals, setGoals] = useState<any[]>([]);

  const [name, setName] = useState("");

  useEffect(() => {
    fetch(`${API}/health`).then(r => r.json()).then(d => setHealth(JSON.stringify(d))).catch(() => setHealth("offline"));
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
    } catch {}
  };

  const createWorkspace = async () => {
    if (!name) return;
    await fetch(`${API}/workspaces`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    setName(""); refresh();
  };

  return (
    <div style={{ padding: 24, fontFamily: "system-ui" }}>
      <h1>Personal AI Team</h1>
      <p>Backend: {health}</p>
      <nav style={{ marginBottom: 12 }}>
        {(["workspaces","projects","goals","deliverables","episodes"] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ marginRight: 8, fontWeight: tab===t?"bold":"normal" }}>{t}</button>
        ))}
      </nav>

      {tab === "workspaces" && (
        <div>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Workspace name" />
          <button onClick={createWorkspace}>Create</button>
          <ul>{workspaces.map(w => <li key={w.id}>{w.name}</li>)}</ul>
        </div>
      )}
      {tab === "projects" && (
        <ul>{projects.map(p => <li key={p.id}>{p.name} ({p.status})</li>)}</ul>
      )}
      {tab === "goals" && (
        <ul>{goals.map(g => <li key={g.id}>{g.title} (p{g.priority})</li>)}</ul>
      )}
      {tab === "deliverables" && (
        <p>Deliverable management via API: POST /workspaces/deliverables</p>
      )}
      {tab === "episodes" && (
        <p>Episode progress via /memory and task endpoints.</p>
      )}
    </div>
  );
}