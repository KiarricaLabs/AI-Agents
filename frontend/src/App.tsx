import { useEffect, useRef, useState, type ReactNode } from "react";
import { diffLines } from "./diff";
import { Markdown } from "./markdown";
import { KNOWN_SAMPLE_IDS } from "./knownSamples";
import { statusLabel, priorityText } from "./uiText";
import { proposeTeamGoal, validateTeamGoalDraft, runAgentStream } from "./coordination";
import { TeamMemory } from "./team_memory";
import { TeamChat } from "./team_chat";
import { CommandCenterSidebar } from "./command_center_sidebar";
import { WorkflowOverview } from "./workflow_overview";
import { StructuredProjects } from "./structured_projects";
import { VoicePanel } from "./voice/VoicePanel";
import "./App.css";

const API = (import.meta.env.VITE_API_BASE as string | undefined) || "http://127.0.0.1:8001";

// Matches an explicit workspace-creation request so the chat offers a reliable
// "propose workspace" path (the model may not emit a valid proposal itself).
const WS_INTENT_RE = /(?:create|make|set up|start|add|open|new|build|establish)[\s\S]{0,40}workspace/i;

// Browser-only, presentation-level storage keys for the sample-data control.
const SAMPLE_VISIBLE_KEY = "pat.sampleData.visible";
const SAMPLE_REVEALED_KEY = "pat.sampleData.revealed";

type Tab = "home" | "agents" | "projects" | "tasks" | "settings";

const NAV: { id: Tab; icon: string; label: string }[] = [
  { id: "home", icon: "home", label: "Home" },
  { id: "agents", icon: "bot", label: "Agents" },
  { id: "projects", icon: "briefcase", label: "Projects" },
  { id: "tasks", icon: "checklist", label: "Task Center" },
  { id: "settings", icon: "gear", label: "Settings" },
];

const NAV_HINTS: Record<Tab, string> = {
  home: "Chat",
  agents: "Run",
  projects: "Plans",
  tasks: "Review",
  settings: "Learn",
};

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
    gear: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h0a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55h0a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v0a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" />
      </>
    ),
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

// Human-readable work-type label for the proposal feed.
const WORK_TYPE_LABEL: Record<string, string> = {
  workspace: "Workspace",
  project: "Project",
  goal: "Goal",
  goal_update: "Goal update",
  assignment: "Assignment",
  deliverable: "Deliverable",
  deliverable_version: "Deliverable version",
};

