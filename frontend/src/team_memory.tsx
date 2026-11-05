// Chunk 4 — Phase 9 §16: Persistent team memory, made inspectable & controllable.
//
// Human continuity across a conversation: the owner can view every approved
// durable memory, revoke one, approve/reject pending memory proposals, and
// propose a new durable note from a message. Nothing is stored automatically:
// every durable memory is created only through the human-only approve endpoint.
import { useCallback, useEffect, useState } from "react";
import { API } from "./coordination";

function errMsg(e: unknown, fallback: string): string {
  if (e && typeof e === "object" && "message" in e) {
    const m = (e as any).message;
    if (typeof m === "string") return m;
    if (typeof m === "object" && m && typeof (m as any).detail === "string") return (m as any).detail;
  }
  return fallback;
}

interface MemoryItem {
  id: string;
  key: string;
  value: string;
  source?: string;
  confidence?: number;
  created_at?: string;
}
interface MemoryProposal {
  id: string;
  key: string;
  value: string;
  agent_id?: string;
  source?: string;
  confidence?: number;
  created_at?: string;
}

export function TeamMemory({ agentDisplay }: { agentDisplay?: (slug?: string) => string }) {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [proposals, setProposals] = useState<MemoryProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [noteTitle, setNoteTitle] = useState("");
  const [noteValue, setNoteValue] = useState("");
  const [noteAgent, setNoteAgent] = useState("workspace_architect");
  const [noteMsg, setNoteMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [p, q] = await Promise.all([
        fetch(`${API}/memory/profile`),
        fetch(`${API}/memory/proposals?status=proposed`),
      ]);
      const pd = await p.json().catch(() => ({}));
      const qd = await q.json().catch(() => ({}));
      if (!p.ok || !q.ok) throw new Error("Could not load team memory.");
      setItems((pd.items || []) as MemoryItem[]);
      setProposals((qd.proposals || []) as MemoryProposal[]);
    } catch (e) {
      setError(errMsg(e, "Could not load team memory."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const label = (slug?: string) =>
    agentDisplay ? agentDisplay(slug) : (slug ? slug.replace(/_/g, " ") : "agent");
  const stamp = (iso?: string) => {
    if (!iso) return "";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  };

  async function act(url: string, method: string, body: unknown) {
    setBusy(url);
    setError("");
    try {
      const r = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError((b as any).detail || `Request failed (${r.status}).`);
        return false;
      }
      await load();
      return true;
    } catch (e) {
      setError(errMsg(e, "Request failed. Please try again."));
      return false;
    } finally {
      setBusy("");
    }
  }

  async function propose() {
    const title = noteTitle.trim();
    const value = noteValue.trim();
    if (!title) return setNoteMsg("Give this memory a short title.");
    if (!value) return setNoteMsg("Describe what to remember.");
    setNoteMsg("");
    setBusy("propose");
    setError("");
    try {
      const r = await fetch(`${API}/memory/proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: noteAgent, kind: "profile", key: title, value, source: "conversation", confidence: 0.8 }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError((b as any).detail || `Could not propose the memory (${r.status}).`);
        return;
      }
      setNoteMsg("Memory proposed — you must approve it below before it is stored.");
      setNoteTitle("");
      setNoteValue("");
      await load();
    } catch (e) {
      setError(errMsg(e, "Could not propose the memory."));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="coord-block team-memory" data-testid="team-memory">
      <div className="panel__head">
        <div>
          <h3 className="section-title">Team memory</h3>
          <p className="panel__sub">
            Approved memories you can rely on across conversations. Nothing is remembered automatically.
          </p>
        </div>
        <button className="btn btn--sm btn--ghost" data-testid="tm-refresh" onClick={load}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error" role="alert" data-testid="tm-error">{error}</p>}

      <div className="tm-propose" data-testid="tm-propose">
        <h5 className="section-title">Propose a durable memory</h5>
        <p className="muted">Captures a fact or preference you want the team to remember. Stored only after your approval.</p>
        <div className="work-toolbar" style={{ flexWrap: "wrap" }}>
          <select className="select select--small" value={noteAgent} onChange={(e) => setNoteAgent(e.target.value)} aria-label="Agent">
            <option value="workspace_architect">Workspace Architect</option>
            <option value="strategist">Strategist</option>
            <option value="researcher">Researcher</option>
            <option value="tutor">Tutor</option>
            <option value="editor">Editor</option>
            <option value="analyst">Analyst</option>
          </select>
          <input className="input input--sm" placeholder="Title (key)…" value={noteTitle} onChange={(e) => setNoteTitle(e.target.value)} aria-label="Memory title" data-testid="tm-title" />
          <input className="input input--sm" placeholder="What to remember…" value={noteValue} onChange={(e) => setNoteValue(e.target.value)} aria-label="Memory detail" data-testid="tm-value" />
          <button className="btn btn--sm btn--primary" onClick={propose} disabled={busy !== ""} data-testid="tm-propose-btn">
            {busy === "propose" ? "Proposing…" : "Propose for approval"}
          </button>
        </div>
        {noteMsg && <p className="success" role="status" data-testid="tm-note">{noteMsg}</p>}
      </div>

      <div className="tm-pending" data-testid="tm-pending">
        <h5 className="section-title">Pending memory proposals ({proposals.length})</h5>
        {proposals.length === 0 ? (
          <p className="muted">No pending memory proposals.</p>
        ) : (
          <ul className="list">
            {proposals.map((p) => (
              <li key={p.id} className="list__item tm-item" data-testid={`tm-proposal-${p.id}`}>
                <div className="tm-item__main">
                  <span className="tm-item__title">{p.key}</span>
                  <span className="muted tm-item__meta">{p.value} · by {label(p.agent_id)}</span>
                </div>
                <span className="coord-step__actions">
                  <button className="btn btn--sm btn--primary" data-testid={`tm-approve-${p.id}`}
                    disabled={busy !== ""} onClick={() => act(`${API}/memory/proposals/${encodeURIComponent(p.id)}/approve`, "POST", {})}>
                    {busy === `${API}/memory/proposals/${encodeURIComponent(p.id)}/approve` ? "Saving…" : "Approve"}
                  </button>
                  <button className="btn btn--sm btn--ghost" data-testid={`tm-reject-${p.id}`}
                    disabled={busy !== ""} onClick={() => act(`${API}/memory/proposals/${encodeURIComponent(p.id)}/reject`, "POST", {})}>
                    Reject
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="tm-approved" data-testid="tm-approved">
        <h5 className="section-title">Approved memories ({items.length})</h5>
        {items.length === 0 ? (
          <p className="muted">No approved memories yet.</p>
        ) : (
          <ul className="list">
            {items.map((it) => (
              <li key={it.id} className="list__item tm-item" data-testid={`tm-memory-${it.id}`}>
                <div className="tm-item__main">
                  <span className="tm-item__title">{it.key}</span>
                  <span className="muted tm-item__meta">{it.value}{it.created_at ? ` · ${stamp(it.created_at)}` : ""}</span>
                </div>
                <span className="coord-step__actions">
                  <button className="btn btn--sm btn--ghost" data-testid={`tm-revoke-${it.id}`}
                    disabled={busy !== ""} onClick={() => act(`${API}/memory/revoke/${encodeURIComponent(it.id)}`, "POST", {})}>
                    Revoke
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
