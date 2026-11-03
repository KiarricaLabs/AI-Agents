import { useEffect, useState, type ReactNode } from "react";
import { diffLines } from "./diff";
import { Markdown } from "./markdown";
import { KNOWN_SAMPLE_IDS } from "./knownSamples";
import { statusLabel, priorityText } from "./uiText";
import "./App.css";

const API = "http://127.0.0.1:8001";

// Matches an explicit workspace-creation request so the chat offers a reliable
// "propose workspace" path (the model may not emit a valid proposal itself).
const WS_INTENT_RE = /(?:create|make|set up|start|add|open|new|build|establish)[\s\S]{0,40}workspace/i;

// Browser-only, presentation-level storage keys for the sample-data control.
const SAMPLE_VISIBLE_KEY = "pat.sampleData.visible";
const SAMPLE_REVEALED_KEY = "pat.sampleData.revealed";

type Tab = "overview" | "workspace" | "work" | "episodes" | "agents";

const NAV: { id: Tab; icon: string; label: string }[] = [
  { id: "overview", icon: "home", label: "Overview" },
  { id: "workspace", icon: "grid", label: "Workspaces" },
  { id: "work", icon: "briefcase", label: "Work" },
  { id: "episodes", icon: "activity", label: "Activity" },
  { id: "agents", icon: "bot", label: "Agents" },
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

function proposalStatusLabel(s?: string | null): string {
  const m: Record<string, string> = {
    proposed: "Pending approval",
    approved: "Approved",
    rejected: "Rejected",
    stale: "Stale",
    failed: "Failed",
  };
  if (!s) return "—";
  return m[s] || s.charAt(0).toUpperCase() + s.slice(1);
}

function OriginConversation({
  types, wid, threadsByKey, onLoad, onOpen,
}: {
  types: string[];
  wid: string;
  threadsByKey: Record<string, any[]>;
  onLoad: (w: string, i: string) => void;
  onOpen: (t: any) => void;
}) {
  useEffect(() => {
    if (wid) types.forEach((t) => onLoad(t, wid));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [types.join(","), wid]);
  const all = types.flatMap((t) => threadsByKey[`${t}:${wid}`] || []).filter(Boolean);
  const seen = new Set<string>();
  const uniq = all.filter((x) => (seen.has(x.thread_id) ? false : (seen.add(x.thread_id), true)));
  if (!wid || uniq.length === 0) return null;
  return (
    <div className="origin-block" data-testid={`origin-${wid}`}>
      <span className="detail-panel__label">Originating conversation</span>
      {uniq.map((t) => (
        <button key={t.thread_id} className="origin-link" onClick={() => onOpen(t)}>
          {t.title || t.thread_id}
        </button>
      ))}
    </div>
  );
}

function ExecutionPanel({
  wtype, wid, data, onLoad, agentLabelFn,
}: {
  wtype: string;
  wid: string;
  data?: any;
  onLoad: (w: string, i: string) => void;
  agentLabelFn: (a: string) => string;
}) {
  useEffect(() => {
    if (wid) onLoad(wtype, wid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wtype, wid]);
  if (!data || !data.episodes || data.episodes.length === 0) return null;
  return (
    <div className="exec-history" data-testid={`exec-${wid}`}>
      <span className="detail-panel__label">Execution history</span>
      <ul className="list">
        {data.episodes.map((e: any) => (
          <li key={e.episode_id} className="list__item">
            <span className="list__name">{agentLabelFn(e.agent_id)}</span>
            <span className={`badge badge--${e.status || "neutral"}`}>{statusLabel(e.status)}</span>
            <span className="badge badge--faint">{Math.round((e.progress || 0) * 100)}%</span>
            {e.evidence_summary && <span className="badge badge--faint">{e.evidence_summary}</span>}
            {e.applied_at && <span className="badge badge--approved">Applied</span>}
          </li>
        ))}
      </ul>
    </div>
  );
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
  // --- M10 D4.2: graceful generation failure handling ---
  const [agentGenError, setAgentGenError] = useState<any>(null);
  const [agentRetryTask, setAgentRetryTask] = useState<string | null>(null);
  const [agentRetryThread, setAgentRetryThread] = useState<string | null>(null);
  // Model availability is tracked separately from whole-backend `offline`.
  const [modelOnline, setModelOnline] = useState<boolean | null>(null);
  // Inline names for Workspaces-page Create buttons.
  const [wsProjName, setWsProjName] = useState("");
  const [wsGoalName, setWsGoalName] = useState("");
  const [wsDelivName, setWsDelivName] = useState("");
  // Reliable workspace-creation fallback: offer to propose the workspace for
  // approval when the agent didn't emit a proposal itself.
  const [wsPrompt, setWsPrompt] = useState<{ task: string; threadId: string | null } | null>(null);
  const [wsProposed, setWsProposed] = useState(false);
  const [wsError, setWsError] = useState("");
  const [wsBusy, setWsBusy] = useState(false);
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

  // --- Sample-data presentation control (browser-only; no DB/API change) ---
  const [sampleDataVisible, setSampleDataVisible] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SAMPLE_VISIBLE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [revealedIds, setRevealedIds] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(SAMPLE_REVEALED_KEY) || "[]");
    } catch {
      return [];
    }
  });
  const [manageSamples, setManageSamples] = useState(false);
  // Detail selections for click-through views.
  const [selectedGoal, setSelectedGoal] = useState<string | null>(null);
  const [selectedAssignment, setSelectedAssignment] = useState<string | null>(null);
  // Deliverable version UX.
  const [showRawDiff, setShowRawDiff] = useState(false);
  const [rejectingVersion, setRejectingVersion] = useState<string | null>(null);
  const [approvingVersion, setApprovingVersion] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [versionError, setVersionError] = useState<string | null>(null);
  // --- M10 Phase D1: approvals + bidirectional navigation (read-only) ---
  const [feed, setFeed] = useState<any[]>([]);
  const [proposalBusy, setProposalBusy] = useState<string | null>(null);
  // Step 2: batch approval of all pending proposals (each still approved via the
  // same authoritative endpoint; nothing is auto-created without human action).
  const [allApproving, setAllApproving] = useState(false);
  const [allApproveMsg, setAllApproveMsg] = useState<string | null>(null);
  const [proposalError, setProposalError] = useState<string | null>(null);
  // --- Deterministic proposal composer (all work types, no model dependency) ---
  const [pfType, setPfType] = useState<string>("goal");
  const [pfName, setPfName] = useState("");
  const [pfPriority, setPfPriority] = useState("1");
  const [pfWorkspace, setPfWorkspace] = useState("");
  const [pfProject, setPfProject] = useState("");
  const [pfGoal, setPfGoal] = useState("");
  const [pfDeliverable, setPfDeliverable] = useState("");
  const [pfAgent, setPfAgent] = useState("strategist");
  // Attribution: which agent "authored" the proposal (defaults to Alex).
  const [pfAuthor, setPfAuthor] = useState("workspace_architect");
  const [pfStatus, setPfStatus] = useState("");
  const [pfProgress, setPfProgress] = useState("");
  const [pfMsg, setPfMsg] = useState("");
  const [pfBusy, setPfBusy] = useState(false);
  const [threadLinks, setThreadLinks] = useState<any[]>([]);
  const [workThreads, setWorkThreads] = useState<Record<string, any[]>>({});
  // Work view -> originating conversation (work_type:work_id -> threads).
  // --- M10 Phase D2: execution tracking (human-operated, evidence-gated) ---
  const [workEpisodes, setWorkEpisodes] = useState<Record<string, any>>({});
  const [execError, setExecError] = useState<string | null>(null);
  const [execBusy, setExecBusy] = useState<string | null>(null);
  const [cpProgress, setCpProgress] = useState("0.5");
  const [cpEvidence, setCpEvidence] = useState("");
  const [completeEvidence, setCompleteEvidence] = useState("");
  const [epError, setEpError] = useState<string | null>(null);
  // --- M10 Phase D3: evidence-backed goal application + execution history ---
  const [workExec, setWorkExec] = useState<Record<string, any>>({});
  const [applyEid, setApplyEid] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [applyingEid, setApplyingEid] = useState<string | null>(null);
  // --- M10 Phase D4.1: approved-assignment execution ---
  const [confirmExec, setConfirmExec] = useState<string | null>(null);
  // --- Phase 1: turn an agent's idea draft into an approvable proposal ---
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftType, setDraftType] = useState("goal");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftGoal, setDraftGoal] = useState("");
  const [draftMsg, setDraftMsg] = useState<string | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  // Step 1: agent brainstorm mode — propose multiple parented ideas for approval.
  const [suggesting, setSuggesting] = useState(false);
  // Step 4: human-triggered "suggest next step" anchored to an approved goal.
  const [nextStepBusy, setNextStepBusy] = useState<string | null>(null);
  const [nextStepResult, setNextStepResult] = useState<{ goalId: string; msg: string } | null>(null);
  // Step 5: safe team orchestration — human-confirmed assignment proposal.
  const [assignOpenGoal, setAssignOpenGoal] = useState<string | null>(null);
  const [assignOwner, setAssignOwner] = useState<string>("");
  const [assignBusy, setAssignBusy] = useState<string | null>(null);
  const [assignMsg, setAssignMsg] = useState<{ goalId: string; msg: string } | null>(null);
  // D4.3-A1: unified "New Objective" command -> coordinated team plan preview.
  const [planObjective, setPlanObjective] = useState<string>("");
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [planResult, setPlanResult] = useState<any | null>(null);
  const [planNotice, setPlanNotice] = useState<string | null>(null);
  // D4.3-A2: editable plan review + approval bridge to /work/proposals.
  const [planFiling, setPlanFiling] = useState<number | null>(null);
  const [planAllBusy, setPlanAllBusy] = useState(false);
  const [planAllMsg, setPlanAllMsg] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(SAMPLE_VISIBLE_KEY, sampleDataVisible ? "1" : "0");
    } catch {}
  }, [sampleDataVisible]);
  useEffect(() => {
    try {
      localStorage.setItem(SAMPLE_REVEALED_KEY, JSON.stringify(revealedIds));
    } catch {}
  }, [revealedIds]);
  const isSample = (id: string) => KNOWN_SAMPLE_IDS.has(id);
  const isRevealed = (id: string) => revealedIds.includes(id);
  // A record is hidden only when sample data is hidden AND it is a known sample
  // AND it has not been individually revealed. IDs are the sole signal — names
  // are never used, so future legitimate records with any name stay visible.
  const effectiveHide = (id: string) =>
    !sampleDataVisible && isSample(id) && !isRevealed(id);
  const visibleOnly = (arr: { id: string }[]): any[] =>
    arr.filter((x) => !effectiveHide(x.id));
  const revealSample = (id: string) =>
    setRevealedIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
  const resetRevealed = () => setRevealedIds([]);
  const toggleAllSamples = () => setSampleDataVisible((v) => !v);

  // --- Conversation browser (global, all agents) ---
  const [conversations, setConversations] = useState<any[]>([]);
  const [convFilter, setConvFilter] = useState("");
  const [openThreadId, setOpenThreadId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<any[]>([]);
  const [renamingThread, setRenamingThread] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState("");

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then((d) => setHealth(JSON.stringify(d)))
      .catch(() => {
        setHealth("offline");
        setOffline(true);
      });
    // D4.2: separate model availability probe (read-only; no state mutation).
    fetch(`${API}/agents/model-health`)
      .then((r) => r.json())
      .then((d) => setModelOnline(d && d.model && d.model.code === "ok"))
      .catch(() => setModelOnline(null));
    refresh();
    fetchAgents();
    loadConvos();
    loadFeed(); // prefetch approvals so the Overview's coordinated status is accurate
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

  const loadConvos = async () => {
    try {
      const r = await fetch(`${API}/memory/conversations`);
      const d = await r.json();
      setConversations(d.items || []);
    } catch {
      /* offline or backend unavailable */
    }
  };

  const openConversation = async (c: any) => {
    setOpenThreadId(c.thread_id);
    setTranscript([]);
    setAgentResult(null);
    setAgentError("");
    loadThreadLinks(c.thread_id);
    try {
      const r = await fetch(
        `${API}/memory/conversation?thread_id=${encodeURIComponent(c.thread_id)}`
      );
      const d = await r.json();
      setTranscript((d.items || []).map((m: any) => ({
        role: m.role, content: m.content, created_at: m.created_at,
      })));
    } catch {
      /* offline or backend unavailable */
    }
    // Restore the correct agent + thread so continuing appends to THIS thread.
    if (c.agent_id) {
      setSelectedAgent(c.agent_id);
      setThreadIds((prev) => ({ ...prev, [c.agent_id]: c.thread_id }));
    }
  };

  const renameConversation = async (c: any, title: string) => {
    const trimmed = title.trim();
    if (!trimmed || renamingThread !== c.thread_id) return;
    await fetch(`${API}/memory/conversations/${encodeURIComponent(c.thread_id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: trimmed }),
    });
    setRenamingThread(null);
    setRenameTitle("");
    loadConvos();
  };

  const startRename = (c: any) => {
    setRenamingThread(c.thread_id);
    setRenameTitle(c.title || "");
  };

  const selectAgent = (agentName: string) => {
    setSelectedAgent(agentName);
    setAgentResult(null);
    setAgentError("");
    setAgentGenError(null); // a prior agent's stale failure panel must not linger
    setAgentRetryTask(null);
    setAgentRetryThread(null);
    setWsPrompt(null);
    setWsProposed(false);
    setWsError("");
    setDraftOpen(false);
    setDraftTitle("");
    setDraftGoal("");
    setDraftMsg(null);
    // Choosing an agent starts a fresh context (saved conversations are untouched).
    setOpenThreadId(null);
    setTranscript([]);
  };

  const runAgent = async () => {
    if (offline || agentRunning || !selectedAgent || !task.trim()) return;
    const submitted = task.trim();
    setAgentRunning(true);
    setAgentError("");
    setAgentResult(null);
    setAgentGenError(null);
    setAgentRetryTask(null);
    setAgentRetryThread(null);
    setWsPrompt(null);
    setWsProposed(false);
    setWsError("");
    setWsBusy(false);
    setDraftOpen(false);
    setDraftTitle("");
    setDraftGoal("");
    setDraftMsg(null);
    const payload: any = { task: submitted };
    if (threadIds[selectedAgent]) payload.thread_id = threadIds[selectedAgent];
    // D4.2/Option-A: route explicit workspace-creation requests through the
    // structured proposal path so the agent can only ever *propose* a workspace
    // (never create one from prose). The human approves it in the Work tab.
    if (WS_INTENT_RE.test(submitted)) {
      payload.work_intent = true;
    }
    // Clear the input immediately so it is ready for the next message while
    // the agent processes; it is restored below if the submission fails.
    setTask("");
    await performRun(submitted, payload);
  };

  const retryAgentRun = async () => {
    if (offline || agentRunning || !selectedAgent || !agentRetryTask) return;
    const submitted = agentRetryTask;
    const payload: any = { task: submitted, retry: true };
    if (agentRetryThread) payload.thread_id = agentRetryThread;
    setAgentRunning(true);
    setAgentError("");
    setAgentGenError(null);
    setAgentRetryTask(null);
    setAgentRetryThread(null);
    await performRun(submitted, payload);
  };

  const extractWorkspaceName = (text: string): string => {
    const clean = text.trim().replace(/[“”"']/g, "");
    const m1 = clean.match(/workspace\s+(?:called|named)?\s*([A-Za-z0-9][A-Za-z0-9 _\-&()]*)$/i);
    if (m1 && m1[1].trim()) return m1[1].trim();
    const m2 = clean.match(/(?:called|named)\s+([A-Za-z0-9][A-Za-z0-9 _\-&()]*)/i);
    if (m2 && m2[1].trim()) return m2[1].trim();
    return "Untitled Workspace";
  };

  // Deterministic Option-A path: create a workspace *proposal* for the user to
  // approve (no dependency on the AI model emitting valid JSON). Only a proposal
  // is stored; a real workspace is created only after human approval.
  const proposeWorkspace = async () => {
    if (!wsPrompt || wsBusy || offline) return;
    const name = extractWorkspaceName(wsPrompt.task);
    setWsBusy(true);
    setWsError("");
    try {
      const r = await fetch(`${API}/work/proposals/workspace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, thread_id: wsPrompt.threadId }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setWsError((b as any).detail || `Could not create the proposal (${r.status}).`);
        return;
      }
      setWsProposed(true);
      setWsPrompt(null);
    } catch {
      setWsError("Could not create the proposal. Please try again.");
    } finally {
      setWsBusy(false);
    }
  };

  // Step 1: have the currently selected agent brainstorm concrete, parented
  // ideas and file each as an approval-gated proposal in one turn. Uses the
  // existing structured (work_intent) path with grounded workspace/project
  // context; the backend injects/validates parent ids server-side. Nothing is
  // created without human approval in the Work tab.
  const suggestIdeas = async () => {
    if (offline || agentRunning || !selectedAgent) return;
    const pid = selectedProjectId || projects[0]?.id;
    const wid = selectedWorkspaceId || workspaces[0]?.id;
    const proj = projects.find((p) => p.id === pid);
    const ws = workspaces.find((w) => w.id === wid);
    const scope = proj
      ? `for the current project “${proj.name}”`
      : ws
        ? `for the current workspace “${ws.name}”`
        : "";
    const submitted = (
      `Propose 3-4 concrete, actionable improvement ideas${scope ? ` ${scope}` : ""} that move the work forward. ` +
      `Return a single JSON object with two keys: \u201creply\u201d (a short human summary of the ideas) and ` +
      `\u201cproposal_v1\u201d as an ARRAY of proposal objects, one per idea. Each proposal object has ` +
      `work_type, action \u201ccreate\u201d, payload with a clear short \u201ctitle\u201d, and a one-line \u201creason\u201d. ` +
      `Choose only proposal work types you are permitted to create. Use the provided workspace/project ` +
      `for parent ids; do not invent other ids. If you have no constructive ideas, return proposal_v1 as null.`
    ).trim();
    const payload: any = {
      task: submitted,
      work_intent: true,
    };
    if (threadIds[selectedAgent]) payload.thread_id = threadIds[selectedAgent];
    if (pid) payload.project_id = pid;
    if (wid) payload.workspace_id = wid;
    if (proj?.name) payload.project_name = proj.name;
    if (ws?.name) payload.workspace_name = ws.name;
    setSuggesting(true);
    setAgentRunning(true);
    setAgentError("");
    setAgentResult(null);
    setAgentGenError(null);
    setAgentRetryTask(null);
    setAgentRetryThread(null);
    setWsPrompt(null);
    setWsProposed(false);
    setWsError("");
    setWsBusy(false);
    setDraftOpen(false);
    setDraftTitle("");
    setDraftGoal("");
    setDraftMsg(null);
    await performRun(submitted, payload);
    setSuggesting(false);
    await loadFeed();
  };

  // Step 4: human-triggered "suggest next step" for a goal. Runs the structured
  // brainstorm on the selected project's grounded context (Step 3) and anchors
  // the ask to this specific goal. Any idea becomes a proposal for approval only;
  // nothing is auto-created or auto-approved.
  const suggestNextStep = async (goal: any) => {
    if (offline || nextStepBusy) return;
    const pid = goal?.project_id;
    const proj = projects.find((x) => x.id === pid);
    const wid = proj?.workspace_id || selectedWorkspaceId || workspaces[0]?.id;
    if (!pid) {
      setNextStepResult({ goalId: goal?.id, msg: "This goal has no project to ground on." });
      return;
    }
    const task = (
      `The current project is “${proj?.name || "this project"}”. It already contains this goal: ` +
      `“${goal.title}” (status: ${goal.status || "open"}). Propose the single most valuable and concrete ` +
      `NEXT step to move it forward. Return a single JSON object with a “reply” (a one-line explanation) ` +
      `and “proposal_v1” (an object or array) describing that next step as a proposal. Choose only work ` +
      `types you are permitted to create. Use the provided project for parent ids; do not invent other ` +
      `ids. If you have no constructive next step, return proposal_v1 as null.`
    ).trim();
    const payload: any = { task, work_intent: true, project_id: pid };
    if (wid) payload.workspace_id = wid;
    if (proj?.name) payload.project_name = proj.name;
    const ws = workspaces.find((x) => x.id === wid);
    if (ws?.name) payload.workspace_name = ws.name;
    setNextStepBusy(goal.id);
    setNextStepResult(null);
    try {
      const r = await fetch(`${API}/agents/strategist/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setNextStepResult({ goalId: goal.id, msg: (b as any).detail || `Could not run (${r.status}).` });
        return;
      }
      const saved = ((b as any).proposal_results || [])
        .filter((s: any) => s && s.status === "saved").length;
      const proposed = ((b as any).proposals || []).length || saved;
      setNextStepResult({
        goalId: goal.id,
        msg: proposed
          ? `Proposed ${saved || proposed} next-step idea(s) for review — approve them in Work · Approvals.`
          : (b as any).generation_error
            ? "Generation unavailable right now. Try again in a moment."
            : "The agent had no constructive next step this time.",
      });
      await loadFeed();
    } catch {
      setNextStepResult({ goalId: goal.id, msg: "Could not run. Please try again." });
    } finally {
      setNextStepBusy(null);
    }
  };

  // Step 5: human-confirmed delegation. The user explicitly chooses which
  // teammate should own this goal's work; the system files an ASSIGNMENT
  // proposal (never an automatic assignment). Approving it in Work creates the
  // assignment on the goal, which the D4.1 flow can then execute with evidence.
  const proposeAssignment = async (goal: any) => {
    if (offline || assignBusy || !assignOwner) return;
    const payload: any = { goal_id: goal?.id, agent_id: assignOwner, priority: 0 };
    setAssignBusy(goal.id);
    setAssignMsg(null);
    try {
      const r = await fetch(`${API}/work/proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          work_type: "assignment",
          action: "create",
          payload,
          agent_id: "strategist",
        }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAssignMsg({ goalId: goal.id, msg: (b as any).detail || `Could not propose (${r.status}).` });
        return;
      }
      setAssignMsg({
        goalId: goal.id,
        msg: "Assignment proposal filed — approve it in Work · Approvals to assign the teammate.",
      });
      setAssignOpenGoal(null);
      setAssignOwner("");
      await loadFeed();
    } catch {
      setAssignMsg({ goalId: goal.id, msg: "Could not propose. Please try again." });
    } finally {
      setAssignBusy(null);
    }
  };

  // D4.3-A1: unified command. Send one objective to the coordinating agent and
  // render a reviewable team plan. Preview only: the backend creates no proposal,
  // record, or execution; nothing happens until a future approval step.
  const requestPlan = async () => {
    if (offline || planBusy || !planObjective.trim()) return;
    const pid = selectedProjectId || projects[0]?.id || undefined;
    const wid = selectedWorkspaceId || workspaces[0]?.id || undefined;
    setPlanBusy(true);
    setPlanError(null);
    setPlanResult(null);
    setPlanNotice(null);
    try {
      const r = await fetch(`${API}/agents/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective: planObjective.trim(), project_id: pid, workspace_id: wid }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setPlanError((b as any).detail || `Could not generate a plan (${r.status}).`);
        return;
      }
      if ((b as any).generation_error) {
        const code = (b as any).generation_error.code;
        setPlanError(
          code === "model_empty"
            ? "No useful steps were generated this time. Try again."
            : "The AI team is temporarily unavailable. Try again."
        );
        return;
      }
      if (!((b as any).steps || []).length) {
        setPlanNotice("The team didn't produce constructive steps yet. Refine the objective and try again.");
      }
      setPlanResult(b);
    } catch {
      setPlanError("Could not reach the AI team. Please try again.");
    } finally {
      setPlanBusy(false);
    }
  };

  const agentDisplay = (slug: string | null | undefined) => {
    return agents.find((a) => a.name === slug)?.display_name || humanize(slug || "");
  };

  // --- D4.3-A2: editable plan review + approval bridge to /work/proposals. ---
  const updatePlanStep = (i: number, patch: any) => {
    if (!planResult) return;
    setPlanResult((prev: any) => {
      if (!prev) return prev;
      const steps = (prev.steps || []).map((s: any, idx: number) =>
        idx === i ? { ...s, ...patch } : s);
      return { ...prev, steps };
    });
  };

  const planOwnerOptions = (step: any) => {
    if (step.agent_options && step.agent_options.length) return step.agent_options;
    return agents.map((a) => a.name);
  };

  // Work types the A2 bridge can turn into proposals via /work/proposals.
  // goal_update / deliverable_version (and any non-create action) are shown as
  // unsupported rather than erroring at approve time.
  const planTypeSupported = (step: any) =>
    (step.action || "create") === "create" &&
    ["workspace", "project", "goal", "deliverable", "assignment"].includes(step.work_type);

  // Build the exact /work/proposals payload for a finalized step, or null when the
  // step cannot yet be bridged (e.g. assignment with no target goal, or an update
  // type outside A2's create-only bridge). The shared endpoint re-validates
  // ownership, parent-per-work-type, and idempotency server-side.
  const buildStepProposal = (step: any) => {
    const wt = step.work_type;
    if ((step.action || "create") !== "create") return null;
    const title = (step.title || "").trim();
    const pid = step.project_id || selectedProjectId || projects[0]?.id;
    const wid = step.workspace_id || selectedWorkspaceId || workspaces[0]?.id;
    const owner = step.owner || step.suggested_agent || "workspace_architect";
    let payload: any = null;
    if (wt === "workspace") {
      payload = { name: title };
    } else if (wt === "project") {
      if (!wid) return null;
      payload = { workspace_id: wid, name: title };
    } else if (wt === "goal") {
      if (!pid) return null;
      payload = { project_id: pid, title };
    } else if (wt === "deliverable") {
      if (!pid) return null;
      payload = { project_id: pid, title };
    } else if (wt === "assignment") {
      const gid = step.goal_id;
      if (!gid) return null;
      payload = { goal_id: gid, agent_id: owner, priority: 0 };
    } else {
      return null; // goal_update / deliverable_version etc. not bridged in A2
    }
    return { work_type: wt, action: "create", payload, agent_id: owner };
  };

  const doApprovePlanStep = async (i: number) => {
    const step = planResult?.steps?.[i];
    if (!step) return;
    const built = buildStepProposal(step);
    if (!built) {
      updatePlanStep(i, {
        error: "Can't propose this yet — add a target (goal/parent) or choose a supported type.",
      });
      return;
    }
    setPlanFiling(i);
    updatePlanStep(i, { approved: false, rejected: false, msg: null, error: null });
    try {
      const r = await fetch(`${API}/work/proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(built),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        updatePlanStep(i, { error: (b as any)?.detail || `Could not propose (${r.status}).` });
        return;
      }
      updatePlanStep(i, {
        approved: true,
        msg: (b as any)?.reused
          ? "Already proposed before — review it in Work · Approvals."
          : "Proposed for your approval — review in Work · Approvals.",
      });
      await loadFeed();
    } catch {
      updatePlanStep(i, { error: "Could not file this step. Try again." });
    } finally {
      setPlanFiling(null);
    }
  };

  const approvePlanStep = (i: number) => {
    if (planFiling !== null) return;
    doApprovePlanStep(i);
  };

  const rejectPlanStep = (i: number) => {
    if (planFiling !== null) return;
    updatePlanStep(i, { rejected: true, approved: false, msg: "Rejected — not proposed.", error: null });
  };

  const removePlanStep = (i: number) => {
    if (planFiling !== null) return;
    setPlanResult((prev: any) => {
      if (!prev) return prev;
      return { ...prev, steps: (prev.steps || []).filter((_: any, idx: number) => idx !== i) };
    });
  };

  const approveAllPlan = async () => {
    const steps = planResult?.steps || [];
    const idxs = steps
      .map((_: any, i: number) => i)
      .filter((i: number) => !steps[i].approved && !steps[i].rejected && !steps[i].error);
    if (!idxs.length || planFiling !== null || planAllBusy) return;
    setPlanAllBusy(true);
    setPlanAllMsg(null);
    for (const i of idxs) {
      await doApprovePlanStep(i);
    }
    setPlanAllBusy(false);
    setPlanAllMsg(idxs.length ? "Plan submitted for approval — review each step in Work · Approvals." : "");
  };

  // Shared POST handler. `payload.retry` tells the backend not to persist a
  // duplicate user message for an already-saved task. It never repeats
  // consequential tool calls, proposals, or execution.
  const performRun = async (submitted: string, payload: any) => {
    try {
      const r = await fetch(`${API}/agents/${selectedAgent}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const code = (body as any).detail || `request failed (${r.status})`;
        // Generic friendly 5xx message: never surface raw backend exception text.
        if (r.status >= 500) {
          setAgentError("The agent couldn\u2019t complete the request right now. Please try again.");
        } else if (r.status === 422) {
          setAgentError("The response couldn\u2019t be validated by the safety checks, so nothing was used. Please try again.");
        } else if (r.status === 403) {
          setAgentError("That action isn\u2019t allowed. Please try again.");
        } else {
          // Meaningful 4xx detail (e.g. not found) is preserved.
          setAgentError(code);
        }
        setTask(submitted); // preserve the message on a rejected submission
        setAgentGenError(null);
      } else {
        // Record a structured generation failure (if any) for the failure panel
        // and one-click retry, without losing the honest reply body below.
        if (body.generation_error) {
          setAgentGenError(body.generation_error);
          setAgentRetryTask(submitted);
          setAgentRetryThread(body.thread_id || null);
        } else {
          setAgentGenError(null);
        }
        // Reliable Option-A fallback: if this was a workspace-creation request
        // and the agent did NOT actually save a proposal, offer to propose the
        // workspace for approval deterministically (independent of model JSON).
        if (WS_INTENT_RE.test(submitted) && !((body.proposals as any[]) || []).length) {
          setWsPrompt({ task: submitted, threadId: body.thread_id || null });
          setWsProposed(false);
        } else {
          setWsPrompt(null);
        }
        // If this run continues the currently-open saved conversation, append the
        // new turns to its transcript instead of replacing the last reply.
        const continuing = Boolean(openThreadId) && body.thread_id === openThreadId;
        if (continuing) {
          setTranscript((prev) => [
            ...prev,
            { role: "user", content: submitted, created_at: new Date().toISOString() },
            { role: "assistant", content: body.reply || "", created_at: new Date().toISOString() },
          ]);
        } else {
          setAgentResult(body);
        }
        if (body.thread_id) {
          setThreadIds((prev) => ({ ...prev, [selectedAgent]: body.thread_id }));
        }
        if (typeof body.context_messages === "number") {
          setContextCounts((prev) => ({ ...prev, [selectedAgent]: body.context_messages }));
        }
        loadConvos();
      }
    } catch (e: any) {
      setAgentError(e?.message || "network error");
      setTask(submitted); // preserve the message on a network failure
      setAgentGenError(null);
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
    setAgentGenError(null);
    setAgentRetryTask(null);
    setAgentRetryThread(null);
    setWsPrompt(null);
    setWsProposed(false);
    setWsError("");
    setTask("");
    // Start fresh: stop viewing an opened transcript (saved conversations are
    // never deleted or altered by New Conversation).
    setOpenThreadId(null);
    setTranscript([]);
    loadConvos();
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
    const title = wsProjName.trim() || "New Project";
    await fetch(`${API}/workspaces/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: wid, name: title }),
    });
    setWsProjName("");
    refresh();
  };

  const createGoal = async () => {
    const pid = selectedProjectId || projects[0]?.id;
    if (offline || !pid) return;
    const title = wsGoalName.trim() || "New Goal";
    await fetch(`${API}/workspaces/goals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: pid, title, priority: 1 }),
    });
    setWsGoalName("");
    refresh();
  };

  const createDeliverable = async () => {
    const pid = selectedProjectId || projects[0]?.id;
    if (offline || !pid) return;
    const title = wsDelivName.trim() || "New Deliverable";
    const r = await fetch(`${API}/workspaces/deliverables`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: pid, title }),
    });
    const d = await r.json();
    if (d.id) {
      await fetch(`${API}/workspaces/deliverables/${d.id}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: "v1 content" }),
      });
    }
    setWsDelivName("");
    refresh();
  };

  const loadVersions = async (did: string) => {
    setSelectedDeliverable(did);
    try {
      const r = await fetch(`${API}/workspaces/deliverables/${did}/versions`);
      if (!r.ok) {
        setVersionError("Could not refresh deliverable versions.");
        return;
      }
      const d = await r.json();
      setVersions(d.items || []);
      setVersionError(null);
    } catch {
      setVersionError("Could not refresh deliverable versions.");
    }
  };

  const confirmApprove = async (vid: string) => {
    if (offline) return;
    setVersionError(null);
    try {
      const r = await fetch(`${API}/workspaces/versions/${vid}/approve`, { method: "POST" });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        setVersionError((b as any).detail || `Approve failed (${r.status}).`);
        return; // keep prompt open; do not imply success
      }
      setApprovingVersion(null);
      if (selectedDeliverable) loadVersions(selectedDeliverable);
    } catch {
      setVersionError("Approve failed. Please try again.");
    }
  };

  const submitReject = async (vid: string) => {
    if (offline) return;
    const reason = rejectReason.trim() || "Requested revision";
    setVersionError(null);
    try {
      const r = await fetch(`${API}/workspaces/versions/${vid}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        setVersionError((b as any).detail || `Reject failed (${r.status}).`);
        return; // keep prompt open + reason; do not imply success
      }
      setRejectingVersion(null);
      setRejectReason("");
      if (selectedDeliverable) loadVersions(selectedDeliverable);
    } catch {
      setVersionError("Reject failed. Please try again.");
    }
  };

  // --- M10 Phase D1: approvals feed + linked-work navigation ---
  const loadFeed = async () => {
    try {
      const r = await fetch(`${API}/work/feed`);
      if (!r.ok) return;
      const d = await r.json();
      setFeed(d.items || []);
    } catch { /* offline or backend unavailable */ }
  };

  const loadThreadLinks = async (threadId: string | null) => {
    setThreadLinks([]);
    if (!threadId) return;
    try {
      const r = await fetch(`${API}/work/links?thread_id=${encodeURIComponent(threadId)}`);
      if (!r.ok) return;
      const d = await r.json();
      setThreadLinks(d.items || []);
    } catch { /* offline or backend unavailable */ }
  };

  const loadWorkThreads = async (wtype: string, wid: string) => {
    const key = `${wtype}:${wid}`;
    if (workThreads[key]) return; // already loaded
    try {
      const r = await fetch(`${API}/work/links/work/${encodeURIComponent(wtype)}/${encodeURIComponent(wid)}`);
      if (!r.ok) return;
      const d = await r.json();
      setWorkThreads((prev) => ({ ...prev, [key]: d.threads || [] }));
    } catch { /* offline or backend unavailable */ }
  };

  const approveProposal = async (id: string) => {
    if (offline || proposalBusy) return;
    setProposalBusy(id);
    setProposalError(null);
    try {
      const r = await fetch(`${API}/work/proposals/${id}/approve`, { method: "POST" });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setProposalError((b as any).detail || `Approve failed (${r.status}).`);
        return; // keep pending; do not imply success
      }
      await loadFeed();
      refresh();
    } catch {
      setProposalError("Approve failed. Please try again.");
    } finally {
      setProposalBusy(null);
    }
  };

  // Step 2: approve every currently-pending proposal in one human gesture. Each
  // proposal still passes through the same authoritative approve endpoint and is
  // created only after this explicit action; results are summarized honestly.
  const approveAllPending = async () => {
    const pending = (feed || []).filter((p) => p && p.status === "proposed");
    if (offline || allApproving || !pending.length) return;
    setAllApproving(true);
    setAllApproveMsg(null);
    setProposalError(null);
    let ok = 0;
    const failures: string[] = [];
    for (const p of pending) {
      try {
        const r = await fetch(`${API}/work/proposals/${p.id}/approve`, { method: "POST" });
        if (r.ok) ok += 1;
        else failures.push(p.id);
      } catch {
        failures.push(p.id);
      }
    }
    setAllApproving(false);
    await loadFeed();
    refresh();
    setAllApproveMsg(
      failures.length === 0
        ? `Approved ${ok} proposal(s). Approved records now appear in their workspace.`
        : `Approved ${ok}, failed ${failures.length}.`
    );
  };

  const pfBuildPayload = (): any => {
    const name = pfName.trim();
    switch (pfType) {
      case "workspace": return { name };
      case "project": return { workspace_id: pfWorkspace, name };
      case "goal": return { project_id: pfProject, title: name, priority: Number(pfPriority) || 0 };
      case "assignment": return { goal_id: pfGoal, agent_id: pfAgent };
      case "deliverable": return { project_id: pfProject, title: name };
      case "deliverable_version": return { content: name };
      case "goal_update": {
        const p: any = {};
        if (name) p.title = name;
        if (pfStatus) p.status = pfStatus;
        if (pfProgress !== "") p.progress = Number(pfProgress);
        return p;
      }
      default: return {};
    }
  };

  // Create a deterministic proposal (no AI-model dependency). Only a proposal is
  // stored; a human approves it in Approvals, which then creates the real record.
  const proposeWork = async () => {
    if (offline || pfBusy) return;
    if (pfType === "project" && !pfWorkspace) return setPfMsg("Choose a parent workspace.");
    if ((pfType === "goal" || pfType === "deliverable") && !pfProject) return setPfMsg("Choose a parent project.");
    if (pfType === "assignment" && !pfGoal) return setPfMsg("Choose a target goal.");
    if (pfType === "goal_update" && !pfGoal) return setPfMsg("Choose a target goal.");
    if (pfType === "deliverable_version" && !pfDeliverable) return setPfMsg("Choose a target deliverable.");
    setPfBusy(true);
    setPfMsg("");
    const payload = pfBuildPayload();
    const target_id = pfType === "goal_update" ? pfGoal : pfType === "deliverable_version" ? pfDeliverable : undefined;
    const action = pfType === "goal_update" ? "update" : "create";
    try {
      const r = await fetch(`${API}/work/proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ work_type: pfType, action, payload, target_id, agent_id: pfAuthor }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setPfMsg((b as any).detail || `Could not create the proposal (${r.status}).`);
        return;
      }
      setPfMsg("Proposal created — approve it below, then it appears in the sections.");
      setPfName("");
      await loadFeed();
    } catch {
      setPfMsg("Could not create the proposal. Please try again.");
    } finally {
      setPfBusy(false);
    }
  };

  // Phase 1: promote an agent's idea draft (free text) into a real, approvable
  // proposal via the deterministic workflow endpoint. Only a proposal is stored;
  // a human still approves it in the Work tab before any real record is created.
  const chatPropose = async () => {
    if (offline || draftBusy) return;
    const title = (draftTitle || "").trim();
    if (!title) return setDraftMsg("Give this idea a short title first.");
    const wtype = draftType;
    const pid = selectedProjectId || projects[0]?.id;
    const wid = selectedWorkspaceId || workspaces[0]?.id;
    const payload: any = {};
    if (wtype === "project") {
      if (!wid) return setDraftMsg("Choose a parent workspace first (Workspace page).");
      payload.workspace_id = wid;
      payload.name = title;
    } else {
      if (!pid) return setDraftMsg("Choose a parent project first (Work page).");
      payload.project_id = pid;
      if (wtype === "goal" || wtype === "deliverable") {
        payload.title = title;
      } else if (wtype === "assignment") {
        const gid = draftGoal || goalsIn(pid)[0]?.id;
        if (!gid) return setDraftMsg("This project has no goal to attach the assignment to.");
        payload.goal_id = gid;
        payload.agent_id = selectedAgent || "workspace_architect";
      }
    }
    setDraftBusy(true);
    setDraftMsg(null);
    try {
      const r = await fetch(`${API}/work/proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ work_type: wtype, action: "create", payload, agent_id: selectedAgent || "workspace_architect" }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setDraftMsg((b as any)?.detail || `Could not create the proposal (${r.status}).`);
        return;
      }
      setDraftMsg("Proposal created \u2014 approve it below and it appears in the workspace.");
      setDraftOpen(false);
      setDraftTitle("");
      setDraftGoal("");
      setAgentResult((prev: any) => (prev ? { ...prev, draftProposed: true } : prev));
      await loadFeed();
    } catch {
      setDraftMsg("Could not create the proposal. Please try again.");
    } finally {
      setDraftBusy(false);
    }
  };

  const rejectProposal = async (id: string) => {
    if (offline || proposalBusy) return;
    setProposalBusy(id);
    setProposalError(null);
    try {
      const r = await fetch(`${API}/work/proposals/${id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Declined by user" }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setProposalError((b as any).detail || `Reject failed (${r.status}).`);
        return;
      }
      await loadFeed();
    } catch {
      setProposalError("Reject failed. Please try again.");
    } finally {
      setProposalBusy(null);
    }
  };

  const openOriginatingThread = (t: any) => {
    const agentId = t.agent_id || selectedAgent || "strategist";
    if (t.agent_id) setSelectedAgent(t.agent_id);
    setTab("agents");
    setOpenThreadId(t.thread_id);
    setThreadIds((prev) => ({ ...prev, [agentId]: t.thread_id }));
    setTranscript([]);
    (async () => {
      try {
        const r = await fetch(`${API}/memory/conversation?thread_id=${encodeURIComponent(t.thread_id)}`);
        const d = await r.json();
        setTranscript((d.items || []).map((m: any) => ({ role: m.role, content: m.content, created_at: m.created_at })));
        loadThreadLinks(t.thread_id);
      } catch { /* offline or backend unavailable */ }
    })();
  };

  const focusWorkItem = (work_type: string, work_id: string) => {
    setTab("work");
    loadFeed();
    setSelectedGoal(null);
    setSelectedAssignment(null);
    setSelectedDeliverable(null);
    if (work_type === "project") {
      const p = projects.find((x) => x.id === work_id);
      if (p) { setSelectedWorkspaceId(p.workspace_id ?? null); setSelectedProjectId(work_id); }
      return;
    }
    if (work_type === "goal" || work_type === "goal_update") {
      const g = goals.find((x) => x.id === work_id);
      if (g) {
        const p = projects.find((x) => x.id === g.project_id);
        setSelectedWorkspaceId(p ? p.workspace_id ?? null : null);
        setSelectedProjectId(g.project_id);
        setSelectedGoal(work_id);
      }
      return;
    }
    if (work_type === "assignment") {
      const a = assignments.find((x) => x.id === work_id);
      if (a) {
        const g = goals.find((x) => x.id === a.goal_id);
        const p = g ? projects.find((x) => x.id === g.project_id) : undefined;
        setSelectedWorkspaceId(p ? p.workspace_id ?? null : null);
        if (g) setSelectedProjectId(g.project_id);
        setSelectedGoal(a.goal_id);
        setSelectedAssignment(work_id);
      }
      return;
    }
    if (work_type === "deliverable" || work_type === "deliverable_version") {
      const d = deliverablesList.find((x) => x.id === work_id);
      const targetId = d ? d.id : work_id;
      const dp = deliverablesList.find((x) => x.id === targetId);
      if (dp) {
        const p = projects.find((x) => x.id === dp.project_id);
        setSelectedWorkspaceId(p ? p.workspace_id ?? null : null);
        setSelectedProjectId(dp.project_id);
        setSelectedDeliverable(targetId);
      }
    }
  };

  // --- M10 Phase D2: human-operated execution tracking (evidence-gated) ---
  const startExecution = async (work_type: string, work_id: string, agent_id: string) => {
    if (offline || execBusy) return;
    const key = `${work_type}:${work_id}`;
    setExecBusy(key);
    setExecError(null);
    try {
      const r = await fetch(`${API}/work/${encodeURIComponent(work_type)}/${encodeURIComponent(work_id)}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setExecError((b as any).detail || `Could not start execution (${r.status}).`);
        return;
      }
      setWorkEpisodes((prev) => ({ ...prev, [key]: b }));
      refresh();
    } catch {
      setExecError("Could not start execution. Please try again.");
    } finally {
      setExecBusy(null);
    }
  };

  const submitCheckpoint = async (eid: string) => {
    if (offline) return;
    const progress = Number(cpProgress);
    const summary = cpEvidence.trim();
    if (!summary) { setEpError("Evidence summary is required."); return; }
    if (!Number.isFinite(progress) || progress < 0 || progress > 1) {
      setEpError("Progress must be a number between 0 and 1."); return;
    }
    setEpError(null);
    try {
      const r = await fetch(`${API}/episodes/${eid}/checkpoint`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ progress, evidence: { summary } }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) { setEpError((b as any).detail || `Checkpoint failed (${r.status}).`); return; }
      setCpEvidence("");
      loadEpisode(eid);
      refresh();
    } catch {
      setEpError("Checkpoint failed. Please try again.");
    }
  };

  const submitComplete = async (eid: string) => {
    if (offline) return;
    const summary = completeEvidence.trim();
    if (!summary) { setEpError("Completion evidence is required."); return; }
    setEpError(null);
    try {
      const r = await fetch(`${API}/episodes/${eid}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evidence: { summary } }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) { setEpError((b as any).detail || `Complete failed (${r.status}).`); return; }
      setCompleteEvidence("");
      loadEpisode(eid);
      refresh();
    } catch {
      setEpError("Complete failed. Please try again.");
    }
  };

  // --- M10 Phase D3: evidence-backed goal application + execution history ---
  const loadWorkExec = async (work_type: string, work_id: string) => {
    const key = `${work_type}:${work_id}`;
    if (workExec[key]) return; // already loaded
    try {
      const r = await fetch(`${API}/work/${encodeURIComponent(work_type)}/${encodeURIComponent(work_id)}/execution`);
      if (!r.ok) return;
      const d = await r.json();
      setWorkExec((prev) => ({ ...prev, [key]: d }));
    } catch { /* offline or backend unavailable */ }
  };

  const submitApply = async (episode_id: string) => {
    if (offline || applyingEid) return;
    setApplyingEid(episode_id);
    setApplyError(null);
    try {
      const r = await fetch(`${API}/episodes/${episode_id}/apply`, { method: "POST" });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setApplyError((b as any).detail || `Apply failed (${r.status}).`);
        return; // keep confirmation open; do not imply success
      }
      setApplyEid(null);
      loadEpisode(episode_id);
      refresh();
      setWorkExec({}); // force exec history refresh on next open
    } catch {
      setApplyError("Apply failed. Please try again.");
    } finally {
      setApplyingEid(null);
    }
  };

  // --- M10 Phase D4.1: approved-assignment execution (human-confirmed) ---
  const startApprovedExecution = async (aid: string, agentId: string) => {
    if (offline || execBusy) return;
    const key = `assignment:${aid}`;
    setExecBusy(key);
    setExecError(null);
    setConfirmExec(null);
    try {
      const r = await fetch(`${API}/work/assignment/${aid}/execute-approved`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: agentId }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setExecError((b as any).detail || `Could not start execution (${r.status}).`);
        return;
      }
      setWorkEpisodes((prev) => ({ ...prev, [key]: b }));
      refresh();
    } catch {
      setExecError("Could not start execution. Please try again.");
    } finally {
      setExecBusy(null);
    }
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

  // Jump to a project (or goal) detail from the Overview tab.
  const goToProject = (pid: string) => {
    const p = projects.find((x) => x.id === pid);
    setTab("workspace");
    setSelectedDeliverable(null);
    setSelectedGoal(null);
    setSelectedProjectId(pid || null);
    setSelectedWorkspaceId(p ? p.workspace_id : null);
  };
  const goToGoal = (gid: string) => {
    const g = goals.find((x) => x.id === gid);
    const p = g ? projects.find((x) => x.id === g.project_id) : undefined;
    setTab("workspace");
    setSelectedDeliverable(null);
    setSelectedGoal(gid);
    setSelectedProjectId(p ? p.id : null);
    setSelectedWorkspaceId(p ? p.workspace_id : null);
  };

  const projectsIn = (wid: string) => visibleOnly(projects.filter((p) => p.workspace_id === wid));
  const goalsIn = (pid: string) => visibleOnly(goals.filter((g) => g.project_id === pid));
  const deliverablesIn = (pid: string) => visibleOnly(deliverablesList.filter((d) => d.project_id === pid));
  const assignmentsIn = (pid: string) => {
    const goalIds = new Set(visibleOnly(goals).filter((g) => g.project_id === pid).map((g) => g.id));
    return visibleOnly(assignments.filter((a) => goalIds.has(a.goal_id)));
  };
  const agentLabel = (slug: string) => {
    const a = agents.find((x) => x.name === slug);
    return a ? a.display_name || humanize(a.name) : humanize(slug);
  };
  const agentArchetype = (slug: string) => agents.find((x) => x.name === slug)?.archetype || "";
  const titleOfGoal = (gid: string) => goals.find((g) => g.id === gid)?.title || gid;
  const workspaceName = (wid: string) => workspaces.find((w) => w.id === wid)?.name || "Unknown workspace";
  const openGoals = visibleOnly(goals).filter((g) => g.status !== "done" && g.status !== "cancelled");
  const recentProjects = [...visibleOnly(projects)]
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
    .slice(0, 5);
  const visibleWorkspaces = visibleOnly(workspaces);
  const visibleEpisodes = visibleOnly(episodes);
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

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
            <p className="brand__tagline">Your six AI teammates, on your own device</p>
          </div>
        </div>
        <div className="status">
          <span className={`status__dot status__dot--${status}`} />
          <span className="status__label">
            {status === "checking" ? "Connecting…" : status === "online" ? "Connected" : "Offline"}
          </span>
          <span className="status__chip">On-device · Ollama</span>
        </div>
      </header>

      {offline && (
        <div className="banner">
          You&apos;re offline — read-only mode. Writes are disabled until the connection returns.
        </div>
      )}

      <div className="sample-bar">
        <button className="btn btn--ghost btn--sm" onClick={toggleAllSamples}>
          {sampleDataVisible ? "Hide sample data" : "Show sample data"}
        </button>
        <button className="btn btn--ghost btn--sm" onClick={() => setManageSamples(true)}>
          Manage samples
        </button>
        <span className="sample-bar__hint">
          {sampleDataVisible
            ? "Showing all records, including sample data."
            : "Sample/test data is hidden. Your own records are never hidden."}
        </span>
      </div>

      <nav className="nav" aria-label="Sections">
        {NAV.map((n) => (
          <button
            key={n.id}
            data-route={n.id}
            className={`nav__btn${tab === n.id ? " nav__btn--active" : ""}`}
            onClick={() => { setTab(n.id); if (n.id === "work") loadFeed(); }}
            aria-label={n.label}
          >
            <Icon name={n.icon} />
            <span className="nav__label">{n.label}</span>
          </button>
        ))}
      </nav>

      {manageSamples && (
        <div className="sample-manage" role="dialog" aria-label="Manage sample data">
          <div className="sample-manage__head">
            <h3>Manage sample data</h3>
            <div className="sample-manage__actions">
              <button className="btn btn--ghost btn--sm" onClick={() => resetRevealed()}>
                Reset reveals
              </button>
              <button className="btn btn--ghost btn--sm" onClick={() => setManageSamples(false)}>
                Close
              </button>
            </div>
          </div>
          <p className="sample-manage__hint">
            Sample records stay in your database — hiding here is a view-only preference.
          </p>
          <ul className="list">
            {visibleOnly(workspaces).filter((w) => KNOWN_SAMPLE_IDS.has(w.id)).length === 0 ? (
              <li className="list__item"><span className="list__name">No hidden workspaces.</span></li>
            ) : (
              visibleOnly(workspaces)
                .filter((w) => KNOWN_SAMPLE_IDS.has(w.id))
                .map((w) => (
                  <li key={w.id} className="list__item">
                    <span className="list__name">{w.name}</span>
                    <button className="btn btn--ghost btn--sm" onClick={() => revealSample(w.id)}>
                      Keep visible
                    </button>
                  </li>
                ))
            )}
          </ul>
        </div>
      )}

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
              <Stat icon="grid" label="Workspaces" value={visibleWorkspaces.length} />
              <Stat icon="briefcase" label="Projects" value={visibleOnly(projects).length} />
              <Stat icon="target" label="Open goals" value={openGoals.length} />
              <Stat icon="checklist" label="Assignments" value={visibleOnly(assignments).length} />
              <Stat icon="file" label="Deliverables" value={visibleOnly(deliverablesList).length} />
            </div>

            {/* D4.3-B: coordinated status — one assistant view of what awaits you. */}
            {(() => {
              const pendingApprovals = (feed || []).filter((p) => p && p.status === "proposed").length;
              const runningEps = (episodes || []).filter((e) => e && e.status === "running").length;
              const doneEps = (episodes || []).filter((e) => e && e.status === "done").length;
              const ownedBy: Record<string, number> = {};
              (assignments || []).forEach((a: any) => {
                ownedBy[a.agent_id || "?"] = (ownedBy[a.agent_id || "?"] || 0) + 1;
              });
              return (
                <div className="coord-status" data-testid="coord-status">
                  <div className="coord-status__head">
                    <h3 className="section-title">Your AI team right now</h3>
                    <span className="muted">Nothing runs automatically — every action below waits on you.</span>
                  </div>
                  <div className="coord-status__rows">
                    <div className="coord-status__item">
                      <span className="coord-status__label">Awaiting your approval</span>
                      <span className="coord-status__value" data-testid="coord-pending">{pendingApprovals}</span>
                      {pendingApprovals > 0 && (
                        <button className="btn btn--sm btn--ghost" data-testid="coord-goto-work" onClick={() => { setTab("work"); loadFeed(); }}>
                          Review proposals
                        </button>
                      )}
                    </div>
                    <div className="coord-status__item">
                      <span className="coord-status__label">Work in progress (needs your evidence)</span>
                      <span className="coord-status__value" data-testid="coord-running">{runningEps}</span>
                      {runningEps > 0 && (
                        <button className="btn btn--sm btn--ghost" onClick={() => setTab("episodes")}>
                          View activity
                        </button>
                      )}
                    </div>
                    <div className="coord-status__item">
                      <span className="coord-status__label">Completed episodes</span>
                      <span className="coord-status__value" data-testid="coord-done">{doneEps}</span>
                    </div>
                    <div className="coord-status__item coord-status__team">
                      <span className="coord-status__label">Team workload (assignments by owner)</span>
                      <div className="coord-status__chips">
                        {Object.keys(ownedBy).length === 0 && <span className="muted">No assignments yet.</span>}
                        {Object.entries(ownedBy).map(([slug, n]) => (
                          <span key={slug} className="chip" data-testid={`coord-owner-${slug}`}>
                            {agentDisplay(slug)} · {n}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}

            {visibleWorkspaces.length === 0 ? (
              <Empty text="No workspaces yet. Open the Workspaces section to create your first workspace and start organizing projects." />
            ) : (
              <div className="overview-grid">
                <div className="overview-col">
                  <h3 className="section-title">Recent projects</h3>
                  {recentProjects.length === 0 ? (
                    <Empty text="No projects yet — create one inside a workspace." />
                  ) : (
                    <ul className="list">
                      {recentProjects.map((p) => (
                        <li
                          key={p.id}
                          className="list__item list__item--clickable"
                          onClick={() => goToProject(p.id)}
                        >
                          <span className="list__icon"><Icon name="briefcase" size={16} /></span>
                          <span className="list__name">{p.name}</span>
                          <span className="badge badge--faint">{workspaceName(p.workspace_id)}</span>
                          <span className={`badge badge--${p.status || "neutral"}`}>{statusLabel(p.status)}</span>
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
                        <li
                          key={g.id}
                          className="list__item list__item--clickable"
                          onClick={() => goToGoal(g.id)}
                        >
                          <span className="list__icon"><Icon name="target" size={16} /></span>
                          <span className="list__name">{g.title}</span>
                          <span className={`badge badge--${g.status || "open"}`}>{statusLabel(g.status)}</span>
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
              (visibleWorkspaces.length === 0 ? (
                <Empty text="No workspaces yet — create one above to get started." />
              ) : (
                <ul className="list">
                  {visibleWorkspaces.map((w) => (
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
                      <span className="badge badge--neutral">{plural(projectsIn(w.id).length, "project")}</span>
                    </li>
                  ))}
                </ul>
              ))}

            {selectedWorkspaceId && !selectedProjectId && (
              <div className="subsection">
                <div className="subsection__head">
                  <h3 className="section-title">Projects</h3>
                  <input
                    className="input"
                    placeholder="Project name…"
                    style={{ width: 180 }}
                    value={wsProjName}
                    onChange={(e) => setWsProjName(e.target.value)}
                    data-testid="ws-project-name"
                  />
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
                        <span className="badge badge--neutral">{plural(goalsIn(p.id).length, "goal")}</span>
                        <span className={`badge badge--${p.status || "neutral"}`}>{statusLabel(p.status)}</span>
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
                          {plural(pGoals.length, "goal")} · {plural(pAssignments.length, "assignment")} · {plural(pDeliverables.length, "deliverable")}
                        </p>
                      </div>
                      <span className={`badge badge--${p?.status || "neutral"}`}>{statusLabel(p?.status)}</span>
                    </div>

                    <h4 className="subsection-title">Goals</h4>
                    {pGoals.length === 0 ? (
                      <Empty text="No goals for this project yet." />
                    ) : (
                      <ul className="list">
                        {pGoals.map((g) => (
                          <li
                            key={g.id}
                            className={`list__item list__item--clickable${selectedGoal === g.id ? " list__item--selected" : ""}`}
                            onClick={() => setSelectedGoal(selectedGoal === g.id ? null : g.id)}
                          >
                            <span className="list__icon"><Icon name="target" size={16} /></span>
                            <span className="list__name">{g.title}</span>
                            <span className={`badge badge--${g.status || "open"}`}>{statusLabel(g.status)}</span>
                            <span className="goal-actions">
                              <button
                                className="btn btn--ghost btn--sm"
                                data-testid={`suggest-next-${g.id}`}
                                disabled={offline || nextStepBusy !== null || nextStepBusy === g.id}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  suggestNextStep(g);
                                }}
                                title="Have Aisha propose the next step for this goal (as a proposal you approve)"
                              >
                                {nextStepBusy === g.id ? "Thinking…" : "✨ Suggest next step"}
                              </button>
                              <button
                                className="btn btn--ghost btn--sm"
                                data-testid={`assign-open-${g.id}`}
                                disabled={offline || assignBusy !== null || assignBusy === g.id}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setAssignMsg(null);
                                  setAssignOpenGoal(assignOpenGoal === g.id ? null : g.id);
                                }}
                                title="Assign this goal's work to a teammate (as an approval-gated proposal)"
                              >
                                👥 Assign to teammate
                              </button>
                            </span>
                            {assignOpenGoal === g.id && (
                              <span
                                className="assign-panel"
                                data-testid={`assign-panel-${g.id}`}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <select
                                  value={assignOwner}
                                  data-testid={`assign-owner-${g.id}`}
                                  onChange={(e) => setAssignOwner(e.target.value)}
                                >
                                  <option value="">Pick a teammate…</option>
                                  {agents.map((a) => (
                                    <option key={a.name} value={a.name}>
                                      {a.display_name || humanize(a.name)}
                                    </option>
                                  ))}
                                </select>
                                <button
                                  className="btn btn--sm btn--primary"
                                  data-testid={`assign-submit-${g.id}`}
                                  disabled={assignBusy !== null || !assignOwner}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    proposeAssignment(g);
                                  }}
                                >
                                  {assignBusy === g.id ? "Filing…" : "Propose assignment"}
                                </button>
                              </span>
                            )}
                            {nextStepResult && nextStepResult.goalId === g.id && (
                              <p className="success" role="status" data-testid={`nextstep-msg-${g.id}`}>
                                {nextStepResult.msg}
                              </p>
                            )}
                            {assignMsg && assignMsg.goalId === g.id && (
                              <p className="success" role="status" data-testid={`assign-msg-${g.id}`}>
                                {assignMsg.msg}
                              </p>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    {selectedGoal && pGoals.some((g) => g.id === selectedGoal) && (
                      <div className="detail-panel">
                        {(() => {
                          const g = pGoals.find((x) => x.id === selectedGoal)!;
                          const asgs = pAssignments.filter((a) => a.goal_id === g.id);
                          return (
                            <>
                              <div className="detail-panel__head">
                                <h4 className="detail-panel__title">{g.title}</h4>
                                <button className="btn btn--ghost btn--sm" onClick={() => setSelectedGoal(null)}>Close</button>
                              </div>
                              <div className="detail-panel__grid">
                                <div className="detail-panel__item"><span className="detail-panel__label">Status</span><span className={`badge badge--${g.status || "open"}`}>{statusLabel(g.status)}</span></div>
                                <div className="detail-panel__item"><span className="detail-panel__label">Progress</span><span>{g.progress ?? 0}%</span></div>
                                <div className="detail-panel__item"><span className="detail-panel__label">Priority</span><span>{priorityText(g.priority)}</span></div>
                              </div>
                              <p className="detail-panel__meta">Created {formatStamp(g.created_at)} · {asgs.length} assignment(s)</p>
                              <p className="detail-panel__hint">This goal is part of the project you are viewing. Deliverables and agent work for it appear under the relevant sections.</p>
                            </>
                          );
                        })()}
                      </div>
                    )}

                    <h4 className="subsection-title">Assignments</h4>
                    {pAssignments.length === 0 ? (
                      <Empty text="No agents assigned to this project's goals yet." />
                    ) : (
                      <ul className="list">
                        {pAssignments.map((a) => (
                          <li
                            key={a.id}
                            className={`list__item list__item--clickable${selectedAssignment === a.id ? " list__item--selected" : ""}`}
                            onClick={() => setSelectedAssignment(selectedAssignment === a.id ? null : a.id)}
                          >
                            <span className="list__icon"><Icon name="checklist" size={16} /></span>
                            <span className="list__name">{agentLabel(a.agent_id)}</span>
                            <span className="badge badge--faint">{titleOfGoal(a.goal_id)}</span>
                            <span className={`badge badge--${a.status || "queued"}`}>{statusLabel(a.status)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {selectedAssignment && pAssignments.some((a) => a.id === selectedAssignment) && (
                      <div className="detail-panel">
                        {(() => {
                          const a = pAssignments.find((x) => x.id === selectedAssignment)!;
                          const ag = agents.find((x) => x.name === a.agent_id);
                          return (
                            <>
                              <div className="detail-panel__head">
                                <h4 className="detail-panel__title">Assignment</h4>
                                <button className="btn btn--ghost btn--sm" onClick={() => setSelectedAssignment(null)}>Close</button>
                              </div>
                              <div className="detail-panel__grid">
                                <div className="detail-panel__item"><span className="detail-panel__label">Agent</span><span>{agentLabel(a.agent_id)}</span></div>
                                <div className="detail-panel__item"><span className="detail-panel__label">Goal</span><span>{titleOfGoal(a.goal_id)}</span></div>
                                <div className="detail-panel__item"><span className="detail-panel__label">Status</span><span className={`badge badge--${a.status || "queued"}`}>{statusLabel(a.status)}</span></div>
                              </div>
                              <p className="detail-panel__meta">Created {formatStamp(a.created_at)} · {ag ? `${ag.display_name || humanize(ag.name)} (${ag.archetype || ag.role})` : ""}</p>
                              <p className="detail-panel__hint">{a.task_id ? `Task: ${a.task_id}` : "No task attached yet."}</p>
                            </>
                          );
                        })()}
                      </div>
                    )}

                    <h4 className="subsection-title">Deliverables</h4>
                    {pDeliverables.length === 0 ? (
                      <Empty text="No deliverables produced for this project yet." />
                    ) : (
                      <ul className="list">
                        {pDeliverables.map((d) => (
                          <li
                            key={d.id}
                            className={`list__item list__item--clickable${selectedDeliverable === d.id ? " list__item--selected" : ""}`}
                            onClick={() => loadVersions(d.id)}
                          >
                            <span className="list__icon"><Icon name="file" size={16} /></span>
                            <span className="list__name">{d.title}</span>
                            <span className={`badge ${d.latest_status ? `badge--${d.latest_status}` : "badge--neutral"}`}>
                              {d.latest_status ? statusLabel(d.latest_status) : "No versions"}
                            </span>
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

            {/* Deterministic proposal composer for all work types. */}
            <div className="subsection" data-testid="proposal-composer">
              <div className="subsection__head">
                <h3 className="subsection-title">New proposal</h3>
              </div>
              <div className="work-toolbar" style={{ gap: 8, flexWrap: "wrap" }}>
                <select className="select" value={pfType} onChange={(e) => setPfType(e.target.value)} aria-label="Proposal type" data-testid="pf-type">
                  <option value="workspace">Workspace</option>
                  <option value="project">Project</option>
                  <option value="goal">Goal</option>
                  <option value="goal_update">Goal update</option>
                  <option value="assignment">Assignment</option>
                  <option value="deliverable">Deliverable</option>
                  <option value="deliverable_version">Deliverable version</option>
                </select>
                <select className="select" value={pfAuthor} onChange={(e) => setPfAuthor(e.target.value)} aria-label="Attributed to" data-testid="pf-author">
                  {agents.map((a: any) => <option key={a.name} value={a.name}>{a.display_name || a.name}</option>)}
                </select>
                {pfType === "project" && (
                  <select className="select" value={pfWorkspace} onChange={(e) => setPfWorkspace(e.target.value)} aria-label="Parent workspace" data-testid="pf-workspace">
                    <option value="">Parent workspace…</option>
                    {visibleWorkspaces.map((w: any) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </select>
                )}
                {(pfType === "goal" || pfType === "deliverable") && (
                  <select className="select" value={pfProject} onChange={(e) => setPfProject(e.target.value)} aria-label="Parent project" data-testid="pf-project">
                    <option value="">Parent project…</option>
                    {projects.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                )}
                {pfType === "deliverable_version" && (
                  <select className="select" value={pfDeliverable} onChange={(e) => setPfDeliverable(e.target.value)} aria-label="Target deliverable" data-testid="pf-deliverable">
                    <option value="">Target deliverable…</option>
                    {deliverablesList.map((d: any) => <option key={d.id} value={d.id}>{d.title}</option>)}
                  </select>
                )}
                {(pfType === "assignment" || pfType === "goal_update") && (
                  <select className="select" value={pfGoal} onChange={(e) => setPfGoal(e.target.value)} aria-label="Target goal" data-testid="pf-goal">
                    <option value="">Target goal…</option>
                    {goals.map((g: any) => <option key={g.id} value={g.id}>{g.title}</option>)}
                  </select>
                )}
                {pfType === "assignment" && (
                  <select className="select" value={pfAgent} onChange={(e) => setPfAgent(e.target.value)} aria-label="Agent" data-testid="pf-agent">
                    {agents.map((a: any) => <option key={a.name} value={a.name}>{a.display_name || a.name}</option>)}
                  </select>
                )}
                {pfType === "goal" && (
                  <select className="select" value={pfPriority} onChange={(e) => setPfPriority(e.target.value)} aria-label="Priority" data-testid="pf-priority">
                    {["0","1","2","3"].map((v) => <option key={v} value={v}>Priority {v}</option>)}
                  </select>
                )}
                {pfType === "goal_update" && (
                  <>
                    <select className="select" value={pfStatus} onChange={(e) => setPfStatus(e.target.value)} aria-label="Status" data-testid="pf-status">
                      <option value="">(keep status)</option>
                      <option value="in_progress">in_progress</option>
                      <option value="done">done</option>
                    </select>
                    <input className="input" type="number" min="0" max="100" placeholder="Progress 0–100 (optional)" value={pfProgress} onChange={(e) => setPfProgress(e.target.value)} data-testid="pf-progress" />
                  </>
                )}
                {pfType !== "assignment" && (
                  <input className="input" placeholder={pfType === "goal_update" ? "New title (optional)…" : (pfType === "deliverable_version" ? "Content / summary…" : "Name / title…")} value={pfName} onChange={(e) => setPfName(e.target.value)} data-testid="pf-name" />
                )}
                <button className="btn btn--sm btn--primary" onClick={proposeWork} disabled={offline || pfBusy} data-testid="pf-submit">
                  {pfBusy ? "Creating…" : "Propose for approval"}
                </button>
              </div>
              {pfMsg && <p className="muted" data-testid="pf-msg">{pfMsg}</p>}
            </div>

            <div className="subsection approvals-panel" data-testid="approvals-panel">
              <div className="subsection__head">
                <h3 className="subsection-title">Proposals &amp; approvals</h3>
                <div className="subsection__actions">
                  {(() => {
                    const pendingCount = (feed || []).filter((p) => p && p.status === "proposed").length;
                    const pending = pendingCount > 0 && !offline;
                    return pending ? (
                      <button
                        className="btn btn--sm btn--primary"
                        data-testid="approve-all-pending"
                        disabled={allApproving}
                        onClick={approveAllPending}
                        title={`Approve all ${pendingCount} pending proposal(s) in one step`}
                      >
                        {allApproving ? "Approving…" : `Approve all pending (${pendingCount})`}
                      </button>
                    ) : null;
                  })()}
                  <button className="btn btn--ghost btn--sm" onClick={loadFeed} disabled={offline}>Refresh</button>
                </div>
              </div>
              {proposalError && <p className="error">Error: {proposalError}</p>}
              {allApproveMsg && <p className="success" role="status">{allApproveMsg}</p>}
              {feed.length === 0 ? (
                <Empty text="No proposals yet. Ask an agent to propose work, then approve it here." />
              ) : (
                <ul className="list approvals-list">
                  {feed.map((p) => {
                    const pending = p.status === "proposed";
                    const dec = p.decision || null;
                    const completed = p.status === "approved" && !!dec && !!dec.work_id && !!dec.label;
                    return (
                      <li key={p.id} className="list__item approvals-item" data-testid={`proposal-${p.id}`}>
                        <div className="approvals-item__main">
                          <span className={`badge badge--${p.status || "neutral"}`}>{proposalStatusLabel(p.status)}</span>
                          <span className="approvals-item__text">{p.proposed_change}</span>
                          {p.source_thread_id && (
                            <button className="origin-link" title={p.source_thread_id} onClick={() => openOriginatingThread({ thread_id: p.source_thread_id, agent_id: p.agent_id }) }>
                              #{p.source_thread_id.slice(0, 8)}
                            </button>
                          )}
                        </div>
                        {pending ? (
                          <div className="approvals-item__actions">
                            <button className="btn btn--sm btn--primary" onClick={() => approveProposal(p.id)} disabled={offline || proposalBusy === p.id} data-testid={`approve-${p.id}`}>Approve</button>
                            <button className="btn btn--sm btn--ghost" onClick={() => rejectProposal(p.id)} disabled={offline || proposalBusy === p.id} data-testid={`reject-${p.id}`}>Reject</button>
                          </div>
                        ) : (
                          <div className="approvals-item__meta">
                            {p.status === "approved" && completed ? (
                              <button className="origin-link" onClick={() => focusWorkItem(dec.work_type, dec.work_id)} data-testid={`result-${p.id}`}>
                                {"\u2192"} {dec.label}
                              </button>
                            ) : p.status === "approved" ? (
                              <span className="muted">Approved (result details unavailable)</span>
                            ) : dec && dec.rejection_reason ? (
                              <span className="muted">{dec.rejection_reason}</span>
                            ) : dec && dec.decided_at ? (
                              <span className="muted">Decided {formatStamp(dec.decided_at)}</span>
                            ) : null}
                            {dec && dec.decided_at && <span className="muted"> · {formatStamp(dec.decided_at)}</span>}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
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
                {visibleWorkspaces.map((w) => (
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

            {/* D4.3-A1: unified command interface — one objective for the whole team. */}
            <div className="command-panel" data-testid="command-panel">
              <div className="command-panel__head">
                <h3 className="section-title">New Objective</h3>
                <span className="command-panel__hint">Coordinated by {agentDisplay("strategist")} for the whole team</span>
              </div>
              <textarea
                className="task-input"
                data-testid="plan-objective"
                value={planObjective}
                onChange={(e) => {
                  setPlanObjective(e.target.value);
                  setPlanError(null);
                  setPlanNotice(null);
                }}
                placeholder="Tell your AI team what to accomplish, e.g. “Help me organize the launch of my new project.”"
                rows={2}
                disabled={offline || planBusy}
              />
              <div className="command-panel__actions">
                <button
                  className="btn btn--primary"
                  data-testid="plan-submit"
                  onClick={requestPlan}
                  disabled={offline || planBusy || !planObjective.trim()}
                >
                  {planBusy ? <><span className="spinner" aria-hidden="true" /> Generating team plan…</> : "Generate team plan"}
                </button>
                <span className="muted">Preview only — nothing is created until you approve later.</span>
              </div>
              {planError && <p className="error" role="alert" data-testid="plan-error">Error: {planError}</p>}
              {planNotice && <p className="warning" data-testid="plan-notice">{planNotice}</p>}
              {planResult && !planError && (
                <div className="plan-preview" data-testid="plan-preview">
                  <div className="plan-preview__head">
                    <span className="result__heading">Coordinated team plan · {((planResult.steps || [])).length} step(s)</span>
                    <span className="muted">Coordinator: {agentDisplay(planResult.coordinator)}</span>
                  </div>
                  {planResult.reply && <p className="plan-preview__reply">{planResult.reply}</p>}
                  <div className="plan-preview__actions">
                    <button
                      className="btn btn--sm btn--primary"
                      data-testid="plan-approve-all"
                      disabled={planAllBusy || planFiling !== null || planBusy ||
                        !(planResult.steps || []).some((x: any) => !x.approved && !x.rejected && !x.error)}
                      onClick={approveAllPlan}
                    >
                      {planAllBusy ? "Filing…" : `Approve all pending (${(planResult.steps || []).filter((x: any) => !x.approved && !x.rejected && !x.error).length})`}
                    </button>
                  </div>
                  {planAllMsg && <p className="success" role="status">{planAllMsg}</p>}
                  <ul className="list plan-steps">
                    {(planResult.steps || []).map((s: any, i: number) => (
                      <li key={i} className="list__item plan-step" data-testid={`plan-step-${i}`}>
                        <div className="plan-step__main">
                          <span className="plan-step__type">{humanize(s.work_type)}</span>
                          <input
                            className="plan-step__title-input"
                            data-testid={`plan-step-title-${i}`}
                            value={s.title || ""}
                            disabled={planFiling !== null || !!(s.approved || s.rejected)}
                            onChange={(e) => updatePlanStep(i, { title: e.target.value, error: null })}
                          />
                          {s.work_type === "assignment" && (() => {
                            const goalOpts = goalsIn(selectedProjectId || s.project_id || projects[0]?.id || "");
                            return goalOpts.length > 0 ? (
                              <select
                                className="select select--sm step-goal"
                                data-testid={`plan-step-goal-${i}`}
                                value={s.goal_id || ""}
                                onChange={(e) => updatePlanStep(i, { goal_id: e.target.value, error: null })}
                              >
                                <option value="">Target goal…</option>
                                {goalOpts.map((g: any) => (
                                  <option key={g.id} value={g.id}>{g.title}</option>
                                ))}
                              </select>
                            ) : (
                              <span className="muted plan-step__err">No goal to assign — create a goal first.</span>
                            );
                          })()}
                        </div>
                        <div className="plan-step__meta">
                          <label className="plan-step__ownerrow">
                            <span className="muted">Owner</span>
                            <select
                              className="select select--sm"
                              data-testid={`plan-step-owner-${i}`}
                              value={s.owner || s.suggested_agent || ""}
                              disabled={planFiling !== null || !!(s.approved || s.rejected)}
                              onChange={(e) => updatePlanStep(i, { owner: e.target.value, error: null })}
                            >
                              {planOwnerOptions(s).map((slug: string) => (
                                <option key={slug} value={slug}>{agentDisplay(slug)}</option>
                              ))}
                            </select>
                          </label>
                          <div className="plan-step__actions">
                            {planTypeSupported(s) ? (
                              <>
                                {!(s.approved || s.rejected) && (
                                  <button
                                    className="btn btn--sm btn--primary"
                                    data-testid={`plan-approve-${i}`}
                                    disabled={planFiling !== null && planFiling !== i || !!s.error}
                                    onClick={() => approvePlanStep(i)}
                                  >
                                    {planFiling === i ? "Filing…" : "Approve"}
                                  </button>
                                )}
                                {s.approved && <span className="badge badge--approved" data-testid={`plan-done-${i}`}>Approved</span>}
                                {!s.approved && !s.rejected && (
                                  <button
                                    className="btn btn--sm btn--ghost"
                                    data-testid={`plan-reject-${i}`}
                                    disabled={planFiling !== null}
                                    onClick={() => rejectPlanStep(i)}
                                  >
                                    Reject
                                  </button>
                                )}
                                {s.rejected && <span className="badge badge--rejected">Rejected</span>}
                              </>
                            ) : (
                              <span className="muted" data-testid={`plan-unsupported-${i}`}>
                                Not supported in this bridge yet.
                              </span>
                            )}
                            <button
                              className="btn btn--sm btn--ghost"
                              data-testid={`plan-remove-${i}`}
                              disabled={planFiling !== null || !!s.approved}
                              onClick={() => removePlanStep(i)}
                              title="Remove this step from the plan"
                            >
                              Remove
                            </button>
                          </div>
                        </div>
                        {s.reason && <span className="plan-step__reason">{s.reason}</span>}
                        {s.msg && <p className="success" role="status" data-testid={`plan-step-msg-${i}`}>{s.msg}</p>}
                        {s.error && <p className="error" role="alert" data-testid={`plan-step-err-${i}`}>Error: {s.error}</p>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {!selectedProjectId ? (
              <Empty text="Select a workspace and project to see its goals, assignments, and deliverables." />
            ) : (
              <>
                <div className="subsection">
                  <div className="subsection__head">
                    <h3 className="subsection-title">Goals</h3>
                    <input
                      className="input"
                      placeholder="Goal name…"
                      style={{ width: 180 }}
                      value={wsGoalName}
                      onChange={(e) => setWsGoalName(e.target.value)}
                      data-testid="ws-goal-name"
                    />
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
                    <>
                    <ul className="list">
                      {filteredGoals.map((g) => (
                        <li
                          key={g.id}
                          className={`list__item list__item--clickable${selectedGoal === g.id ? " list__item--selected" : ""}`}
                          onClick={() => setSelectedGoal(selectedGoal === g.id ? null : g.id)}
                        >
                          <span className="list__icon"><Icon name="target" size={16} /></span>
                          <span className="list__name">{g.title}</span>
                          <span className={`badge badge--${g.status || "open"}`}>{statusLabel(g.status)}</span>
                        </li>
                      ))}
                    </ul>
                    {selectedGoal && workGoals.some((g) => g.id === selectedGoal) && (
                      <div className="detail-panel">
                        {(() => {
                          const g = workGoals.find((x) => x.id === selectedGoal)!;
                          const asgs = workAssignments.filter((a) => a.goal_id === g.id);
                          return (
                            <>
                              <div className="detail-panel__head">
                                <h4 className="detail-panel__title">{g.title}</h4>
                                <button className="btn btn--ghost btn--sm" onClick={() => setSelectedGoal(null)}>Close</button>
                              </div>
                              <div className="detail-panel__grid">
                                <div className="detail-panel__item"><span className="detail-panel__label">Status</span><span className={`badge badge--${g.status || "open"}`}>{statusLabel(g.status)}</span></div>
                                <div className="detail-panel__item"><span className="detail-panel__label">Progress</span><span>{g.progress ?? 0}%</span></div>
                                <div className="detail-panel__item"><span className="detail-panel__label">Priority</span><span>{priorityText(g.priority)}</span></div>
                              </div>
                              <p className="detail-panel__meta">Created {formatStamp(g.created_at)} · {asgs.length} assignment(s)</p>
                              <OriginConversation types={["goal", "goal_update"]} wid={g.id} threadsByKey={workThreads} onLoad={loadWorkThreads} onOpen={openOriginatingThread} />
                              {(() => {
                                const agentId = asgs[0]?.agent_id || null;
                                const key = `goal:${g.id}`;
                                const ep = workEpisodes[key];
                                if (ep && ep.status === "running") {
                                  return (
                                    <div className="exec-control">
                                      <span className="badge badge--running">Tracking</span>
                                      <button className="origin-link" onClick={() => { setTab("episodes"); setSelectedEpisode(ep.episode_id); loadEpisode(ep.episode_id); }}>Open in Activity</button>
                                    </div>
                                  );
                                }
                                if (!agentId) {
                                  return <div className="exec-control"><span className="muted">Assign an agent to this goal to start tracking.</span></div>;
                                }
                                return (
                                  <div className="exec-control">
                                    <button className="btn btn--sm btn--primary" onClick={() => startExecution("goal", g.id, agentId)} disabled={offline || execBusy === key} data-testid={`track-${g.id}`}>
                                      Track execution
                                    </button>
                                    {execError && <span className="muted">{execError}</span>}
                                  </div>
                                );
                              })()}
                              <ExecutionPanel wtype="goal" wid={g.id} data={workExec[`goal:${g.id}`]} onLoad={loadWorkExec} agentLabelFn={agentLabel} />
                            </>
                          );
                        })()}
                      </div>
                    )}
                    </>
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
                    <>
                    <ul className="list">
                      {filteredAssignments.map((a) => (
                        <li
                          key={a.id}
                          data-testid={`assignment-${a.id}`}
                          className={`list__item list__item--clickable${selectedAssignment === a.id ? " list__item--selected" : ""}`}
                          onClick={() => setSelectedAssignment(selectedAssignment === a.id ? null : a.id)}
                        >
                          <span className="list__icon"><Icon name="checklist" size={16} /></span>
                          <span className="list__name">{agentLabel(a.agent_id)}</span>
                          {agentArchetype(a.agent_id) && <span className="badge badge--faint">{agentArchetype(a.agent_id)}</span>}
                          <span className="badge badge--faint">{titleOfGoal(a.goal_id)}</span>
                          <span className={`badge badge--${a.status || "queued"}`}>{statusLabel(a.status)}</span>
                        </li>
                      ))}
                    </ul>
                    {selectedAssignment && workAssignments.some((a) => a.id === selectedAssignment) && (
                      <div className="detail-panel">
                        {(() => {
                          const a = workAssignments.find((x) => x.id === selectedAssignment)!;
                          const ag = agents.find((x) => x.name === a.agent_id);
                          return (
                            <>
                              <div className="detail-panel__head">
                                <h4 className="detail-panel__title">Assignment</h4>
                                <button className="btn btn--ghost btn--sm" onClick={() => setSelectedAssignment(null)}>Close</button>
                              </div>
                              <div className="detail-panel__grid">
                                <div className="detail-panel__item"><span className="detail-panel__label">Agent</span><span>{agentLabel(a.agent_id)}</span></div>
                                <div className="detail-panel__item"><span className="detail-panel__label">Goal</span><span>{titleOfGoal(a.goal_id)}</span></div>
                                <div className="detail-panel__item"><span className="detail-panel__label">Status</span><span className={`badge badge--${a.status || "queued"}`}>{statusLabel(a.status)}</span></div>
                              </div>
                              <p className="detail-panel__meta">Created {formatStamp(a.created_at)} · {ag ? `${ag.display_name || humanize(ag.name)} (${ag.archetype || ag.role})` : ""}</p>
                              <p className="detail-panel__hint">{a.task_id ? `Task: ${a.task_id}` : "No task attached yet."}</p>
                              {(() => {
                                const approved = feed.some(
                                  (p) => p.work_type === "assignment" && p.status === "approved" && p.result_id === a.id);
                                if (!approved) {
                                  return <p className="detail-panel__hint" data-testid={`not-approved-${a.id}`}>Not approved for execution yet.</p>;
                                }
                                const key = `assignment:${a.id}`;
                                const ep = workEpisodes[key];
                                if (ep && ep.status === "running") {
                                  return (
                                    <div className="exec-control">
                                      <span className="badge badge--running">Tracking</span>
                                      <button className="origin-link" onClick={() => { setTab("episodes"); setSelectedEpisode(ep.episode_id); loadEpisode(ep.episode_id); }}>Open in Activity</button>
                                    </div>
                                  );
                                }
                                return (
                                  <div className="exec-control">
                                    {confirmExec === a.id ? (
                                      <>
                                        <span className="muted">Start tracking this approved assignment?</span>
                                        <button className="btn btn--sm btn--primary" data-testid={`run-${a.id}`} onClick={() => startApprovedExecution(a.id, a.agent_id)} disabled={!!execBusy}>
                                          Confirm
                                        </button>
                                        <button className="btn btn--sm btn--ghost" onClick={() => setConfirmExec(null)}>Cancel</button>
                                      </>
                                    ) : (
                                      <button className="btn btn--sm btn--primary" data-testid={`approved-run-${a.id}`} onClick={() => { setConfirmExec(a.id); setExecError(null); }} disabled={offline}>
                                        Run approved
                                      </button>
                                    )}
                                    {execError && <span className="muted">{execError}</span>}
                                  </div>
                                );
                              })()}
                              <ExecutionPanel wtype="assignment" wid={a.id} data={workExec[`assignment:${a.id}`]} onLoad={loadWorkExec} agentLabelFn={agentLabel} />
                            </>
                          );
                        })()}
                      </div>
                    )}
                    </>
                  )}
                </div>

                <div className="subsection">
                  <div className="subsection__head">
                    <h3 className="subsection-title">Deliverables</h3>
                    <input
                      className="input"
                      placeholder="Deliverable name…"
                      style={{ width: 180 }}
                      value={wsDelivName}
                      onChange={(e) => setWsDelivName(e.target.value)}
                      data-testid="ws-deliverable-name"
                    />
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
                            {statusLabel(d.latest_status) || "No versions"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {selectedDeliverable &&
                  (() => {
                    const first = versions[0];
                    const last = versions[versions.length - 1];
                    const summary =
                      first && last
                        ? diffLines(first.content, last.content)
                        : { added: [] as string[], removed: [] as string[], changed: [] as string[] };
                    return (
                      <div className="versions">
                        <div className="versions__head">
                          <h3 className="versions__title">Deliverable versions</h3>
                          <span className="badge badge--faint">{versions.length} version(s)</span>
                        </div>
                        <OriginConversation types={["deliverable", "deliverable_version"]} wid={selectedDeliverable} threadsByKey={workThreads} onLoad={loadWorkThreads} onOpen={openOriginatingThread} />
                        {versionError && (
                          <div className="error-banner" role="alert" data-testid="version-error">
                            {versionError}
                          </div>
                        )}
                        {versions.length === 0 ? (
                          <Empty text="No versions yet." />
                        ) : (
                          <div className="versions__list">
                            {versions.map((v) => (
                              <div key={v.id} className="version" data-testid="version">
                                <div className="version__meta">
                                  <span className={`badge badge--${v.status || "neutral"}`}>v{v.version}</span>
                                  <span className={`badge badge--${v.status || "neutral"}`}>{statusLabel(v.status)}</span>
                                  {v.created_at && <span className="badge badge--faint">created {formatStamp(v.created_at)}</span>}
                                </div>
                                {v.content ? (
                                  <div className="version__content markdown"><Markdown source={v.content} /></div>
                                ) : (
                                  <p className="detail-panel__hint">No content in this version.</p>
                                )}

                                {!offline && v.status !== "approved" && v.status !== "rejected" && (
                                  <div className="version__actions">
                                    {approvingVersion === v.id ? (
                                      <div className="confirm-row">
                                        <span>Approve v{v.version}? This marks it as the accepted deliverable output.</span>
                                        <button className="btn btn--primary btn--sm" onClick={() => confirmApprove(v.id)}>Confirm approve</button>
                                        <button className="btn btn--ghost btn--sm" onClick={() => setApprovingVersion(null)}>Cancel</button>
                                      </div>
                                    ) : (
                                      <>
                                        <button className="btn btn--ghost btn--sm" onClick={() => setApprovingVersion(v.id)}>Approve</button>
                                        <button className="btn btn--danger-ghost btn--sm" onClick={() => { setRejectReason(""); setRejectingVersion(v.id); }}>Request revision</button>
                                      </>
                                    )}
                                  </div>
                                )}

                                {rejectingVersion === v.id && (
                                  <div className="reject-row">
                                    <label htmlFor={`reason-${v.id}`}>What should be revised? (optional)</label>
                                    <input
                                      id={`reason-${v.id}`}
                                      className="input"
                                      value={rejectReason}
                                      onChange={(e) => setRejectReason(e.target.value)}
                                      placeholder="Share what needs to change"
                                    />
                                    <button className="btn btn--primary btn--sm" onClick={() => submitReject(v.id)}>Send request</button>
                                    <button className="btn btn--ghost btn--sm" onClick={() => setRejectingVersion(null)}>Cancel</button>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}

                        {versions.length >= 2 && first && last && (
                          <div className="diff" data-testid="diff">
                            <div className="diff__head">
                              <h4 className="diff__title">Comparison: v{first.version} → v{last.version}</h4>
                              <span className="badge badge--faint">
                                +{summary.added.length} added · −{summary.removed.length} removed
                              </span>
                              <button className="btn btn--ghost btn--sm" onClick={() => setShowRawDiff((s) => !s)}>
                                {showRawDiff ? "Hide technical diff" : "Show technical diff"}
                              </button>
                            </div>
                            {showRawDiff ? (
                              <pre className="diff__body">{summary.changed.join("\n")}</pre>
                            ) : (
                              <ul className="list">
                                {summary.added.length === 0 && summary.removed.length === 0 ? (
                                  <li className="list__item"><span className="list__name">No differences between these versions.</span></li>
                                ) : (
                                  <>
                                    {summary.added.map((l, i) => (
                                      <li key={`a${i}`} className="diff-summary diff-summary--added"><span>Added</span><span>{l}</span></li>
                                    ))}
                                    {summary.removed.map((l, i) => (
                                      <li key={`r${i}`} className="diff-summary diff-summary--removed"><span>Removed</span><span>{l}</span></li>
                                    ))}
                                  </>
                                )}
                              </ul>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })()}
              </>
            )}
          </section>
        )}

        {tab === "episodes" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Agent Activity</h2>
                <p className="panel__sub">What your agents have run recently, their status, and their progress.</p>
              </div>
            </div>
            {visibleEpisodes.length === 0 ? (
              <Empty text="No agent activity yet. Runs appear here when you ask an agent to do work." />
            ) : (
              <ul className="list">
                {visibleEpisodes.map((e) => (
                  <li
                    key={e.id}
                    className={`list__item list__item--clickable${selectedEpisode === e.id ? " list__item--selected" : ""}`}
                    onClick={() => loadEpisode(e.id)}
                  >
                    <span className="list__icon">
                      <Icon name="activity" size={16} />
                    </span>
                    <span className="list__name">{agentLabel(e.agent_id)}</span>
                    <span className={`badge badge--${e.status || "neutral"}`}>{statusLabel(e.status)}</span>
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
                <h3 className="versions__title">Activity detail</h3>
                {episodeDetail ? (
                  <>
                    <div className="episode-meta">
                      <span className={`badge badge--${episodeDetail.status || "neutral"}`}>{statusLabel(episodeDetail.status)}</span>
                      <span className="badge badge--faint">{Math.round((episodeDetail.progress || 0) * 100)}% progress</span>
                      {episodeDetail.created_at && (
                        <span className="badge badge--faint">started {formatStamp(episodeDetail.created_at)}</span>
                      )}
                    </div>
                    {episodeDetail.status === "done" &&
                      (episodeDetail.applied_at ? (
                        <div className="exec-apply" data-testid="episode-applied"><span className="badge badge--approved">Applied</span></div>
                      ) : !offline ? (
                        <div className="exec-control exec-apply">
                          {applyEid === episodeDetail.id ? (
                            <>
                              <span className="muted">Apply this completion to its goal using the recorded evidence?</span>
                              <button className="btn btn--sm btn--primary" data-testid="confirm-apply" onClick={() => submitApply(episodeDetail.id)} disabled={!!applyingEid}>
                                Confirm apply
                              </button>
                              <button className="btn btn--sm btn--ghost" onClick={() => setApplyEid(null)}>Cancel</button>
                            </>
                          ) : (
                            <button className="btn btn--sm btn--primary" data-testid="apply-btn"
                              onClick={() => { setApplyEid(episodeDetail.id); setApplyError(null); }}>
                              Apply to goal
                            </button>
                          )}
                          {applyError && <span className="muted" data-testid="apply-error">{applyError}</span>}
                        </div>
                      ) : null)}
                    {episodeEvents.length === 0 ? (
                      <Empty text="No events recorded for this episode yet." />
                    ) : (
                      <ul className="list">
                        {episodeEvents.map((ev, i) => {
                          let evSummary: string | null = null;
                          try {
                            const raw = ev.evidence_json;
                            const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
                            evSummary = parsed && parsed.summary ? String(parsed.summary) : null;
                          } catch { evSummary = null; }
                          return (
                            <li key={i} className="list__item" data-testid={`event-${ev.status}`}>
                              <span className="list__icon">
                                <Icon name="activity" size={16} />
                              </span>
                              <span className="list__name">{statusLabel(ev.status)}</span>
                              {ev.detail && <span className="badge badge--faint">{ev.detail}</span>}
                              {evSummary && <span className="badge badge--faint">{evSummary}</span>}
                              <span className="badge badge--faint">{formatStamp(ev.created_at)}</span>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                    {episodeDetail && episodeDetail.status === "running" && !offline && (
                      <div className="exec-forms">
                        <div className="exec-forms__head">Record progress (evidence required)</div>
                        {epError && <p className="error" data-testid="ep-error">Error: {epError}</p>}
                        <div className="exec-forms__row">
                          <input
                            className="input input--sm"
                            aria-label="Progress (0..1)"
                            value={cpProgress}
                            onChange={(e) => setCpProgress(e.target.value)}
                            placeholder="0..1"
                          />
                          <input
                            className="input input--sm"
                            aria-label="Evidence summary"
                            value={cpEvidence}
                            onChange={(e) => setCpEvidence(e.target.value)}
                            placeholder="Evidence summary"
                          />
                          <button className="btn btn--sm btn--primary" onClick={() => submitCheckpoint(selectedEpisode as string)} data-testid="checkpoint-btn">
                            Save progress
                          </button>
                        </div>
                        <div className="exec-forms__row">
                          <input
                            className="input input--sm"
                            aria-label="Completion evidence"
                            value={completeEvidence}
                            onChange={(e) => setCompleteEvidence(e.target.value)}
                            placeholder="Completion evidence"
                          />
                          <button className="btn btn--sm btn--ghost" onClick={() => submitComplete(selectedEpisode as string)} data-testid="complete-btn">
                            Complete
                          </button>
                        </div>
                      </div>
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
                <p className="panel__sub">Select an agent, review past conversations, and give it a task.</p>
              </div>
            </div>

            {(() => {
              const filtered = convFilter
                ? conversations.filter((c) => c.agent_id === convFilter)
                : conversations;
              return (
                <div className="conv-browser">
                  <div className="conv-browser__head">
                    <h3 className="section-title">Conversations</h3>
                    <select
                      className="select select--small"
                      value={convFilter}
                      onChange={(e) => setConvFilter(e.target.value)}
                      aria-label="Filter conversations by agent"
                    >
                      <option value="">All agents</option>
                      {agents.map((a) => (
                        <option key={a.name} value={a.name}>
                          {a.display_name || humanize(a.name)}{a.archetype ? ` · ${a.archetype}` : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                  {conversations.length === 0 ? (
                    <Empty text="No saved conversations yet. Conversations appear here once you chat with an agent." />
                  ) : filtered.length === 0 ? (
                    <Empty text="No conversations for this agent yet." />
                  ) : (
                    <ul className="conv-browser__list">
                      {filtered.map((c) => (
                        <li
                          key={c.thread_id}
                          data-testid={`convo-${c.thread_id}`}
                          className={`conv-browser__item${openThreadId === c.thread_id ? " conv-browser__item--active" : ""}`}
                        >
                          <button
                            className="conv-browser__open"
                            onClick={() => openConversation(c)}
                          >
                            <span className="conv-browser__title">{c.title}</span>
                            <span className="conv-browser__meta">
                              {c.agent_id ? agentLabel(c.agent_id) : "Agent unknown"}
                              {" · "}{c.message_count} message(s) · {formatStamp(c.last_activity)}
                            </span>
                          </button>
                          {renamingThread === c.thread_id ? (
                            <span className="conv-browser__rename">
                              <input
                                className="input"
                                value={renameTitle}
                                onChange={(e) => setRenameTitle(e.target.value)}
                                placeholder="Rename conversation"
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") renameConversation(c, renameTitle);
                                  if (e.key === "Escape") setRenamingThread(null);
                                }}
                              />
                              <button className="btn btn--ghost btn--sm" onClick={() => renameConversation(c, renameTitle)}>Save</button>
                              <button className="btn btn--ghost btn--sm" onClick={() => setRenamingThread(null)}>Cancel</button>
                            </span>
                          ) : (
                            <button className="btn btn--ghost btn--sm" onClick={(e) => { e.stopPropagation(); startRename(c); }}>Rename</button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })()}

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
                      This conversation · {contextCounts[selectedAgent] ?? 0} message(s)
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
                  <button
                    className="btn btn--ghost btn--sm"
                    data-testid="suggest-ideas"
                    onClick={suggestIdeas}
                    disabled={offline || agentRunning || suggesting}
                    title="Have this agent propose 3\u20134 concrete ideas as proposals you approve in Work"
                  >
                    {suggesting ? (
                      <><span className="spinner" aria-hidden="true" /> Brainstorming…</>
                    ) : (
                      "✨ Suggest ideas (propose for my approval)"
                    )}
                  </button>
                  {agentRunning && (
                    <span className="task-panel__status">Generating response locally…</span>
                  )}
                </div>

                {/* Phase 1 (safest path): deterministic idea-to-proposal composer.
                    Always available — works even if the model is slow or offline,
                    because it never depends on a generated reply. Still files only
                    a proposal; a human must approve it in Work before any record. */}
                <div className="draft-composer" data-testid="draft-composer">
                  <div className="draft-composer__head">
                    <span className="draft-composer__title">Turn an idea into a proposal</span>
                    <span className="draft-composer__hint">Deterministic{" \u2014 "}works even if the model is slow</span>
                  </div>
                  <div className="draft__row">
                    <select
                      value={draftType}
                      data-testid="draft-composer-type"
                      onChange={(e) => {
                        setDraftType(e.target.value);
                        setDraftMsg(null);
                        setDraftGoal("");
                      }}
                    >
                      <option value="goal">Goal</option>
                      <option value="project">Project</option>
                      <option value="deliverable">Deliverable</option>
                      <option value="assignment">Assignment</option>
                    </select>
                    <input
                      placeholder="Idea (e.g. \u201cImprove onboarding with a guided welcome flow\u201d)"
                      data-testid="draft-composer-title"
                      value={draftTitle}
                      onChange={(e) => {
                        setDraftTitle(e.target.value);
                        setDraftMsg(null);
                      }}
                    />
                  </div>
                  {draftType === "assignment" && (() => {
                    const goalsForParent = goalsIn(selectedProjectId || projects[0]?.id || "");
                    return goalsForParent.length > 0 ? (
                      <div className="draft__row">
                        <select value={draftGoal} data-testid="draft-composer-goal" onChange={(e) => setDraftGoal(e.target.value)}>
                          <option value="">Target goal{"…"}</option>
                          {goalsForParent.map((g: any) => (
                            <option key={g.id} value={g.id}>{g.title}</option>
                          ))}
                        </select>
                      </div>
                    ) : null;
                  })()}
                  <p className="draft__ctx">
                    Agent: {humanize(selectedAgent || "workspace_architect")}{" · "}
                    {draftType === "project"
                      ? `Parent workspace: ${workspaceName(selectedWorkspaceId || workspaces[0]?.id || "")}`
                      : `Parent project: ${projects.find((p) => p.id === (selectedProjectId || projects[0]?.id))?.name || "None"}`}
                  </p>
                  {draftMsg && <p className="draft__msg" role="status">{draftMsg}</p>}
                  <div className="draft__actions">
                    <button
                      className="btn btn--primary btn--sm"
                      data-testid="draft-composer-submit"
                      disabled={draftBusy || offline || !draftTitle.trim()}
                      onClick={chatPropose}
                    >
                      {draftBusy ? "Creating…" : "Create proposal"}
                    </button>
                  </div>
                </div>

                {modelOnline === false && !offline && (
                  <div className="warning" data-testid="model-offline-banner" role="alert">
                    The language model is currently unavailable, so replies may not generate until it recovers.
                  </div>
                )}
                {agentError && <p className="error">Error: {agentError}</p>}
                {agentResult?.history_warning && (
                  <p className="warning">Warning: {agentResult.history_warning}</p>
                )}
                {agentGenError && (
                  <div className="warning" data-testid="gen-failure-panel" role="alert">
                    <span className="result__heading">
                      {agentGenError.code === "model_empty"
                        ? "No response was generated this time."
                        : agentGenError.code === "memory_error"
                          ? "Your saved context couldn't be loaded."
                          : "The language model is temporarily unavailable."}
                    </span>
                    <p className="muted">
                      {agentGenError.code === "memory_error"
                        ? "Your reply was prepared without your saved context, and nothing from your memory was changed."
                        : "Nothing was saved or changed. You can retry, or type your message again."}
                    </p>
                    {agentGenError.retryable && (
                      <button
                        className="btn btn--sm btn--primary"
                        data-testid="retry-agent"
                        onClick={retryAgentRun}
                        disabled={offline || agentRunning}
                      >
                        Retry
                      </button>
                    )}
                  </div>
                )}
                {wsProposed ? (
                  <div className="warning" data-testid="ws-proposed-panel" role="alert">
                    <span className="result__heading">Workspace proposal created</span>
                    <p className="muted">
                      Review and approve it in the{" "}
                      <button className="origin-link" onClick={() => setTab("work")}>Work · Approvals</button>{" "}
                      to actually create the workspace.
                    </p>
                  </div>
                ) : (
                  wsPrompt && (
                    <div className="warning" data-testid="ws-propose-panel" role="alert">
                      <span className="result__heading">Create as a proposal for approval?</span>
                      <p className="muted">
                        "{extractWorkspaceName(wsPrompt.task)}" — nothing is created until you approve it.
                      </p>
                      {wsError && <p className="muted" data-testid="ws-error">Error: {wsError}</p>}
                      <button
                        className="btn btn--sm btn--primary"
                        data-testid="propose-workspace"
                        onClick={proposeWorkspace}
                        disabled={wsBusy || offline}
                      >
                        {wsBusy ? "Proposing…" : "Propose workspace for approval"}
                      </button>
                    </div>
                  )
                )}

                {openThreadId && transcript.length > 0 && (
                  <div className="result transcript" data-testid="transcript">
                    {transcript.map((m, i) => (
                      <div
                        key={i}
                        className={`chat-bubble chat-bubble--${m.role === "user" ? "user" : "agent"}`}
                      >
                        <div className="chat-bubble__role">
                          {m.role === "user"
                            ? "You"
                            : (agents.find((x) => x.name === selectedAgent)?.display_name || humanize(selectedAgent))}
                        </div>
                        <div className="chat-bubble__body markdown"><Markdown source={m.content} /></div>
                      </div>
                    ))}
                  </div>
                )}

                {openThreadId && threadLinks.length > 0 && (
                  <div className="result__section linked-work" data-testid="linked-work">
                    <span className="result__heading">Linked work</span>
                    <ul className="chips">
                      {threadLinks.map((l, i) => (
                        <li key={i} className="chip">
                          <button className="origin-link" onClick={() => focusWorkItem(l.work_type, l.work_id)}>
                            {l.label || `${l.work_type}: ${l.work_id.slice(0, 8)}`}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {!openThreadId && agentResult && (
                  <div className="result">
                    <div className="result__meta">
                      Generated on your device
                      <details className="tech-detail">
                        <summary>Technical details</summary>
                        <p>Execution: {agentResult.location}</p>
                      </details>
                    </div>
                    <div className="result__body" data-testid="agent-reply">
                      <Markdown source={agentResult.reply} />
                    </div>
                    {agentResult.facts?.length > 0 &&
                      (() => {
                        const facts = uniqueBy(agentResult.facts, (f: any) => `${f.key ?? ""}|${f.value ?? ""}`);
                        return facts.length > 0 ? (
                          <div className="result__section">
                            <span className="result__heading">What I already know</span>
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
                          {agentResult.proposal_results?.length > 1
                            ? `${agentResult.proposal_results.length} idea(s) filed as proposals \u2014 approve them below.`
                            : `${agentResult.proposals.length} proposal(s) filed for your approval.`}
                        </span>
                        <button
                          className="btn btn--sm btn--ghost"
                          data-testid="ideas-to-approve"
                          onClick={() => setTab("work")}
                        >
                          Review in Work \u00b7 Approvals
                        </button>
                      </div>
                    )}
                    {agentResult.tool_results?.length > 0 && (
                      <div className="result__section">
                        <span className="result__heading">Tools used</span>
                        <ul className="chips">
                          {agentResult.tool_results.map((t: any, i: number) => (
                            <li key={i} className="chip">
                              {t.tool}: {t.ok ? "ok" : `error: ${t.error}`}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {!agentGenError && (agentResult.draftProposed ? (
                      <div className="result__section draft-panel">
                        <span className="result__heading">Proposal created</span>
                        <button className="draft__goto" data-testid="draft-goto" onClick={() => setTab("work")}>
                          Approve it in Work {"·"} Approvals
                        </button>
                      </div>
                    ) : (
                      <div className="result__section draft-panel">
                        {!draftOpen ? (
                          <button
                            className="draft__toggle"
                            data-testid="draft-open"
                            onClick={() => {
                              setDraftMsg(null);
                              setDraftTitle(
                                agentResult.reply
                                  ? agentResult.reply.replace(/[\r\n]+/g, " ").trim().slice(0, 160)
                                  : ""
                              );
                              setDraftOpen(true);
                            }}
                          >
                            + Make this a proposal
                          </button>
                        ) : (
                          <div className="draft__form" data-testid="draft-form">
                            <span className="result__heading">Turn this idea into a proposal</span>
                            <div className="draft__row">
                              <select
                                value={draftType}
                                onChange={(e) => {
                                  setDraftType(e.target.value);
                                  setDraftMsg(null);
                                  setDraftGoal("");
                                }}
                              >
                                <option value="goal">Goal</option>
                                <option value="project">Project</option>
                                <option value="deliverable">Deliverable</option>
                                <option value="assignment">Assignment</option>
                              </select>
                              <input
                                placeholder="Short title for this idea"
                                value={draftTitle}
                                onChange={(e) => {
                                  setDraftTitle(e.target.value);
                                  setDraftMsg(null);
                                }}
                              />
                            </div>
                            {draftType === "assignment" && (() => {
                              const goalsForParent = goalsIn(selectedProjectId || projects[0]?.id || "");
                              return goalsForParent.length > 0 ? (
                                <div className="draft__row">
                                  <select value={draftGoal} onChange={(e) => setDraftGoal(e.target.value)}>
                                    <option value="">Target goal{"…"}</option>
                                    {goalsForParent.map((g: any) => (
                                      <option key={g.id} value={g.id}>{g.title}</option>
                                    ))}
                                  </select>
                                </div>
                              ) : null;
                            })()}
                            <p className="draft__ctx">
                              Agent: {humanize(selectedAgent || "workspace_architect")}{" \u00b7 "}
                              {draftType === "project"
                                ? `Parent workspace: ${workspaceName(selectedWorkspaceId || workspaces[0]?.id || "")}`
                                : `Parent project: ${projects.find((p) => p.id === (selectedProjectId || projects[0]?.id))?.name || "None"}`}
                            </p>
                            {draftMsg && <p className="draft__msg" role="status">{draftMsg}</p>}
                            <div className="draft__actions">
                              <button className="btn" data-testid="draft-submit" disabled={draftBusy} onClick={chatPropose}>
                                {draftBusy ? "Creating\u2026" : "Create proposal"}
                              </button>
                              <button className="draft__cancel" data-testid="draft-cancel" onClick={() => setDraftOpen(false)}>
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
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
