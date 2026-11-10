// AI Team 2 — the shared group chat (Home hero).
//
// One big conversation with every agent: the human sends a message to the team,
// and the backend's TeamRouter dispatches it SEQUENTIALLY to the relevant
// agent(s), returning one labeled bubble per agent. Any relevant agent may
// reply. The composer also supports designating a task or requesting a proposal
// (same shared thread, human-initiated). Nothing runs automatically and no
// agent is dispatched after a single send beyond the existing routing.
import { useCallback, useEffect, useRef, useState } from "react";
import { API, humanizeAgent, type TeamGoalDraft } from "./coordination";
import { Composer } from "./Composer";
import { TeamChatTimeline } from "./TeamChatTimeline";
import { runAgentStream } from "./coordination";
import { Markdown } from "./markdown";

const THREAD_KEY = "ai-team-shared-thread";
const CONTACTS = [
  { id: "team", label: "AI Team", subtitle: "Group chat · everyone", avatar: undefined },
  { id: "strategist", label: "Aisha — Visionary", subtitle: "Strategy & vision", avatar: "strategist" },
  { id: "communications", label: "Brandon — Voice", subtitle: "Communications Manager", avatar: "communications" },
  { id: "tutor", label: "Brittany — Educator", subtitle: "Tutor", avatar: "tutor" },
  { id: "executive_assistant", label: "Taylor — Organizer", subtitle: "Executive Assistant", avatar: "executive_assistant" },
  { id: "workspace_architect", label: "Alex — Builder", subtitle: "Architect", avatar: "workspace_architect" },
  { id: "soundboard", label: "Portia — Challenger", subtitle: "Advisory", avatar: "soundboard" },
] as const;

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

const AGENT_ICONS: Record<string, string> = { strategist: "👁️", tutor: "📚", executive_assistant: "🗓️", communications: "🎙️", soundboard: "⚡", workspace_architect: "🔧" };
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
  const icon = slug ? AGENT_ICONS[slug.toLowerCase()] : undefined;
  const avatar = src ? (
      <img className="agent-avatar agent-avatar--img" data-testid={`avatar-${slug}`} aria-hidden="true" src={src} alt="" style={{ width: size, height: size }} />
    ) : (
      <span className="agent-avatar" data-testid={`avatar-${slug || "team"}`} aria-hidden="true" style={{ width: size, height: size, background: agentColor(slug), fontSize: Math.round(size * 0.48) }}>{agentInitial(slug)}</span>
    );
  if (!icon) return avatar;
  return (
    <span style={{ position: "relative", display: "inline-flex", width: size, height: size }}>
      {avatar}
      <span style={{ position: "absolute", bottom: -4, right: -4, width: 16, height: 16, borderRadius: "50%", background: "var(--surface)", border: "1px solid var(--border)", display: "grid", placeItems: "center", fontSize: 9 }}>{icon}</span>
    </span>
  );
}

interface Msg {
  role: "user" | "assistant";
  agent?: string;
  content: string;
  created_at?: string;
}

type Mode = "team" | "task" | "delegate";

const MODE_META: Record<Mode, { label: string; hint: string; prefix: string }> = {
  team: { label: "Ask the team", hint: "Any relevant agent replies.", prefix: "" },
  task: { label: "Designate a task", hint: "The message is treated as an assignment for the most relevant agents.", prefix: "[Designated task] " },
  delegate: { label: "Delegate to the team", hint: "Turn this into a runnable team plan; agents run their steps, you approve the final deliverable.", prefix: "[Delegated to team] " },
};

function stamp(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
}

