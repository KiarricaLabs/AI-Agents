// AI Team 2 — the shared group chat (Home hero).
//
// One big conversation with every agent: the human sends a message to the team,
// and the backend's TeamRouter dispatches it SEQUENTIALLY to the relevant
// agent(s), returning one labeled bubble per agent. Any relevant agent may
// reply. The composer also supports designating a task or requesting a proposal
// (same shared thread, human-initiated). Nothing runs automatically and no
// agent is dispatched after a single send beyond the existing routing.
import { useCallback, useEffect, useRef, useState } from "react";
import { API, humanizeAgent } from "./coordination";
import { Markdown } from "./markdown";

const THREAD_KEY = "ai-team-shared-thread";

// Agent photos (fall back to a colored initial when no photo is mapped).
import tutorUrl from "./assets/agents/tutor.jpg";
import strategistUrl from "./assets/agents/strategist.jpg";
import execAssistantUrl from "./assets/agents/executive_assistant.jpg";
import workspaceArchitectUrl from "./assets/agents/workspace_architect.jpg";
import soundboardUrl from "./assets/agents/soundboard.jpg";
import communicationsUrl from "./assets/agents/communications.jpg";

const AVATAR_IMG: Record<string, string> = {
  tutor: tutorUrl,
  strategist: strategistUrl,
  executive_assistant: execAssistantUrl,
  workspace_architect: workspaceArchitectUrl,
  soundboard: soundboardUrl,
  communications: communicationsUrl,
};

const AGENT_COLORS = ["#d97706", "#7c3aed", "#059669", "#dc2626", "#2563eb", "#0891b2", "#db2777"];

function agentInitial(slug?: string): string {
  const name = humanizeAgent(slug);
  const word = (name || "team").split(/[\s-]+/).filter(Boolean)[0] || "?";
  return (word[0] || "?").toUpperCase();
}

function agentColor(slug?: string): string {
  const s = (slug || "team").toLowerCase();
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AGENT_COLORS[h % AGENT_COLORS.length];
}