// Extract the actual generated name/title from a proposal payload, falling back
// to a truthful generic string. Never invents a title.
function proposalTitle(p: any): string {
  const payload = p?.payload || {};
  for (const key of ["title", "name", "content", "summary"]) {
    const v = payload[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  // fall back to a labeled description of the work type + action
  const w = WORK_TYPE_LABEL[p?.work_type] || p?.work_type || "work";
  return `New ${w}`;
}

// A short, truthful "what happens next" hint for the proposal feed.
function proposalNextStep(p: any): string {
  if (p?.status === "proposed") return "Approve to create, or reject.";
  if (p?.status === "approved") return "Approved — see it under the relevant section.";
  if (p?.status === "rejected") return "Not applied.";
  if (p?.status === "stale") return "Outdated — superseded by a newer change.";
  return "";
}

// Human-facing label for Task Center statuses (Phase 4).
const TASK_STATUS_LABEL: Record<string, string> = {
  awaiting_assignment: "Awaiting assignment",
  awaiting_execution: "Awaiting execution",
  in_progress: "In progress",
  needs_input: "Needs your input",
  ready_for_review: "Ready for review",
  revision_requested: "Revision requested",
  completed: "Completed",
  rejected: "Rejected",
};
function taskStatusLabel(s: string | null | undefined): string {
  if (!s) return "—";
  return TASK_STATUS_LABEL[s] || s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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

const STANDARD_AGENTS = ["strategist", "communications", "tutor", "executive_assistant", "workspace_architect", "soundboard"];

export default function App() {
  const [tab, setTab] = useState<Tab>("home");
  // Task Center <-> chat linkage: open a conversation thread in the group chat.
  // The group chat reads its active thread from localStorage on mount.
  const openThreadInChat = (threadId: string) => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("ai-team-shared-thread", threadId);
    }
    setTab("home");
  };
  // Projects tab is segmented: "browse" (workspaces/projects) vs "proposals".
  const [projectsSection, setProjectsSection] = useState<"browse" | "proposals">("browse");
  const [health, setHealth] = useState("checking...");
  const [systemReady, setSystemReady] = useState<"checking" | "ready" | "not-ready" | "unavailable">("checking");
  const [queuedCount, setQueuedCount] = useState<number | null>(null);
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
  const [agentStreaming, setAgentStreaming] = useState(false);
  const [agentResult, setAgentResult] = useState<any>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const runTokenRef = useRef(0);
  const statusInFlightRef = useRef(false);
  const [agentError, setAgentError] = useState("");
  const [recentRuns, setRecentRuns] = useState<any[]>([]);
  const [recentRunsLoading, setRecentRunsLoading] = useState(false);
  const [recentRunsError, setRecentRunsError] = useState("");
  const [recentAgentFilter, setRecentAgentFilter] = useState("");
  const [recentStatusFilter, setRecentStatusFilter] = useState("");
  const [recentOffset, setRecentOffset] = useState(0);
  const RECENT_LIMIT = 10;
  const [staleRuns, setStaleRuns] = useState<any[]>([]);
  const [staleLoading, setStaleLoading] = useState(false);
  const [approvalsPreview, setApprovalsPreview] = useState<any[]>([]);
  const [queueInfo, setQueueInfo] = useState<any>(null);
  const [queueLoading, setQueueLoading] = useState(false);
  const [queueError, setQueueError] = useState("");
  const [recentFailures, setRecentFailures] = useState<any[]>([]);
  const [failuresLoading, setFailuresLoading] = useState(false);
  const [failuresError, setFailuresError] = useState("");
  const [threadRuns, setThreadRuns] = useState<any[]>([]);
  // Clear stale result/error when the selected agent changes; preserve task input.
  useEffect(() => {
    setAgentResult(null);
    setAgentError("");
  }, [selectedAgent]);

  const loadRecentRuns = async () => {
    setRecentRunsLoading(true);
    setRecentRunsError("");
    try {
      const params = new URLSearchParams();
      params.set("limit", String(RECENT_LIMIT));
      params.set("offset", String(recentOffset));
      if (recentAgentFilter) params.set("agent", recentAgentFilter);
      if (recentStatusFilter) params.set("status", recentStatusFilter);
      const r = await fetch(`${API}/agents/runs?${params.toString()}`, { headers: { "x-token": localStorage.getItem("pat_token") || "" } });
      if (r.ok) {
        const data = await r.json();
        setRecentRuns(data.items || []);
      } else {
        setRecentRunsError("Failed to load history.");
      }
    } catch {
      setRecentRunsError("Failed to load history.");
    } finally {
      setRecentRunsLoading(false);
    }
  };
  useEffect(() => { if (tab === "agents") loadRecentRuns(); }, [tab, recentOffset, recentAgentFilter, recentStatusFilter]);
  const loadStaleRuns = async () => {
    setStaleLoading(true);
    try { const r = await fetch(`${API}/runs/stale`, { headers: { "x-token": localStorage.getItem("pat_token") || "" } }); if (r.ok) { const d = await r.json(); setStaleRuns(d.stale || d.items || []); } } catch {} finally { setStaleLoading(false); }
  };
  const loadApprovalsPreview = async () => {
    try { const r = await fetch(`${API}/work/proposals?status=pending&limit=3`, { headers: { "x-token": localStorage.getItem("pat_token") || "" } }); if (r.ok) { const d = await r.json(); setApprovalsPreview(d.items || d.proposals || []); } } catch {}
  };
  const loadQueueInfo = async () => { setQueueLoading(true); setQueueError(""); try { const r = await fetch(`${API}/runs/queue`, { headers: { "x-token": localStorage.getItem("pat_token") || "" } }); if (!r.ok) throw new Error(); const d = await r.json(); if (typeof d.running_count!=="number" || typeof d.queued_count!=="number") throw new Error(); setQueueInfo(d); } catch { setQueueError("Activity unavailable."); } finally { setQueueLoading(false); } };
  const loadRecentFailures = async () => { setFailuresLoading(true); setFailuresError(""); try { const r = await fetch(`${API}/agents/runs?status=failed&limit=3`, { headers: { "x-token": localStorage.getItem("pat_token") || "" } }); if (!r.ok) throw new Error(); const d = await r.json(); setRecentFailures(d.items || []); } catch { setFailuresError("Failures unavailable."); } finally { setFailuresLoading(false); } };
  const loadThreadRuns = async () => { const tid = localStorage.getItem("ai-team-shared-thread"); if (!tid) return; try { const r = await fetch(`${API}/agents/runs?thread_id=${encodeURIComponent(tid)}&limit=5`, { headers: { "x-token": localStorage.getItem("pat_token") || "" } }); if (r.ok) { const d = await r.json(); setThreadRuns(d.items || []); } } catch {} };
  useEffect(() => { if (tab === "home") { loadStaleRuns(); loadApprovalsPreview(); loadQueueInfo(); loadRecentFailures(); loadThreadRuns(); } }, [tab]);
  // --- Chunk 5: conversation -> assignment/deliverable draft extraction ---
  const [extractBusy, setExtractBusy] = useState(false);
  const [extractError, setExtractError] = useState("");
  const [extractDraft, setExtractDraft] = useState<any | null>(null);
  const [extractMsg, setExtractMsg] = useState("");
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
  // --- Phase 4: Task Center ---
  const [tasks, setTasks] = useState<any[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [taskStatusFilter, setTaskStatusFilter] = useState<string>("");
  const [taskSearch, setTaskSearch] = useState<string>("");
  // Conversation -> task bridge (M2 backend).
  const [convTaskThread, setConvTaskThread] = useState<string | null>(null);
  const [convTaskTitle, setConvTaskTitle] = useState<string>("");
  const [convTaskGoal, setConvTaskGoal] = useState<string>("");
  const [convTaskBusy, setConvTaskBusy] = useState(false);
  const [convTaskMsg, setConvTaskMsg] = useState<string | null>(null);
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
  // Delegate the generated plan as a runnable coordination TeamGoal.
  const [planDelegateBusy, setPlanDelegateBusy] = useState(false);
  const [planDelegateMsg, setPlanDelegateMsg] = useState<string | null>(null);

  useEffect(() => {
    return () => { streamAbortRef.current?.abort(); };
  }, []);
  useEffect(() => {
    let cancelled = false;
    const refreshStatus = async () => {
      if (statusInFlightRef.current) return;
      statusInFlightRef.current = true;
      try {
        const r = await fetch(`${API}/ready`);
        if (cancelled) return;
        if (!r.ok) { setSystemReady("unavailable"); setQueuedCount(null); return; }
        const d = await r.json().catch(() => ({}));
        if (cancelled) return;
        setSystemReady(d && d.ready ? "ready" : "not-ready");
        try {
          const qr = await fetch(`${API}/runs/queue`);
          if (cancelled) return;
          if (qr.ok) {
            const qd = await qr.json().catch(() => ({}));
            if (!cancelled) setQueuedCount(typeof qd.queued_count === "number" ? qd.queued_count : null);
          } else {
            if (!cancelled) setQueuedCount(null);
          }
        } catch {
          if (!cancelled) setQueuedCount(null);
        }
      } catch {
        if (!cancelled) { setSystemReady("unavailable"); setQueuedCount(null); }
      } finally {
        statusInFlightRef.current = false;
      }
    };
    refreshStatus();
    const id = setInterval(refreshStatus, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);
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

  // D4.3 read-only tool wiring: run the safe ``calculate`` tool on the typed
  // expression. The backend whitelists + manifest/policy gates it read-only;
  // the result is surfaced via the existing tool_results panel.
  const runCalculate = async () => {
    if (offline || agentRunning || !selectedAgent || !task.trim()) return;
    const expr = task.trim();
    const submitted = `Using the calculate tool, evaluate this expression and report the result: ${expr}`;
    setAgentRunning(true);
    setAgentError("");
    setAgentResult(null);
    setAgentGenError(null);
    setAgentRetryTask(null);
    setAgentRetryThread(null);
    const payload: any = {
      task: submitted,
      tool_calls: [{ tool: "calculate", args: { expression: expr }, approved: true }],
    };
    if (threadIds[selectedAgent]) payload.thread_id = threadIds[selectedAgent];
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

  // Bridge the Generated team plan into the coordination pipeline: build a
  // TeamGoal from the plan steps (validated + auto-reassigned like chat
  // delegation), propose it, and refresh the coordination/review panels. This
  // unifies Projects' "New Objective" and the chat's "Delegate" entry points.
  const delegatePlanToTeam = async () => {
    const steps = planResult?.steps || [];
    if (!steps.length || planDelegateBusy) return;
    const coordinator = planResult?.coordinator || "workspace_architect";
    setPlanDelegateBusy(true);
    setPlanDelegateMsg(null);
    try {
      let teamSteps = steps.map((s: any, idx: number) => ({
        seq: idx + 1,
        agent_id: (s.owner || s.suggested_agent || "workspace_architect"),
        responsibility: ((s.title || "").trim()) || `Step ${idx + 1}`,
        depends_on_seq: idx === 0 ? null : idx,
      }));
      // Validate + auto-reassign invalid steps to a capable delegable agent.
      try {
        const val = await validateTeamGoalDraft(coordinator, teamSteps);
        if (!val.plan_valid) {
          const reassigned: string[] = [];
          let blocking = "";
          teamSteps = val.steps.map((vs: any) => {
            if (vs.valid || !vs.suggested_agent_id) {
              if (!vs.valid) blocking = blocking || (vs.error || `step ${vs.seq} cannot be assigned`);
              return { seq: vs.seq, agent_id: vs.suggested_agent_id || vs.agent_id, responsibility: vs.responsibility, depends_on_seq: vs.depends_on_seq ?? null };
            }
            reassigned.push(`step ${vs.seq}: ${vs.agent_id} → ${vs.suggested_agent_id}`);
            return { seq: vs.seq, agent_id: vs.suggested_agent_id, responsibility: vs.responsibility, depends_on_seq: vs.depends_on_seq ?? null };
          });
          if (blocking) {
            setPlanDelegateMsg(`Could not create a team goal: ${blocking}. Fix the plan steps or choose a different coordinator.`);
            return;
          }
          if (reassigned.length) setPlanDelegateMsg(`Auto-assigned ${reassigned.length} ${reassigned.length === 1 ? "step" : "steps"} to capable agents (${reassigned.join("; ")}). `);
        }
      } catch { /* validation unavailable — propose as-is */ }
      const created = await proposeTeamGoal({
        title: (planResult?.title || planObjective.trim() || "Team goal").slice(0, 120),
        coordinator_agent: coordinator,
        summary: planObjective.trim() || undefined,
        steps: teamSteps,
      });
      window.dispatchEvent(new CustomEvent("ai-team:goal-created"));
      setPlanDelegateMsg((planDelegateMsg ? planDelegateMsg + " " : "") +
        (created.status === "proposed"
          ? "TeamGoal proposed (proposed). On Home: approve → authorize → Run all → accept, and it materializes into Projects."
          : `TeamGoal created (${created.status}).`));
    } catch (e) {
      const detail = (e as any)?.message || (e as any)?.detail;
      setPlanDelegateMsg(detail ? `Could not create team goal: ${detail}` : "Could not create team goal.");
    } finally {
      setPlanDelegateBusy(false);
    }
  };

  // Shared POST handler. `payload.retry` tells the backend not to persist a
  // duplicate user message for an already-saved task. It never repeats
  // consequential tool calls, proposals, or execution.
  const performRun = async (submitted: string, payload: any) => {
    const eligible =
      !payload?.work_intent &&
      !(Array.isArray(payload?.tool_calls) && payload.tool_calls.length) &&
      STANDARD_AGENTS.includes(selectedAgent);
    const token = ++runTokenRef.current;
    if (eligible) {
      const controller = new AbortController();
      streamAbortRef.current = controller;
      setAgentRunning(true);
      setAgentStreaming(true);
      setAgentError("");
      setAgentResult({ reply: "", thread_id: payload?.thread_id || null });
      setAgentGenError(null);
      try {
        await runAgentStream(selectedAgent, payload, {
          onChunk: (text) => {
            if (runTokenRef.current !== token) return;
            setAgentResult((prev: any) => ({ ...(prev || {}), reply: (prev?.reply || "") + text }));
          },
          onDone: (meta) => {
            if (runTokenRef.current !== token) return;
            setAgentResult((prev: any) => ({ ...(prev || {}), reply: meta.reply ?? prev?.reply ?? "", thread_id: meta.thread_id ?? prev?.thread_id }));
            if (meta.thread_id) setThreadIds((prev) => ({ ...prev, [selectedAgent]: meta.thread_id as string }));
            setAgentStreaming(false);
            setAgentRunning(false);
            loadRecentRuns();
          },
          onError: (msg) => {
            if (runTokenRef.current !== token) return;
            setAgentError(msg);
            setAgentStreaming(false);
            setAgentRunning(false);
            loadRecentRuns();
          },
        }, controller.signal);
        if (controller.signal.aborted) {
          setAgentStreaming(false);
          setAgentRunning(false);
        } else if (runTokenRef.current === token) {
          // ensure terminal if stream ended without callback
          setAgentStreaming(false);
          setAgentRunning(false);
        }
      } catch (e: any) {
        if (runTokenRef.current !== token) return;
        setAgentError(e?.message || "network error");
        setAgentStreaming(false);
        setAgentRunning(false);
      } finally {
        if (streamAbortRef.current === controller) streamAbortRef.current = null;
      }
      return;
    }
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
        loadRecentRuns();
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
        loadRecentRuns();
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
      await loadTasks();
    } catch {
      setOffline(true);
    }
  };

  const deleteGoal = async (id: string) => {
    try {
      await fetch(`${API}/workspaces/goals/${encodeURIComponent(id)}`, { method: "DELETE" });
      setSelectedGoal(null);
      await refresh();
    } catch { /* offline */ }
  };

  const deleteDeliverable = async (id: string) => {
    try {
      await fetch(`${API}/workspaces/deliverables/${encodeURIComponent(id)}`, { method: "DELETE" });
      await refresh();
    } catch { /* offline */ }
  };

  const deleteProject = async (id: string) => {
    try {
      await fetch(`${API}/workspaces/projects/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (selectedProjectId === id) setSelectedProjectId(null);
      await refresh();
    } catch { /* offline */ }
  };

  const deleteWorkspace = async (id: string) => {
    try {
      await fetch(`${API}/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (selectedWorkspaceId === id) { setSelectedWorkspaceId(null); setSelectedProjectId(null); }
      await refresh();
    } catch { /* offline */ }
  };

  const deleteTask = async (id: string) => {
    try {
      await fetch(`${API}/tasks/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadTasks();
    } catch { /* offline */ }
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

  // --- Phase 4: Task Center data ---
  const loadTasks = async () => {
    setTasksLoading(true);
    setTasksError(null);
    try {
      const r = await fetch(`${API}/tasks`);
      if (!r.ok) {
        setTasksError("Could not load tasks.");
        return;
      }
      const d = await r.json();
      setTasks(d.items || []);
    } catch {
      setTasksError("Could not load tasks (offline?).");
    } finally {
      setTasksLoading(false);
    }
  };

  // Conversation -> task bridge (M2). Creates a proposal only; nothing is
  // created or executed until a human approves it in the review flow.
  const submitConversationToTask = async (threadId: string) => {
    if (offline || convTaskBusy) return;
    if (!convTaskTitle.trim()) { setConvTaskMsg("Give the task a short title."); return; }
    const goalId = convTaskGoal;
    if (!goalId) { setConvTaskMsg("Choose the goal this task should be attached to."); return; }
    setConvTaskBusy(true);
    setConvTaskMsg(null);
    try {
      const r = await fetch(`${API}/conversations/${encodeURIComponent(threadId)}/to-task`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal_id: goalId,
          title: convTaskTitle.trim(),
          agent_id: selectedAgent || "",
        }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setConvTaskMsg((b as any).detail || `Could not create the proposal (${r.status}).`);
        return;
      }
      setConvTaskMsg("Proposal created — review and approve it to turn this conversation into work.");
      setConvTaskTitle("");
      setConvTaskGoal("");
      setConvTaskThread(null);
      await loadFeed();
      await loadTasks();
    } catch {
      setConvTaskMsg("Could not create the proposal. Please try again.");
    } finally {
      setConvTaskBusy(false);
    }
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

  // Chunk 5: extract an editable assignment/deliverable DRAFT from the typed
  // message. Drafts persist nothing; the human proposes them for approval below.
  const runExtract = async (kind: string) => {
    if (offline || extractBusy) return;
    const trimmed = task.trim();
    if (!trimmed) return setExtractError("Type a message to extract from first.");
    setExtractBusy(true);
    setExtractError("");
    setExtractMsg("");
    setExtractDraft(null);
    try {
      const body: any = { kind, message: trimmed };
      if (kind === "assignment") body.subject_agent = selectedAgent || "workspace_architect";
      else body.owner_agent = selectedAgent || undefined;
      const r = await fetch(`${API}/work/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setExtractError((b as any).detail || `Could not extract a draft (${r.status}).`);
        return;
      }
      setExtractDraft(b.draft);
      setExtractMsg(`Draft ${kind} extracted — edit the details, pick a target, then propose for approval.`);
    } catch {
      setExtractError("Could not extract a draft. Please try again.");
    } finally {
      setExtractBusy(false);
    }
  };

  // Chunk 5: turn the edited extract draft into a work proposal (existing,
  // human-only /work/proposals flow). Nothing is created until the human approves.
  const proposeExtracted = async () => {
    if (offline || extractBusy) return;
    if (!extractDraft) return;
    setExtractBusy(true);
    setExtractError("");
    setExtractMsg("");
    try {
      const kind = extractDraft.kind;
      let work_type = kind;
      let payload: any = {};
      let target_id: string | undefined;
      if (kind === "assignment") {
        const gid = draftGoal || goalsIn(selectedProjectId || "")[0]?.id;
        if (!gid) {
          setExtractError("Pick a project with a goal to attach the assignment to.");
          return;
        }
        work_type = "assignment";
        payload = { goal_id: gid, agent_id: extractDraft.subject_agent || "workspace_architect" };
      } else {
        const pid = selectedProjectId || projects[0]?.id;
        if (!pid) {
          setExtractError("Pick a project to attach the deliverable to.");
          return;
        }
        work_type = "deliverable";
        payload = { project_id: pid, title: extractDraft.title || "New deliverable" };
      }
      const r = await fetch(`${API}/work/proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ work_type, action: "create", payload, target_id, agent_id: extractDraft.subject_agent || selectedAgent || "workspace_architect" }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setExtractError((b as any).detail || `Could not create the proposal (${r.status}).`);
        return;
      }
      setExtractMsg("Proposal created — approve it in Work · Approvals to create the real record.");
      setExtractDraft(null);
      await loadFeed();
    } catch {
      setExtractError("Could not create the proposal. Please try again.");
    } finally {
      setExtractBusy(false);
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
    setTab("home");
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
    setTab("projects");
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
    setTab("projects");
    setSelectedDeliverable(null);
    setSelectedGoal(null);
    setSelectedProjectId(pid || null);
    setSelectedWorkspaceId(p ? p.workspace_id : null);
  };
  const goToGoal = (gid: string) => {
    const g = goals.find((x) => x.id === gid);
    const p = g ? projects.find((x) => x.id === g.project_id) : undefined;
    setTab("projects");
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
          <span className="status__chip" data-testid="system-status">
            {systemReady === "checking" ? "System: checking…" : systemReady === "ready" ? `System: ready${queuedCount !== null && queuedCount > 0 ? ` · ${queuedCount} queued` : ""}` : systemReady === "not-ready" ? "System: not ready" : "System: unavailable"}
          </span>
          {agentStreaming && (
            <span className="status__chip" data-testid="agent-streaming-indicator">Agent is responding…</span>
          )}
          {agentStreaming && (
            <button
              className="status__chip"
              data-testid="agent-stop-button"
              type="button"
              onClick={() => { streamAbortRef.current?.abort(); }}
            >
              Stop
            </button>
          )}
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
            data-route={n.id}
            className={`nav__btn${tab === n.id ? " nav__btn--active" : ""}`}
            onClick={() => { setTab(n.id); if (n.id === "tasks") { loadFeed(); loadTasks(); } }}
            aria-label={n.label}
          >
            <Icon name={n.icon} />
            <span className="nav__copy">
              <span className="nav__label">{n.label}</span>
              <span className="nav__hint">{NAV_HINTS[n.id]}</span>
            </span>
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
        {tab === "home" && (
          <section className="command-center">
            <div className="command-center__welcome">
              <div>
                <span className="eyebrow">ON US AI TEAM · COMMAND CENTER</span>
                <h2>Good morning. What are we working on?</h2>
                <p>Your AI team's command center: send one message to the room. The coordinator will bring in the right teammates, explain the plan, and wait for your approval.</p>
              </div>
              <div className="command-center__status"><span /> Local and ready</div>
            </div>

            <div className="stats">
              <Stat icon="bot" label="Teammates" value={agents.length} />
              <Stat icon="comments" label="Discussions" value={conversations.length} />
              <Stat icon="inbox" label="Awaiting your review" value={(feed || []).filter((p) => p && p.status === "proposed").length} />
              <Stat icon="layers" label="Proposals" value={(feed || []).length} />
            </div>
            <div className="flow-legend" aria-label="Approval flow">
              <span className="flow-legend__active">Chat</span><i>›</i><span>Plans</span><i>›</i><span>Review</span><i>›</i><span>Execute</span><i>›</i><span>Learn</span>
            </div>

            <div className="command-center__layout">
              <div className="command-center__main">
                <div className="workspace-label"><span>01</span><div><strong>Group chat</strong><small>Coordinate with your whole AI team</small></div></div>
                <TeamChat onOpenTasks={() => setTab("tasks")} />
                <VoicePanel />

                {(() => {
                  const pendingApprovals = (feed || []).filter((p) => p && p.status === "proposed").length;
                  const runningEps = (episodes || []).filter((e) => e && e.status === "running").length;
                  const doneEps = (episodes || []).filter((e) => e && e.status === "done").length;
                  const ownedBy: Record<string, number> = {};
                  (assignments || []).forEach((a: any) => {
                    ownedBy[a.agent_id || "?"] = (ownedBy[a.agent_id || "?"] || 0) + 1;
                  });
                  return (
                    <div className="command-status" data-testid="coord-status">
                      <span className="command-status__label">Your command center</span>
                      <span><b data-testid="coord-pending">{pendingApprovals}</b> awaiting approval</span>
                      <span><b data-testid="coord-running">{runningEps}</b> in progress</span>
                      <span><b data-testid="coord-done">{doneEps}</b> completed</span>
                      {Object.entries(ownedBy).map(([slug, n]) => (
                        <span key={slug} data-testid={`coord-owner-${slug}`}>{agentDisplay(slug)} · {n}</span>
                      ))}
                    </div>
                  );
                })()}

                <div className="workspace-label workspace-label--plans"><span>02</span><div><strong>Structured project workflow</strong><small>Review the plan, run approved tasks, and review drafts</small></div></div>
                <StructuredProjects />
              </div>
              <div className="command-center__rail">
                <CommandCenterSidebar />
                <div className="command-card" style={{ marginTop: 12 }}>
                  <h4 style={{ margin: "0 0 8px" }}>Stale Runs {staleRuns.length > 0 ? `· ${staleRuns.length}` : ""}</h4>
                  {staleLoading ? <div>Loading…</div> : staleRuns.length === 0 ? <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No stale runs.</div> : staleRuns.slice(0,5).map((r: any, i: number) => (
                    <div key={i} style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
                      {r.agent_id || r.agent || r.id} · {r.started_at ? Math.round((Date.now() - new Date(r.started_at).getTime())/1000/60) + "m ago" : ""}
                    </div>
                  ))}
                </div>
                <div className="command-card" style={{ marginTop: 12 }}>
                  <h4 style={{ margin: "0 0 8px" }}>Activity</h4>
                  {queueLoading ? <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Loading…</div> : queueError ? <div style={{ fontSize: 12, color: "var(--red)" }}>{queueError}</div> : queueInfo ? <div style={{ fontSize: 12, display: "flex", gap: 12 }}><span>Running: {queueInfo.running_count}</span><span>Queued: {queueInfo.queued_count}</span></div> : <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Unavailable</div>}
                </div>
                <div className="command-card" style={{ marginTop: 12 }}>
                  <h4 style={{ margin: "0 0 8px" }}>Recent Failures</h4>
                  {failuresLoading ? <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Loading…</div> : failuresError ? <div style={{ fontSize: 12, color: "var(--red)" }}>{failuresError}</div> : recentFailures.length===0 ? <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No recent failures.</div> : recentFailures.map((f:any,i:number)=>{
                    const dur = f.created_at && f.finished_at ? Math.round((new Date(f.finished_at).getTime()-new Date(f.created_at).getTime())/1000) : null;
                    return (<div key={i} style={{ fontSize: 12, padding: "6px 0", borderBottom: "1px solid var(--border)" }}><div style={{ display: "flex", justifyContent: "space-between" }}><span><span style={{color:"var(--red)"}}>●</span> {f.agent_id} · {f.error_category || "failed"}</span><span style={{ color: "var(--text-faint)" }}>{f.finished_at ? new Date(f.finished_at).toLocaleTimeString() : ""}{dur!==null?` · ${dur}s`:""}</span></div>{f.task_summary && <div style={{ color: "var(--text-muted)", marginTop: 2, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.task_summary.slice(0,80)}</div>}</div>)
                  })}
                  {recentFailures.length>0 && <button className="btn btn--ghost" style={{ marginTop: 8, fontSize: 11 }} onClick={()=>{ setTab("agents" as any); setRecentStatusFilter("failed"); setRecentOffset(0); }}>View all failed runs</button>}
                </div>
                <div className="command-card" style={{ marginTop: 12 }}>
                  <h4 style={{ margin: "0 0 8px" }}>Thread Activity</h4>
                  {threadRuns.length===0 ? <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No runs for this thread.</div> : threadRuns.map((r:any,i:number)=><div key={i} style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px solid var(--border)" }}>{r.agent_id} · {r.status}</div>)}
                </div>
                <div className="command-card" style={{ marginTop: 12 }}>
                  <h4 style={{ margin: "0 0 8px" }}>Approvals {approvalsPreview.length > 0 ? `· ${approvalsPreview.length}` : ""}</h4>
                  {approvalsPreview.length === 0 ? <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No pending approvals.</div> : approvalsPreview.map((p: any, i: number) => (
                    <div key={i} style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px solid var(--border)" }}>{p.title || p.key || p.id}</div>
                  ))}
                  {approvalsPreview.length > 0 && <button className="btn btn--ghost" style={{ marginTop: 8 }} onClick={()=>setTab("tasks" as any)}>View inbox</button>}
                </div>
              </div>
            </div>
          </section>
        )}

                {tab === "agents" && (
          <section className="panel" data-testid="agents-tab">
            <div className="panel__head"><h2>Agent execution</h2></div>
            <div className="row" style={{ gap: 8, marginBottom: 12 }}>
              <select className="select" value={selectedAgent} onChange={(e) => setSelectedAgent(e.target.value)} aria-label="Select agent" data-testid="agent-select">
                <option value="">Select an agent…</option>
                {STANDARD_AGENTS.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
            <div className="row" style={{ gap: 8, marginBottom: 12 }}>
              <input className="input" value={task} onChange={(e) => setTask(e.target.value)} placeholder="Enter a task…" data-testid="agent-task" />
              <button className="btn btn--primary" onClick={runAgent} disabled={agentRunning || !selectedAgent || !task.trim()} data-testid="agent-run">Run</button>
              {agentStreaming && (
                <button className="btn" data-testid="agent-stop-button" type="button" onClick={() => { streamAbortRef.current?.abort(); }}>Stop</button>
              )}
            </div>
            {agentStreaming && <div data-testid="agent-streaming-indicator">Agent is responding…</div>}
            {agentError && <div className="error" data-testid="agent-error">{agentError}</div>}
            {agentResult && agentResult.reply && (
              <div className="panel" data-testid="agent-result">
                <Markdown source={agentResult.reply} />
              </div>
            )}
            <section className="panel" data-testid="recent-runs">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h3>Recent Runs</h3>
                <button className="btn" onClick={loadRecentRuns} disabled={recentRunsLoading}>Refresh</button>
              </div>
              <div style={{ display: "flex", gap: 8, margin: "8px 0" }}>
                <input placeholder="agent filter" value={recentAgentFilter} onChange={(e) => { setRecentAgentFilter(e.target.value); setRecentOffset(0); }} />
                <select value={recentStatusFilter} onChange={(e) => { setRecentStatusFilter(e.target.value); setRecentOffset(0); }}>
                  <option value="">all statuses</option>
                  <option value="completed">completed</option>
                  <option value="failed">failed</option>
                  <option value="rejected">rejected</option>
                  <option value="cancelled">cancelled</option>
                </select>
                {(recentAgentFilter || recentStatusFilter) && (
                  <button className="btn" onClick={() => { setRecentAgentFilter(""); setRecentStatusFilter(""); setRecentOffset(0); }}>Clear</button>
                )}
              </div>
              {recentRunsLoading && <div>Loading…</div>}
              {recentRunsError && <div className="error">{recentRunsError} <button className="btn" onClick={loadRecentRuns}>Retry</button></div>}
              {!recentRunsLoading && !recentRunsError && recentRuns.length === 0 && <div>No runs yet.</div>}
              {recentRuns.map((run) => (
                <div key={run.run_id} style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>
                  <strong>{run.agent_id}</strong> — {run.status} — {run.task_summary}
                  <div style={{ fontSize: 12, opacity: 0.7 }}>{run.created_at}</div>
                </div>
              ))}
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button className="btn" disabled={recentOffset === 0} onClick={() => setRecentOffset((o) => Math.max(0, o - RECENT_LIMIT))}>Prev</button>
                <button className="btn" disabled={recentRuns.length < RECENT_LIMIT} onClick={() => setRecentOffset((o) => o + RECENT_LIMIT)}>Next</button>
              </div>
            </section>
          </section>
        )}

                {tab === "projects" && (
          <section className="panel">
            <StructuredProjects />
          </section>
        )}

        

{tab === "tasks" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Review queue</h2>
                <p className="panel__sub">Approve, revise, or reject proposed work before it can move into execution.</p>
                <button className="btn btn--sm btn--ghost" data-testid="open-coordination" onClick={() => setTab("projects")}>
                  Open structured projects
                </button>
              </div>
            </div>
            <WorkflowOverview stage="review" onOpenCoordination={() => setTab("home")} />
            <div className="work-toolbar" style={{ flexWrap: "wrap" }}>
              <select className="select select--small" value={taskStatusFilter} onChange={(e) => setTaskStatusFilter(e.target.value)} aria-label="Task status filter" data-testid="task-status-filter">
                <option value="">All statuses</option>
                <option value="awaiting_assignment">Awaiting assignment</option>
                <option value="awaiting_execution">Awaiting execution</option>
                <option value="in_progress">In progress</option>
                <option value="needs_input">Needs your input</option>
                <option value="ready_for_review">Ready for review</option>
                <option value="revision_requested">Revision requested</option>
                <option value="completed">Completed</option>
                <option value="rejected">Rejected</option>
              </select>
              <input className="input work-search" value={taskSearch} onChange={(e) => setTaskSearch(e.target.value)} placeholder="Search tasks…" aria-label="Search tasks" />
              <button className="btn btn--ghost btn--sm" onClick={loadTasks} disabled={offline}>Refresh</button>
            </div>

            {tasksError && <p className="error" role="alert">{tasksError}</p>}
            {tasksLoading ? (
              <Empty text="Loading tasks…" />
            ) : tasks.length === 0 ? (
              <Empty text="No tasks yet. Ask the AI team to propose work, or create a project and plan." />
            ) : (
              <ul className="list">
                {tasks
                  .filter((t) => !taskStatusFilter || t.status === taskStatusFilter)
                  .filter((t) => !taskSearch || (t.title || "").toLowerCase().includes(taskSearch.trim().toLowerCase()))
                  .map((t) => {
                    const st = t.status || "";
                    return (
                      <li key={t.task_id} className="list__item tasks-item" data-testid={`task-${t.task_id}`}>
                        <div className="tasks-item__main">
                          <Icon name={st === "completed" ? "checklist" : st === "ready_for_review" ? "file" : "target"} size={16} />
                          <span className="list__name"><strong>{t.title || "Untitled task"}</strong></span>
                          {t.agent_id && <span className="badge badge--faint">{agentLabel(t.agent_id)}</span>}
                          <span className={`badge badge--${st}`}>{taskStatusLabel(st)}</span>
                        </div>
                        <div className="tasks-item__meta">
                          {t.project_name && <span className="muted">{t.project_name}</span>}
                          {t.goal_title && <span className="muted"> · {t.goal_title}</span>}
                          {t.thread_ids?.length ? (
                            <span className="muted"> · from conversation{" "}
                              <button className="origin-link" data-testid={`task-open-chat-${t.task_id}`}
                                onClick={() => openThreadInChat(t.thread_ids[0])}>
                                Open in chat
                              </button>
                            </span>
                          ) : null}
                        </div>
                        {t.description && <p className="muted">{t.description}</p>}
                        <p className="muted"><em>{t.next_action}</em></p>
                        {t.deliverable && (
                          <div className="tasks-item__deliv">
                            <span className="badge badge--faint">Deliverable: {t.deliverable.title}</span>
                            <span className={`badge badge--${t.deliverable.status}`}>{t.deliverable.status}</span>
                          </div>
                        )}
                        {st === "awaiting_assignment" && (
                          <div className="tasks-item__actions">
                            <button className="btn btn--sm btn--ghost" disabled={true} title="Approve via Projects · Proposals">Approve in Projects</button>
                            <button className="btn btn--sm btn--ghost" data-testid={`delete-task-${t.task_id}`} onClick={() => deleteTask(t.task_id)}>Delete</button>
                          </div>
                        )}
                        {st !== "awaiting_assignment" && (
                          <div className="tasks-item__actions">
                            <button className="btn btn--sm btn--ghost" data-testid={`delete-task-${t.task_id}`} onClick={() => deleteTask(t.task_id)}>Delete</button>
                          </div>
                        )}
                      </li>
                    );
                  })}
              </ul>
            )}

            <TeamMemory agentDisplay={(slug) => agentLabel(slug || "")} />
          </section>
        )}

        {tab === "settings" && (
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">Settings</h2>
                <p className="panel__sub">Shape how the team learns and prepare secure connections for a future phase.</p>
              </div>
              <WorkflowOverview stage="learn" onOpenCoordination={() => setTab("home")} />
            </div>

            <div className="subsection">
              <div className="subsection__head"><h3 className="section-title">Sample &amp; test data</h3></div>
              <div className="work-toolbar" style={{ flexWrap: "wrap" }}>
                <button className="btn btn--sm btn--ghost" onClick={toggleAllSamples}>
                  {sampleDataVisible ? "Hide sample data" : "Show sample data"}
                </button>
                <button className="btn btn--sm btn--ghost" onClick={() => setManageSamples(true)}>Manage samples</button>
                <span className="sample-bar__hint">
                  {sampleDataVisible
                    ? "Showing all records, including sample data."
                    : "Sample/test data is hidden. Your own records are never hidden."}
                </span>
              </div>
            </div>

            <div className="subsection">
              <div className="subsection__head"><h3 className="section-title">Preferences</h3></div>
              <p className="muted">Other preference controls will appear here as they're added.</p>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