export function TeamChat({ onOpenTasks }: { onOpenTasks?: () => void } = {}) {
  const [threadId, setThreadId] = useState<string>(() => (typeof localStorage !== "undefined" ? localStorage.getItem(THREAD_KEY) || "" : ""));
  const [activeContact, setActiveContact] = useState("team");
  const [voiceOutput, setVoiceOutput] = useState(true);
  const [booting, setBooting] = useState(true);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<Mode>("team");
  const [individualAgent, setIndividualAgent] = useState<string>("tutor");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  // --- Delegate-to-the-team: message -> TeamGoal proposal -> approve/authorize/run ---
  const [delegBusy, setDelegBusy] = useState(false);
  const [delegMsg, setDelegMsg] = useState("");
  const [delegDraft, setDelegDraft] = useState<TeamGoalDraft | null>(null);
  // --- Phase 8 §15: durable team progress feed for this thread ---
  const [progress, setProgress] = useState<any[]>([]);
  // --- Task Center <-> chat linkage: work this thread produced ---
  const [workLinks, setWorkLinks] = useState<any[]>([]);
  const audioRef=useRef<HTMLAudioElement>(null);
  useEffect(()=>{ if(!voiceOutput) return; const last=messages[messages.length-1]; if(last && last.role==="assistant" && last.content && last.agent){ fetch(`${API}/voice/speak`, {method:"POST", headers:{"Content-Type":"application/json", "x-token": localStorage.getItem("pat_token")||""}, body: JSON.stringify({agent: last.agent, text: last.content.slice(0,1000)})}).then(r=>r.blob()).then(b=>{ const url=URL.createObjectURL(b); if(audioRef.current){ audioRef.current.src=url; audioRef.current.play(); }}).catch(()=>{}); } },[messages]);
  // --- conversation sidebar ---
  const [conversations, setConversations] = useState<any[]>([]);
  const listRef = useRef<HTMLDivElement>(null);

  const threadStorageKey = (contact: string) => contact === "team" ? THREAD_KEY : `ai-team-contact-thread-${contact}`;

  const ensureThread = useCallback(async (contact = "team") => {
    const storageKey = threadStorageKey(contact);
    if (typeof localStorage !== "undefined" && localStorage.getItem(storageKey)) {
      setThreadId(localStorage.getItem(storageKey) || "");
      return;
    }
    try {
      const r = await fetch(`${API}/team/threads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: contact === "team" ? "AI Team" : `${humanizeAgent(contact)} chat`, thread_type: "team" }),
      });
      const b = await r.json().catch(() => ({}));
      if (r.ok && b.thread_id) {
        if (typeof localStorage !== "undefined") localStorage.setItem(storageKey, b.thread_id);
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
    try {
      const wl = await fetch(`${API}/work/links?thread_id=${encodeURIComponent(tid)}`);
      const wd = await wl.json().catch(() => ({}));
      setWorkLinks(wd.items || []);
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
    setWorkLinks([]);
    if (typeof localStorage !== "undefined") localStorage.setItem(THREAD_KEY, tid);
  };

  const deleteConv = async (tid: string) => {
    try {
      const r = await fetch(`${API}/memory/conversations/${encodeURIComponent(tid)}`, { method: "DELETE" });
      if (r.ok) {
        if (threadId === tid) {
          if (typeof localStorage !== "undefined") localStorage.removeItem(THREAD_KEY);
          setThreadId("");
          setMessages([]);
          setProgress([]);
        }
        loadConversations();
      }
    } catch { /* offline */ }
  };

  useEffect(() => {
    (async () => { await ensureThread("team"); setBooting(false); loadConversations(); })();
  }, [ensureThread, loadConversations]);

  useEffect(() => { if (threadId) load(threadId); }, [threadId, load]);

  const selectContact = async (contact: string) => {
    if (contact === activeContact && threadId) return;
    setBooting(true);
    setActiveContact(contact);
    setMessages([]);
    setProgress([]);
    setWorkLinks([]);
    setDelegDraft(null);
    setDelegMsg("");
    const key = threadStorageKey(contact);
    const saved = typeof localStorage !== "undefined" ? localStorage.getItem(key) || "" : "";
    if (saved) setThreadId(saved);
    else await ensureThread(contact);
    setBooting(false);
  };

  useEffect(() => {
    const el = listRef.current;
    if (!el || typeof el.scrollTo !== "function") return; // jsdom lacks scrollTo
    try { el.scrollTo({ top: el.scrollHeight }); } catch { /* non-critical */ }
  }, [messages.length, booting]);

  const send = async () => {
    const text = draft.trim();
    if (!text || sending || booting) return;
    // The user explicitly chose "Delegate to the team". Enter/Send must route
    // through the structured planner (POST /projects), never fall through to the
    // conversational chat like the team/task auto-delegate heuristic does.
    if (mode === "delegate") {
      setActiveContact("team");
      setDraft("");
      await delegateToTeam(text);
      return;
    }
    // Individual mode: dispatch to selected agent via individual endpoint
    if (mode === "task" && individualAgent) {
      const payload = text;
      setSending(true);
      setError("");
      // Optimistically add user message
      setMessages((prev) => [...prev, { role: "user", content: payload, created_at: new Date().toISOString() }]);
      setDraft("");
      try {
        await runAgentStream(individualAgent, { task: payload }, {
          onChunk: (chunk: string) => {
            setMessages((prev) => {
              const last = prev[prev.length-1];
              if (last && last.role === "assistant" && last.agent === individualAgent) {
                return [...prev.slice(0,-1), { ...last, content: last.content + chunk }];
              }
              return [...prev, { role: "assistant", agent: individualAgent, content: chunk, created_at: new Date().toISOString() }];
            });
          },
          onDone: (meta: any) => {
            if (meta?.reply) {
              setMessages((prev) => {
                const last = prev[prev.length-1];
                if (last && last.role === "assistant" && last.agent === individualAgent) return prev;
                return [...prev, { role: "assistant", agent: individualAgent, content: meta.reply, created_at: new Date().toISOString() }];
              });
            }
          },
          onError: (msg: string) => setError(msg),
        } as any);
      } catch (e: any) { setError(e?.message || "request failed"); }
      setSending(false);
      return;
    }
    const asksToCapturePlan = /\b(?:capture|save|turn)\b[\s\S]{0,30}\b(?:as|into)\b[\s\S]{0,12}\bplan\b/i.test(text);
    const asksToDelegate = (mode === "team" || mode === "task") && (
      /\b(delegate|assign|break\s+(?:this|it)\s+into\s+tasks|have\s+\w+\s+(?:draft|research|define|write)|(?:create|build|launch)\s+(?:a\s+)?campaign|marketing campaign|campaign strategy|long[-\s]term strategy|strategy for)\b/i.test(text) ||
      /\b(?:i\s+(?:need|want)|help me with|create|develop|build|make)\b[\s\S]{0,50}\b(?:plan|strategy|roadmap|campaign)\b/i.test(text)
    );
    if (asksToDelegate || asksToCapturePlan) {
      const recentDiscussion = messages
        .filter((message) => message.role === "assistant")
        .slice(-3)
        .map((message) => message.content)
        .join("\n\n")
        .slice(-6000);
      const planRequest = asksToCapturePlan && recentDiscussion
        ? `Create an approval-gated team plan from this discussion. Preserve the useful objectives and constraints, assign work only to registered agents, and do not execute anything yet.\n\nDISCUSSION:\n${recentDiscussion}`
        : text;
      setMode("delegate");
      setActiveContact("team");
      setDraft("");
      await delegateToTeam(planRequest);
      return;
    }
    const full = activeContact !== "team"
      ? `@${activeContact} ${mode === "team" ? text : `${MODE_META[mode].prefix}${text}`}`
      : mode === "team"
        ? text
        : `${MODE_META[mode].prefix}${text}`;
    setDraft("");
    setError("");
    setSending(true);
    setMessages((prev) => [...prev, { role: "user", content: full, created_at: new Date().toISOString() }]);
    try {
      const body: any = { message: full, thread_id: threadId || undefined };
      if (activeContact !== "team") body.subject_agent = activeContact;
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

  async function delegateToTeam(message?: string) {
    const request = (message ?? draft).trim();
    if (!request) return;
    setDelegBusy(true);
    // Immediate feedback: show the user's request as sent, and a clear working
    // status, because the structured planner (local model) can take up to a
    // minute before a plan is ready.
    setMessages((prev) => [...prev, {
      role: "user" as const,
      content: `${MODE_META.delegate.prefix}${request}`,
      created_at: new Date().toISOString(),
    }]);
    setDelegMsg("Generating your team plan\u2026 this can take up to a minute.");
    setDelegDraft(null);
    try {
      const structured = await fetch(`${API}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: request }),
      });
      const structuredBody = await structured.json().catch(() => ({}));
      if (!structured.ok || !structuredBody.id) {
        const detail = typeof structuredBody.detail === "string"
          ? structuredBody.detail
          : `structured planner returned HTTP ${structured.status}`;
        throw new Error(`Structured planning failed: ${detail}. No plan was saved.`);
      }
      window.dispatchEvent(new CustomEvent("ai-team:structured-project-created", {
        detail: { projectId: structuredBody.id },
      }));
      setDelegMsg("Structured plan created. Review and approve it before any task runs.");
    } catch (e) {
      const detail = (e as any)?.message || (e as any)?.detail;
      setDelegMsg(detail ? `Could not delegate: ${detail}` : "Could not delegate. Please try again.");
    } finally {
      setDelegBusy(false);
    }
  }

  return (
    <section className="team-chat-shell" data-testid="team-chat">
      <aside className="team-chat__sidebar" aria-label="Conversations">
        <div className="team-chat__inbox-head">
          <div>
            <h4 className="section-title">Messages</h4>
            <p className="muted">Your AI team</p>
          </div>
          <span className="team-chat__online-dot" aria-label="Online" />
        </div>
        <ul className="team-chat__contacts">
          {CONTACTS.map((contact) => (
            <li key={contact.id}>
              <button
                className={`team-chat__contact${activeContact === contact.id ? " team-chat__contact--active" : ""}`}
                data-testid={`contact-${contact.id}`}
                onClick={() => selectContact(contact.id)}
              >
                <span className="team-chat__contact-avatar">
                  {contact.id === "team"
                    ? <span className="team-chat__mini-stack"><AgentAvatar slug="strategist" size={22} /><AgentAvatar slug="communications" size={22} /></span>
                    : <AgentAvatar slug={contact.avatar} size={36} />}
                </span>
                <span className="team-chat__contact-copy">
                  <strong>{contact.label}</strong>
                  <small>{contact.subtitle}</small>
                </span>
                {activeContact === contact.id && <span className="team-chat__contact-check">✓</span>}
              </button>
            </li>
          ))}
        </ul>
        {conversations.length > 0 && (
          <details className="team-chat__other" open>
            <summary>Recent conversations</summary>
            <ul className="team-chat__convlist">
              {conversations.map((c) => (
                <li key={c.thread_id}>
                  <div className="team-chat__convrow">
                    <button className={`team-chat__conv${threadId === c.thread_id ? " team-chat__conv--active" : ""}`}
                      data-testid={`conv-${c.thread_id}`} onClick={() => openConv(c.thread_id)}>
                      {c.title || c.thread_id}
                    </button>
                    <button className="team-chat__del" data-testid={`del-conv-${c.thread_id}`}
                      aria-label={`Delete ${c.title || "conversation"}`} onClick={() => deleteConv(c.thread_id)}>×</button>
                  </div>
                </li>
              ))}
            </ul>
          </details>
        )}
      </aside>

      <div className="panel team-chat">
      <div className="panel__head">
        <div className="team-chat__title">
          {activeContact === "team" ? (
            <div className="team-chat__avatar-stack" aria-hidden="true">
              <AgentAvatar slug="strategist" size={34} />
              <AgentAvatar slug="communications" size={34} />
              <AgentAvatar slug="tutor" size={34} />
            </div>
          ) : <AgentAvatar slug={activeContact} size={44} />}
          <div>
            <h3 className="section-title">{CONTACTS.find((c) => c.id === activeContact)?.label || "AI Team"}</h3>
            <p className="panel__sub"><span className="team-chat__online-dot" /> {activeContact === "team" ? "Everyone · On Us workspace" : "Available · Private conversation"}</p>
          </div>
        </div>
        <span className="team-chat__mode-label">{mode === "team" ? "Team chat" : MODE_META[mode].label}</span>
        {workLinks.length > 0 && onOpenTasks && (
          <button className="btn btn--sm btn--ghost" data-testid="chat-open-tasks"
            onClick={onOpenTasks}>
            View {workLinks.length} in Task Center
          </button>
        )}
      </div>

      <div className="team-chat__auto-mode">
        <span className="team-chat__mode-label">Automatic team workflow</span>
        <span className="muted">Ask naturally. The team will reply or prepare a plan when work is needed.</span>
      </div>
      <details className="team-chat__advanced">
        <summary>More ways to work</summary>
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
      </details>

      {mode === "delegate" && (delegDraft || delegMsg) && (
        <div className="extract-panel" data-testid="delegate-panel">
          <div className="extract-panel__head">
            <span className="result__heading">Team plan from your message</span>
            <span className="badge badge--faint">intent only — your approval gates run</span>
          </div>
          {delegDraft && (
            <div className="muted" data-testid="delegate-draft">
              <p><strong>{delegDraft.title}</strong></p>
              <ul className="list">
                {(delegDraft.steps || []).map((s, i) => (
                  <li key={s.seq ?? i} className="list__item">
                    {humanizeAgent(s.agent_id)} · {s.responsibility || "—"}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {delegMsg && <p className="success" role="status" data-testid="delegate-msg">{delegMsg}</p>}
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
          <TeamChatTimeline messages={messages as any} />
        )}
        {sending && (
          <div className="chat-bubble chat-bubble--agent">
            <div className="chat-bubble__head"><AgentAvatar slug="" /><div className="chat-bubble__role">Team</div></div>
            <div className="chat-bubble__status" role="status"><span className="spinner" aria-hidden="true" /> coordinating…</div>
          </div>
        )}
      </div>

      <audio ref={audioRef} controls style={{display:"none"}} />
      {error && <p className="error" role="alert" data-testid="team-chat-error">{error}</p>}

      <div className="team-chat__composer">
        <div style={{display:"flex",gap:8,marginBottom:8,alignItems:"center"}}>
          <label style={{display:"flex",gap:4,alignItems:"center",fontSize:12}}><input type="checkbox" checked={voiceOutput} onChange={e=>setVoiceOutput(e.target.checked)} /> Voice reply</label>
          <button className={`btn ${mode==="team"?"btn--primary":""}`} onClick={()=>setMode("team")}>Team</button>
          <button className={`btn ${mode==="task"?"btn--primary":""}`} onClick={()=>setMode("task")}>Individual</button>
          <button className={`btn ${mode==="delegate"?"btn--primary delegate-btn--active":"btn--ghost"}`} onClick={()=>setMode("delegate")}>Delegate</button>
        </div>
        {mode==="task" && (
          <select value={individualAgent} onChange={e=>setIndividualAgent(e.target.value)} style={{marginBottom:8}}>
            <option value="tutor">Tutor</option>
            <option value="strategist">Strategist</option>
            <option value="communications">Communications</option>
            <option value="executive_assistant">Executive Assistant</option>
            <option value="workspace_architect">Workspace Architect</option>
            <option value="soundboard">Soundboard</option>
          </select>
        )}
        <Composer value={draft} onChange={setDraft} onSend={send} placeholder={mode==="team"?"Message the whole team…":"Message individual agent…"} disabled={booting || sending} />
        <div className="team-chat__actions">
          {mode === "delegate" ? (
            <button
              className="btn btn--primary"
              data-testid="team-chat-delegate"
              disabled={booting || delegBusy || !draft.trim()}
              onClick={() => delegateToTeam()}
            >
              {delegBusy ? "Delegating…" : "Delegate to team"}
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

        {progress.length > 0 && (
          <div className="team-progress" data-testid="team-progress">
            <span className="team-progress__title">Recent activity ({progress.length})</span>
            <ul className="team-progress__list">
              {progress.slice(0, 3).map((p, i) => (
                <li key={`${p.id || i}`} className="team-progress__item" data-testid={`progress-${i}`}>
                  <span className="team-progress__agent">{humanizeAgent(p.agent_id)}</span>
                  <span className="team-progress__status">{p.status}</span>
                  {p.detail && <span className="team-progress__detail"> — {p.detail.slice(0, 100)}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
