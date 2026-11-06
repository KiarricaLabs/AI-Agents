// Phase 8 §15 — "Team status" command center.
//
// A read-only, owner-scoped consolidation of what the AI team is doing right
// now: live agent activity from the durable progress ledger (/team/progress)
// and any agent-to-agent coordination loops that got blocked
// (/team/comm/blocked). It never dispatches, starts, or approves anything — it
// only reports state back to the human so blockers and in-flight work are
// visible in one place.
import { useCallback, useEffect, useState } from "react";
import { API, humanizeAgent } from "./coordination";

interface AgentState {
  agent: string;
  status: string;
  detail?: string;
}

export function TeamStatus() {
  const [progress, setProgress] = useState<any[]>([]);
  const [blocked, setBlocked] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [p, b] = await Promise.all([
        fetch(`${API}/team/progress`),
        fetch(`${API}/team/comm/blocked`),
      ]);
      const pd = await p.json().catch(() => ({}));
      const bd = await b.json().catch(() => ({}));
      setProgress(pd.items || []);
      setBlocked(bd.items || []);
    } catch {
      setError("Could not load team status.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // The ledger is ordered most-recent first, so the first entry we see for each
  // agent is its latest status.
  const seen = new Set<string>();
  const agents: AgentState[] = [];
  for (const it of progress) {
    const a: string = it.agent_id;
    if (!seen.has(a)) {
      seen.add(a);
      agents.push({ agent: a, status: it.status, detail: it.detail });
    }
  }

  return (
    <section className="coord-block team-status" data-testid="team-status">
      <div className="panel__head">
        <div>
          <h3 className="section-title">Team status</h3>
          <p className="panel__sub">What the team is doing and what needs you.</p>
        </div>
        <button className="btn btn--sm btn--ghost" data-testid="team-status-refresh" onClick={load}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="team-status__agents">
        <span className="team-status__kicker">Agents</span>
        {agents.length === 0 ? (
          <span className="muted" data-testid="team-status-agents-empty">No agent activity recorded yet.</span>
        ) : (
          agents.map((a) => (
            <span key={a.agent} className={`badge badge--${a.status}`}
              data-testid={`team-status-agent-${a.agent}`} title={a.detail || ""}>
              {humanizeAgent(a.agent)} · {a.status}
            </span>
          ))
        )}
      </div>

      <div className="team-status__cols">
        <div className="team-status__col">
          <span className="team-status__kicker">Recent activity ({progress.length})</span>
          {progress.length === 0 ? (
            <p className="muted" data-testid="team-status-progress-empty">No activity recorded yet.</p>
          ) : (
            <ul className="team-status__list">
              {progress.slice(0, 8).map((it, i) => (
                <li key={it.id || i} data-testid={`team-status-progress-${i}`}>
                  <span className="team-status__agent">{humanizeAgent(it.agent_id)}</span>
                  <span className={`badge badge--${it.status}`}>{it.status}</span>
                  {it.detail && <span className="team-status__detail"> — {String(it.detail).slice(0, 120)}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="team-status__col">
          <span className="team-status__kicker">Blocked coordination ({blocked.length})</span>
          {blocked.length === 0 ? (
            <p className="muted" data-testid="team-status-blocked-empty">No blocked coordination requests.</p>
          ) : (
            <ul className="team-status__list">
              {blocked.map((it, i) => (
                <li key={it.id || i} data-testid={`team-status-blocked-${i}`}>
                  <span className="badge badge--blocked">blocked</span>
                  <span className="team-status__agent">{humanizeAgent(it.from_agent)} → {humanizeAgent(it.to_agent)}</span>
                  {it.content && <span className="team-status__detail"> — {String(it.content).slice(0, 120)}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