export function AgentAvatar({ slug, size = 28 }: { slug?: string; size?: number }) {
  const src = slug ? AVATAR_IMG[slug.toLowerCase()] : undefined;
  if (src) {
    return (
      <img
        className="agent-avatar agent-avatar--img"
        data-testid={`avatar-${slug || "team"}`}
        aria-hidden="true"
        src={src}
        alt=""
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <span
      className="agent-avatar"
      data-testid={`avatar-${slug || "team"}`}
      aria-hidden="true"
      style={{ width: size, height: size, background: agentColor(slug), fontSize: Math.round(size * 0.48) }}
    >
      {agentInitial(slug)}
    </span>
  );
}

interface Msg {
  role: "user" | "assistant";
  agent?: string;
  content: string;
  created_at?: string;
}

type Mode = "team" | "task" | "propose";

const MODE_META: Record<Mode, { label: string; hint: string; prefix: string }> = {
  team: { label: "Ask the team", hint: "Any relevant agent replies.", prefix: "" },
  task: { label: "Designate a task", hint: "The message is treated as an assignment for the most relevant agents.", prefix: "[Designated task] " },
  propose: { label: "Request a proposal", hint: "Ask the team to draft a proposal for your approval.", prefix: "[Proposal request] " },
};

function stamp(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
}

export function TeamChat() {
  const [threadId, setThreadId] = useState<string>(() => (typeof localStorage !== "undefined" ? localStorage.getItem(THREAD_KEY) || "" : ""));
  const [booting, setBooting] = useState(true);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<Mode>("team");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  // --- Request-a-proposal: extract an editable draft, choose a parent, file it ---
  const [propKind, setPropKind] = useState("project");
  const [propDraft, setPropDraft] = useState<any | null>(null);
  const [propParent, setPropParent] = useState("");
  const [propParents, setPropParents] = useState<{ workspaces: any[]; projects: any[]; goals: any[] }>({ workspaces: [], projects: [], goals: [] });
  const [propBusy, setPropBusy] = useState(false);
  const [propMsg, setPropMsg] = useState("");
  // --- Phase 8 §15: durable team progress feed for this thread ---
  const [progress, setProgress] = useState<any[]>([]);
  // --- conversation sidebar ---
  const [conversations, setConversations] = useState<any[]>([]);
  const listRef = useRef<HTMLDivElement>(null);

  const ensureThread = useCallback(async () => {
    if (typeof localStorage !== "undefined" && localStorage.getItem(THREAD_KEY)) return;
    try {
      const r = await fetch(`${API}/team/threads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "Team chat", thread_type: "team" }),
      });
      const b = await r.json().catch(() => ({}));
      if (r.ok && b.thread_id) {
        if (typeof localStorage !== "undefined") localStorage.setItem(THREAD_KEY, b.thread_id);
        setThreadId(b.thread_id);
      }
    } catch { /* backend unavailable — chat remains read-only */ }
  }, []);

  const load = useCallback(async (tid: string) => {
    try {
      const r = await fetch(`${API}/memory/conversation?thread_id=${encodeURIComponent(tid)}`);
      const b = await r.json().catch(() => ({}));
      setMessages((b.items || []).map((m: any) => ({
        role: m.role === "user" ? "user" as const : "assistant" as const,
        content: m.content,
        created_at: m.created_at,
      })));
    } catch { /* offline */ }
    try {
      const pr = await fetch(`${API}/team/progress?thread_id=${encodeURIComponent(tid)}`);
      const pb = await pr.json().catch(() => ({}));
      setProgress(pb.items || []);
    } catch { /* offline */ }
  }, []);

  const loadConversations = useCallback(async () => {
    try {
      const r = await fetch(`${API}/memory/conversations`);
      const b = await r.json().catch(() => ({}));
      setConversations(b.items || []);
    } catch { /* offline */ }
  }, []);

  const openConv = (tid: string) => {
    setThreadId(tid);
    setMessages([]);
    setProgress([]);
    if (typeof localStorage !== "undefined") localStorage.setItem(THREAD_KEY, tid);
  };

  useEffect(() => {
    (async () => { await ensureThread(); setBooting(false); loadConversations(); })();
  }, [ensureThread, loadConversations]);

  useEffect(() => { if (threadId) load(threadId); }, [threadId, load]);

  useEffect(() => {
    const el = listRef.current;
    if (!el || typeof el.scrollTo !== "function") return; // jsdom lacks scrollTo
    try { el.scrollTo({ top: el.scrollHeight }); } catch { /* non-critical */ }
  }, [messages.length, booting]);

  const send = async () => {
    const text = draft.trim();
    if (!text || sending || booting) return;
    const full = mode === "team" ? text : `${MODE_META[mode].prefix}${text}`;
    setDraft("");
    setError("");
    setSending(true);
    setMessages((prev) => [...prev, { role: "user", content: full, created_at: new Date().toISOString() }]);
    try {
      const body: any = { message: full, thread_id: threadId || undefined };
      const r = await fetch(`${API}/team/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError((b as any).detail || `Could not reach the team (${r.status}).`);
        return;
      }
      const bubbles: Msg[] = (b.responses || []).map((x: any) => ({
        role: "assistant" as const,
        agent: x.agent,
        content: x.reply || "",
      })).filter((m: Msg) => m.content);
      setMessages((prev) => [...prev, ...bubbles]);
      if (threadId) {
        const pr = await fetch(`${API}/team/progress?thread_id=${encodeURIComponent(threadId)}`);
        const pb = await pr.json().catch(() => ({}));
        setProgress(pb.items || []);
      }
      if ((b.errors || []).length) {
        setError(`${b.errors.length} agent(s) couldn't respond just now.`);
      }
    } catch {
      setError("Could not reach the team. Please try again.");
    } finally {
      setSending(false);
    }
  };

  const loadParents = async () => {
    try {
      const [w, p, g] = await Promise.all([
        fetch(`${API}/workspaces`), fetch(`${API}/workspaces/projects`), fetch(`${API}/workspaces/goals`),
      ]);
      const wd = await w.json().catch(() => ({}));
      const pd = await p.json().catch(() => ({}));
      const gd = await g.json().catch(() => ({}));
      setPropParents({
        workspaces: wd.items || [],
        projects: pd.items || [],
        goals: gd.items || [],
      });
    } catch { /* offline */ }
  };

  const chooseKind = (kind: string) => {
    setPropKind(kind);
    setPropDraft(null);
    setPropParent("");
    setPropMsg("");
  };

  const extractProposal = async () => {
    const message = draft.trim();
    if (!message || propBusy) return;
    setPropBusy(true);
    setPropMsg("");
    try {
      const r = await fetch(`${API}/work/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: propKind, message, subject_agent: "workspace_architect" }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) { setPropMsg((b as any).detail || `Could not extract a draft (${r.status}).`); return; }
      setPropDraft(b.draft);
      setPropMsg("Draft ready — choose a parent and propose for approval.");
      await loadParents();
    } catch {
      setPropMsg("Could not extract a draft. Please try again.");
    } finally {
      setPropBusy(false);
    }
  };

  const proposeProposal = async () => {
    if (propBusy || !propDraft) return;
    let work_type = propKind;
    let payload: any = {};
    if (propKind === "project") {
      // Seamless path: with no workspace selected, create one (a container) on
      // this explicit human action, then attach the project proposal to it.
      if (propParent) {
        payload = { workspace_id: propParent, name: propDraft.title || "New project" };
      } else {
        const wsName = (propDraft.title || "New project").slice(0, 60) + " · workspace";
        const wsr = await fetch(`${API}/workspaces`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: wsName }),
        });
        const wsb = await wsr.json().catch(() => ({}));
        if (!wsr.ok || !wsb.id) {
          setPropMsg("Could not create a workspace to attach the project to. Please create one in Projects first.");
          return;
        }
        payload = { workspace_id: wsb.id, name: propDraft.title || "New project" };
      }
    } else if (propKind === "goal") {
      if (!propParent) { setPropMsg("Choose a parent project."); return; }
      payload = { project_id: propParent, title: propDraft.title || "New goal", priority: 0 };
    } else if (propKind === "assignment") {
      if (!propParent) { setPropMsg("Choose a target goal."); return; }
      payload = { goal_id: propParent, agent_id: propDraft.subject_agent || "workspace_architect" };
    } else if (propKind === "plan") {
      // A plan is self-contained: approving it creates its own workspace/project
      // plus goals (from milestones) and deliverables. No parent needed.
    } else {
      if (!propParent) { setPropMsg("Choose a parent project."); return; }
      payload = { project_id: propParent, title: propDraft.title || "New deliverable" };
    }
    setPropBusy(true);
    setPropMsg("");
    try {
      if (propKind === "plan") {
        const r = await fetch(`${API}/team/plans`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: propDraft.title || "New plan",
            milestones: propDraft.milestones || [],
            deliverables: propDraft.deliverables || [],
            tasks: propDraft.tasks || [],
            success_criteria: [],
            description: propDraft.description || "",
            thread_id: threadId || undefined,
          }),
        });
        const b = await r.json().catch(() => ({}));
        if (!r.ok) { setPropMsg((b as any).detail || `Could not create the plan proposal (${r.status}).`); return; }
        setPropMsg("Plan proposed — approve it to create the goals and deliverables.");
        setPropDraft(null);
        setPropParent("");
        return;
      }
      const r = await fetch(`${API}/work/proposals`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ work_type, action: "create", payload, thread_id: threadId || undefined }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) { setPropMsg((b as any).detail || `Could not create the proposal (${r.status}).`); return; }
      setPropMsg("Proposal created — approve it in Work · Approvals to create the real record.");
      setPropDraft(null);
      setPropParent("");
    } catch {
      setPropMsg(propKind === "plan" ? "Could not create the plan proposal. Please try again." : "Could not create the proposal. Please try again.");
    } finally {
      setPropBusy(false);
    }
  };

  const parentOptions = () => {
    if (propKind === "project") return propParents.workspaces.map((w) => ({ id: w.id, label: w.name }));
    if (propKind === "goal") return propParents.projects.map((p) => ({ id: p.id, label: p.name }));
    if (propKind === "assignment") return propParents.goals.map((g) => ({ id: g.id, label: g.title }));
    return propParents.projects.map((p) => ({ id: p.id, label: p.name }));
  };

  return (
    <section className="team-chat-shell" data-testid="team-chat">
      <aside className="team-chat__sidebar" aria-label="Conversations">
        <h4 className="section-title">Conversations</h4>
        <p className="muted">Pick a thread to keep it contained here.</p>
        {conversations.length === 0 ? (
          <p className="muted" data-testid="conv-sidebar-empty">No saved conversations yet.</p>
        ) : (
          <ul className="team-chat__convlist">
            {conversations.map((c) => (
              <li key={c.thread_id}>
                <button
                  className={`team-chat__conv${threadId === c.thread_id ? " team-chat__conv--active" : ""}`}
                  data-testid={`conv-${c.thread_id}`}
                  onClick={() => openConv(c.thread_id)}
                  title={c.title || c.thread_id}
                >
                  {c.title || c.thread_id}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className="panel team-chat">
      <div className="panel__head">
        <div>
          <h3 className="section-title">AI Team chat</h3>
          <p className="panel__sub">One shared conversation with all of your agents. Only you can start or run work.</p>
        </div>
        <span className="badge badge--faint">{mode === "team" ? "Any agent may reply" : MODE_META[mode].label}</span>
      </div>

      <div className="team-chat__modes" role="group" aria-label="Compose mode">
        {(Object.keys(MODE_META) as Mode[]).map((m) => (
          <button
            key={m}
            className={`btn btn--sm${mode === m ? " btn--primary" : " btn--ghost"}`}
            data-testid={`mode-${m}`}
            aria-pressed={mode === m}
            onClick={() => setMode(m)}
          >
            {MODE_META[m].label}
          </button>
        ))}
      </div>

      <div className="team-chat__hint muted">{MODE_META[mode].hint}</div>

      {mode === "propose" && (
        <div className="extract-panel" data-testid="propose-panel">
          <div className="extract-panel__head">
            <span className="result__heading">Build a proposal from your message</span>
            <span className="badge badge--faint">draft only — requires your approval</span>
          </div>
          <p className="muted">Pick the kind of work, extract an editable draft, choose a parent, then file it for approval.</p>
          <div className="work-toolbar" style={{ flexWrap: "wrap" }}>
            <select className="select select--small" value={propKind} onChange={(e) => chooseKind(e.target.value)} aria-label="Proposal kind" data-testid="prop-kind">
              <option value="project">Project</option>
              <option value="goal">Goal</option>
              <option value="plan">Plan (goals + deliverables)</option>
              <option value="assignment">Assignment</option>
              <option value="deliverable">Deliverable</option>
            </select>
            <button className="btn btn--sm btn--ghost" data-testid="prop-extract" disabled={propBusy || !draft.trim()} onClick={extractProposal}>
              {propBusy ? "Extracting…" : "Extract draft"}
            </button>
          </div>

          {propDraft && (
            <div className="work-toolbar" style={{ flexWrap: "wrap" }}>
              <span className="muted">Title:</span>
              <input className="input input--sm" value={propDraft.title || ""} data-testid="prop-title" aria-label="Proposal title"
                onChange={(e) => setPropDraft({ ...propDraft, title: e.target.value })} />
              {propKind !== "plan" && (<>
                <span className="muted">Parent:</span>
                <select className="select select--small" value={propParent} onChange={(e) => setPropParent(e.target.value)} aria-label="Parent" data-testid="prop-parent">
                  <option value="">Select a parent…</option>
                  {parentOptions().map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </>)}
              <button className="btn btn--sm btn--primary" data-testid="prop-file" disabled={propBusy} onClick={proposeProposal}>
                {propBusy ? "Filing…" : "Propose for approval"}
              </button>
            </div>
          )}
          {propMsg && <p className="success" role="status" data-testid="prop-msg">{propMsg}</p>}
        </div>
      )}

      <div className="team-chat__list" ref={listRef} data-testid="team-chat-list">
        {booting ? (
          <div className="empty">Preparing your team chat…</div>
        ) : messages.length === 0 ? (
          <div className="empty" data-testid="team-chat-empty">
            This is a fresh team thread. Send a message and the relevant agents will join in.
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`chat-bubble chat-bubble--${m.role === "user" ? "user" : "agent"}`}>
              <div className="chat-bubble__head">
                {m.role !== "user" && <AgentAvatar slug={m.agent} />}
                <span className="chat-bubble__role">
                  {m.role === "user" ? "You" : m.agent ? humanizeAgent(m.agent) : "Team"}
                </span>
                {m.created_at && <span className="chat-bubble__time">{stamp(m.created_at)}</span>}
              </div>
              <div className="chat-bubble__body markdown"><Markdown source={m.content} /></div>
            </div>
          ))
        )}
        {sending && (
          <div className="chat-bubble chat-bubble--agent">
            <div className="chat-bubble__head"><AgentAvatar slug="" /><div className="chat-bubble__role">Team</div></div>
            <div className="chat-bubble__status" role="status"><span className="spinner" aria-hidden="true" /> coordinating…</div>
          </div>
        )}
      </div>

      {progress.length > 0 && (
        <div className="team-progress" data-testid="team-progress">
          <span className="section-title">Recent activity ({progress.length})</span>
          <ul className="list">
            {progress.slice(0, 6).map((p, i) => (
              <li key={`${p.id || i}`} className="list__item team-progress__item" data-testid={`progress-${i}`}>
                <span className="badge badge--faint">{humanizeAgent(p.agent_id)} · {p.status}</span>
                {p.detail && <span className="muted"> — {p.detail.slice(0, 140)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="error" role="alert" data-testid="team-chat-error">{error}</p>}

      <div className="team-chat__composer">
        <textarea
          className="input"
          rows={3}
          placeholder="Message the whole team… (e.g. Research the launch market and propose a strategy)"
          value={draft}
          data-testid="team-chat-input"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          disabled={booting}
        />
        <div className="team-chat__actions">
          {mode === "propose" ? (
            <button
              className="btn btn--primary"
              data-testid="team-chat-propose"
              disabled={booting || propBusy || !draft.trim()}
              onClick={extractProposal}
            >
              {propBusy ? "Extracting…" : "Extract & propose"}
            </button>
          ) : (
            <button
              className="btn btn--primary"
              data-testid="team-chat-send"
              disabled={booting || sending || !draft.trim()}
              onClick={send}
            >
              {sending ? "Coordinating…" : "Send to team"}
            </button>
          )}
        </div>
        </div>
      </div>
    </section>
  );
}
