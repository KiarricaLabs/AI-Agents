import { AgentAvatar } from "./team_chat";
import { Markdown } from "./markdown";

interface Msg { role: string; agent?: string; content: string; created_at?: string }

interface Props { messages: Msg[] }

async function playVoice(agent: string | undefined, text: string) {
  if (!agent || !text) return;
  try {
    const r = await fetch(`${(import.meta.env.VITE_API_BASE as string) || "http://127.0.0.1:8001"}/voice/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-token": localStorage.getItem("pat_token") || "" },
      body: JSON.stringify({ agent, text: text.slice(0,1000) }),
    });
    if (!r.ok) throw new Error(await r.text());
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    await audio.play();
  } catch (e) { console.error("voice play failed", e); }
}

export function TeamChatTimeline({ messages }: Props) {
  const turns: { user?: Msg; agents: Msg[] }[] = [];
  let current: { user?: Msg; agents: Msg[] } | null = null;
  for (const m of messages) {
    if (m.role === "user") {
      if (current) turns.push(current);
      current = { user: m, agents: [] };
    } else {
      if (!current) current = { agents: [] };
      current.agents.push(m);
    }
  }
  if (current) turns.push(current);
  return (
    <div className="timeline">
      {turns.map((t, i) => (
        <div key={i} className="timeline__turn">
          {t.user && (
            <div className="timeline__user">
              <div className="timeline__user-bubble">{t.user.content}</div>
              {t.user.created_at && <span className="timeline__time">{new Date(t.user.created_at).toLocaleTimeString()}</span>}
            </div>
          )}
          {t.agents.length > 0 && (
            <div className="timeline__team">
              <div className="timeline__team-label">Team response · {t.agents.length} {t.agents.length === 1 ? "agent" : "agents"}</div>
              {t.agents.map((a, idx) => (
                <div key={idx} className="timeline__agent">
                  <AgentAvatar slug={a.agent} size={32} />
                  <div className="timeline__agent-body" style={{flex:1}}>
                    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                      <div className="timeline__agent-name">{a.agent ? `${{"strategist":"👁️ Aisha — Visionary","tutor":"📚 Brittany — Tutor","executive_assistant":"🗓️ Taylor — Organizer","communications":"🎙️ Brandon — Voice","soundboard":"⚡ Portia — Challenger","workspace_architect":"🔧 Alex — Builder"}[a.agent] || a.agent}` : "Assistant"}</div>
                      <button onClick={()=>playVoice(a.agent, a.content)} title="Play voice" style={{background:"var(--surface-2)",border:"1px solid var(--border)",borderRadius:6,padding:"2px 6px",cursor:"pointer"}}>🔊</button>
                    </div>
                    <div className="timeline__agent-content"><Markdown source={a.content} /></div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
