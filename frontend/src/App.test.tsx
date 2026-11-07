import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import App from "./App";
import { TeamMemory } from "./team_memory";
import { TeamChat } from "./team_chat";
import { Pipeline } from "./pipeline";
import { TeamStatus } from "./team_status";

const API = "http://127.0.0.1:8001";

function ok(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
}

function fail(data: unknown, status = 400) {
  return Promise.resolve({ ok: false, status, json: () => Promise.resolve(data) });
}

type Route = (url: string, opts?: any) => any;

function makeFetch(overrides: Record<string, Route> = {}) {
  const fn = vi.fn((url: string, opts?: any) => {
    if (url.endsWith("/health")) return ok({ ok: true });
    if (overrides[url]) return overrides[url](url, opts);
    if (url.endsWith("/agents/model-health"))
      return ok({ backend: { ok: true }, model: { code: "ok", provider: "ollama" } });
    // default: empty lists
    return ok({ items: [] });
  });
  return fn;
}

// Drive the Work view into the "Acme" workspace / "Launch" project used by
// the fixtures below, waiting for the async workspace/project data to arrive.
async function openWorkProject() {
  // The proposals & project work now live under the Projects tab's "Proposals"
  // sub-view (Workspaces and Work were merged into Projects).
  fireEvent.click(screen.getByRole("button", { name: "Projects" }));
  fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
  // Scope these to the view's workspace/project selectors so the deterministic
  // "New proposal" composer (which also lists parents) does not create ambiguity.
  const wsSelect = await screen.findByLabelText("Workspace");
  await within(wsSelect).findByRole("option", { name: "Acme" });
  fireEvent.change(wsSelect, { target: { value: "w1" } });
  const prSelect = screen.getByLabelText("Project");
  await within(prSelect).findByRole("option", { name: "Launch" });
  fireEvent.change(prSelect, { target: { value: "p1" } });
}

beforeEach(() => {
  vi.restoreAllMocks();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App shell and navigation", () => {
  it("renders title and all navigation tabs", async () => {
    globalThis.fetch = makeFetch() as any;
    render(<App />);
    expect(screen.getByRole("heading", { name: "Personal AI Team" })).toBeInTheDocument();
    const tabs: [string, string][] = [
      ["home", "Home"],
      ["projects", "Projects"],
      ["tasks", "Task Center"],
      ["settings", "Settings"],
    ];
    for (const [route, label] of tabs) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: label }).dataset.route).toBe(route);
    }
  });
});

;

;

;

describe("D4.3 read-only tool wiring", () => {
  it.skip("runs the calculate tool and surfaces the result", async () => {
    const fn = makeFetch({
      [`${API}/agents`]: () => ok({ agents: [{ name: "strategist", display_name: "Aisha", archetype: "Strategist" }] }),
      [`${API}/agents/strategist/run`]: (url: string, opts?: any) => {
        const body = JSON.parse(opts.body);
        return ok({
          agent: "strategist", reply: "Here is the result:", facts: [], proposals: [],
          tool_results: [{ tool: "calculate", ok: true, result: 391 }],
          thread_id: "t-1", context_messages: 1, sent: body,
        });
      },
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Aisha"));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "17*23" } });
    fireEvent.click(screen.getByTestId("run-calculate"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0] === `${API}/agents/strategist/run`);
      expect(call).toBeTruthy();
      const body = JSON.parse(call[1].body);
      expect(body.tool_calls).toEqual([
        { tool: "calculate", args: { expression: "17*23" }, approved: true },
      ]);
    });
    const chip = await screen.findByTestId("tool-result-0");
    expect(chip.textContent).toContain("calculate");
    expect(chip.textContent).toContain("391");
  });
});

describe("D4.3-B coordinated status", () => {
  it("shows awaiting-approval, in-progress, and team workload", async () => {
    const fn = makeFetch({
      [`${API}/agents`]: () => ok({ agents: [
        { name: "strategist", display_name: "Aisha", archetype: "Strategist" },
        { name: "communications", display_name: "Brandon", archetype: "Communications" },
      ] }),
      [`${API}/work/feed`]: () => ok({ items: [
        { id: "p1", work_type: "goal", action: "create", status: "proposed", proposed_change: "create goal", decision: null },
      ] }),
      [`${API}/episodes`]: () => ok({ items: [
        { id: "e1", status: "running", title: "Onboarding" },
        { id: "e2", status: "done", title: "Done one" },
      ] }),
      [`${API}/workspaces/assignments`]: () => ok({ items: [
        { id: "a1", agent_id: "communications", goal_id: "g1" },
        { id: "a2", agent_id: "communications", goal_id: "g1" },
        { id: "a3", agent_id: "strategist", goal_id: "g1" },
      ] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    const panel = await screen.findByTestId("coord-status");
    expect(panel).toBeInTheDocument();
    expect(screen.getByTestId("coord-pending").textContent).toBe("1");
    expect(screen.getByTestId("coord-running").textContent).toBe("1");
    expect(screen.getByTestId("coord-done").textContent).toBe("1");
    // Team workload groups assignments by owner.
    expect(screen.getByTestId("coord-owner-communications").textContent).toContain("Brandon");
    expect(screen.getByTestId("coord-owner-strategist").textContent).toContain("Aisha");
  });
});

;

;

;

;

describe.skip("Graceful generation failure handling (M10 D4.2)", () => {
  const agentFixture = () => ({
    [`${API}/agents`]: () =>
      ok({
        agents: [{ name: "tutor", role: "Personal tutor", capabilities: ["explain"] }],
      }),
  });

  async function selectTutor() {
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
  }

  it("shows a model-offline banner separate from backend offline", async () => {
    globalThis.fetch = makeFetch({
      ...agentFixture(),
      [`${API}/agents/model-health`]: () =>
        ok({ backend: { ok: true }, model: { code: "model_unavailable", provider: "ollama" } }),
    }) as any;
    render(<App />);
    await selectTutor();
    expect(await screen.findByTestId("model-offline-banner")).toBeInTheDocument();
  });

  it("shows a friendly failure panel with a Retry and no raw detail", async () => {
    globalThis.fetch = makeFetch({
      ...agentFixture(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "I couldn't reach the language model just now.",
          location: "local:ollama:llama3.1",
          thread_id: "th1",
          facts: [],
          proposals: [],
          tool_results: [],
          generation_error: { code: "model_unavailable", retryable: true },
        }),
    }) as any;
    render(<App />);
    await selectTutor();
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "help me plan" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    expect(await screen.findByTestId("gen-failure-panel")).toBeInTheDocument();
    expect(screen.getByTestId("retry-agent")).toBeInTheDocument();
    // no raw backend detail is surfaced
    expect(screen.queryByText(/Error:/)).not.toBeInTheDocument();
  });

  it("Retry resubmits the same task and thread with retry:true", async () => {
    const fn = makeFetch({
      ...agentFixture(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "still down",
          location: "local:ollama:llama3.1",
          thread_id: "th1",
          facts: [],
          proposals: [],
          tool_results: [],
          generation_error: { code: "model_unavailable", retryable: true },
        }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    await selectTutor();
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "plan my week" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    await screen.findByTestId("gen-failure-panel");
    fireEvent.click(screen.getByTestId("retry-agent"));
    await waitFor(() => {
      const calls = fn.mock.calls.filter((c: any) => c[0] === `${API}/agents/tutor/run`);
      expect(calls.length).toBeGreaterThanOrEqual(2);
      const retry = calls[calls.length - 1];
      const body = JSON.parse(retry[1].body);
      expect(body.task).toBe("plan my week");
      expect(body.thread_id).toBe("th1");
      expect(body.retry).toBe(true);
    });
  });

  it("surfaces a history-warning instead of hiding it", async () => {
    globalThis.fetch = makeFetch({
      ...agentFixture(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "done",
          location: "local:ollama:llama3.1",
          facts: [],
          proposals: [],
          tool_results: [],
          history_warning: "reply generated but history failed to save (OperationalError)",
        }),
    }) as any;
    render(<App />);
    await selectTutor();
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    expect(
      await screen.findByText(/reply generated but history failed to save/)
    ).toBeInTheDocument();
  });

  it("surfaces a useful summary of partial tool results", async () => {
    globalThis.fetch = makeFetch({
      ...agentFixture(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "partly done",
          location: "local:ollama:llama3.1",
          facts: [],
          proposals: [],
          tool_results: [
            { tool: "now", ok: true },
            { tool: "calculate", ok: false, error: "division by zero" },
          ],
        }),
    }) as any;
    render(<App />);
    await selectTutor();
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "compute" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    await screen.findByText("Tools used");
    expect(screen.getByText(/calculate: error: division by zero/)).toBeInTheDocument();
    expect(screen.getByText(/now: ok/)).toBeInTheDocument();
  });

  it("does not expose raw backend detail on a 5xx (L3)", async () => {
    globalThis.fetch = makeFetch({
      ...agentFixture(),
      [`${API}/agents/tutor/run`]: () =>
        fail({ detail: "Traceback (most recent call last): boom" }, 500),
    }) as any;
    render(<App />);
    await selectTutor();
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "help" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    // generic friendly message shown; raw exception text never rendered
    expect(
      await screen.findByText(/couldn\u2019t complete the request right now/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
    expect(screen.queryByText(/boom/)).not.toBeInTheDocument();
  });

  it("clears a stale failure panel when switching agents (L2)", async () => {
    const twoAgents = () => ({
      [`${API}/agents`]: () =>
        ok({
          agents: [
            { name: "tutor", role: "Personal tutor", capabilities: ["explain"] },
            { name: "strategist", role: "Strategist", capabilities: ["plan"] },
          ],
        }),
    });
    globalThis.fetch = makeFetch({
      ...twoAgents(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "down",
          location: "local:ollama:llama3.1",
          thread_id: "th1",
          facts: [],
          proposals: [],
          tool_results: [],
          generation_error: { code: "model_unavailable", retryable: true },
        }),
    }) as any;
    render(<App />);
    await selectTutor();
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    expect(await screen.findByTestId("gen-failure-panel")).toBeInTheDocument();
    // switch to another agent -> prior failure panel is cleared
    fireEvent.click(screen.getByRole("button", { name: "strategist" }));
    expect(screen.queryByTestId("gen-failure-panel")).not.toBeInTheDocument();
  });
});

describe("Phase 4 — Task Center, Settings, conversation-to-task", () => {
  it("renders tasks loaded from /tasks in the Task Center", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/tasks`]: () =>
        ok({ items: [
          { task_id: "t1", kind: "assignment", status: "awaiting_execution", title: "Write launch plan", description: "A short plan", agent_id: "strategist", goal_id: "g1", goal_title: "Launch", project_name: "Launch", workspace_name: "Work", next_action: "Approved. Start execution when ready.", deliverable: null, deliverables: [], thread_ids: [], needs_approval: false },
        ] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Task Center" }));
    expect(await screen.findByText("Write launch plan")).toBeInTheDocument();
    expect(screen.getByText(/Start execution when ready/)).toBeInTheDocument();
    // status label is human-readable (badge + status filter option both match)
    expect(screen.getAllByText("Awaiting execution").length).toBeGreaterThan(0);
  });

  it("links from the Task Center to coordination (AI tab)", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/tasks`]: () => ok({ items: [] }),
      [`${API}/team/goals`]: () => ok({ items: [] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Task Center" }));
    const link = await screen.findByTestId("open-coordination");
    expect(link.textContent).toContain("Open structured projects");
    fireEvent.click(link);
    expect(await screen.findByTestId("structured-projects")).toBeInTheDocument();
  });

  it("opens the originating conversation from a task in the Task Center", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/tasks`]: () =>
        ok({ items: [
          { task_id: "t9", kind: "assignment", status: "awaiting_execution", title: "Draft launch copy", agent_id: "communications", goal_id: "g1", goal_title: "Launch", project_name: "Launch", next_action: "Approved.", deliverable: null, deliverables: [], thread_ids: ["thr-abc"], needs_approval: false },
        ] }),
      [`${API}/team/threads`]: () => ok({ thread_id: "fresh" }),
      [`${API}/memory/conversations`]: () => ok({ items: [] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Task Center" }));
    const btn = await screen.findByTestId("task-open-chat-t9");
    expect(btn.textContent).toContain("Open in chat");
    fireEvent.click(btn);
    expect(localStorage.getItem("ai-team-shared-thread")).toBe("thr-abc");
    // navigates back to Home (the group chat)
    expect(await screen.findByTestId("team-chat-list")).toBeInTheDocument();
    localStorage.removeItem("ai-team-shared-thread");
  });

  it("filters tasks by status in the Task Center", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/tasks`]: () =>
        ok({ items: [
          { task_id: "t1", status: "awaiting_execution", title: "Task A", agent_id: "tutor" },
          { task_id: "t2", status: "in_progress", title: "Task B", agent_id: "tutor" },
        ] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Task Center" }));
    expect(await screen.findByText("Task A")).toBeInTheDocument();
    expect(screen.getByText("Task B")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Task status filter"), { target: { value: "in_progress" } });
    expect(screen.queryByText("Task A")).not.toBeInTheDocument();
    expect(screen.getByText("Task B")).toBeInTheDocument();
  });

  it("renders Settings with sample-data and preferences sections", async () => {
    globalThis.fetch = makeFetch() as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByText("Sample & test data", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText("Preferences", { selector: "h3" })).toBeInTheDocument();
  });

  it.skip("opens the conversation-to-task panel from a conversation (AI Team)", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/memory/conversations`]: () =>
        ok({ items: [
          { thread_id: "thr-x", agent_id: "strategist", title: "Strategy talk", is_renamed: false, last_activity: "2026-11-02T00:00:00Z", message_count: 3 },
        ] }),
      [`${API}/memory/conversation?thread_id=thr-x`]: () =>
        ok({ items: [ { role: "user", content: "help me", created_at: "now" } ] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    // open the conversation, then click "→ Task" on it
    fireEvent.click(await screen.findByText("Strategy talk"));
    fireEvent.click(screen.getByText("→ Task"));
    expect(await screen.findByTestId("conv-to-task")).toBeInTheDocument();
  });
});

;

;

;

describe.skip("Conversation draft extraction (component)", () => {
  function aiFixture() {
    return {
      [`${API}/agents`]: () => ok({ agents: [{ name: "strategist", display_name: "Aisha", archetype: "The Visionary" }] }),
    };
  }

  it("extracts an assignment draft and does not auto-propose", async () => {
    const fn = makeFetch({
      ...aiFixture(),
      [`${API}/work/extract`]: (url: string, opts?: any) => {
        const b = JSON.parse(opts.body);
        return ok({ kind: b.kind, draft: { kind: b.kind, title: "Research the market", subject_agent: "strategist", expected_output: "a brief", priority: "high" }, persisted: false });
      },
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "strategist" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "assign: Research the market\nto: strategist" } });
    fireEvent.click(screen.getByTestId("extract-assignment"));
    await screen.findByTestId("extract-panel");
    expect(screen.getByTestId("extract-title").value).toBe("Research the market");
    expect(screen.getByTestId("extract-agent").value).toBe("strategist");
    // Draft only: no proposal is created on extraction.
    expect(fn.mock.calls.some((c: any) => typeof c[0] === "string" && c[0].includes("/work/proposals"))).toBe(false);
  });

  it("proposing a deliverable draft without project context surfaces an error", async () => {
    const fn = makeFetch({
      ...aiFixture(),
      [`${API}/work/extract`]: () => ok({ kind: "deliverable", draft: { kind: "deliverable", title: "Launch deck", format: "pdf" }, persisted: false }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "strategist" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "deliverable: Launch deck" } });
    fireEvent.click(screen.getByTestId("extract-deliverable"));
    await screen.findByTestId("extract-panel");
    expect(screen.getByTestId("extract-title").value).toBe("Launch deck");
    fireEvent.click(screen.getByTestId("extract-propose"));
    await screen.findByTestId("extract-error");
    expect(screen.getByTestId("extract-error").textContent).toMatch(/Pick a project/);
  });

  it("extract API error is surfaced without proposing", async () => {
    const fn = makeFetch({
      ...aiFixture(),
      [`${API}/work/extract`]: () => fail({ detail: "unknown agent: bogus" }, 400),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "strategist" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "assign to bogus" } });
    fireEvent.click(screen.getByTestId("extract-assignment"));
    await screen.findByTestId("extract-error");
    expect(screen.getByTestId("extract-error").textContent).toMatch(/unknown agent/);
    expect(screen.queryByTestId("extract-panel")).toBeNull();
  });
});

describe("Team Chat (component)", () => {
  function chatBackend() {
    return vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/team/messages")) {
        return ok({ message: "hi team", routed_to: ["strategist"], coordinated_team_response: false, responses: [{ agent: "strategist", reply: "Here's a plan for the launch." }], errors: [] });
      }
      return ok({ items: [] });
    });
  }

  it("shows an empty state on a fresh shared thread", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    globalThis.fetch = chatBackend() as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-empty");
  });

  it("links the current thread to the Task Center when it produced work", async () => {
    localStorage.setItem("ai-team-shared-thread", "team-1");
    const fn = vi.fn(async (url: string) => {
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.includes("/work/links?")) return ok({ items: [{ id: "w1" }, { id: "w2" }] });
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    let opened = 0;
    render(<TeamChat onOpenTasks={() => { opened += 1; }} />);
    const btn = await screen.findByTestId("chat-open-tasks");
    expect(btn.textContent).toContain("2");
    fireEvent.click(btn);
    expect(opened).toBe(1);
    localStorage.removeItem("ai-team-shared-thread");
  });

  it("hides the Task Center link on a thread with no produced work", async () => {
    localStorage.setItem("ai-team-shared-thread", "team-empty");
    globalThis.fetch = chatBackend() as any; // /work/links returns empty items
    render(<TeamChat onOpenTasks={() => { /* noop */ }} />);
    await screen.findByTestId("team-chat-input");
    expect(screen.queryByTestId("chat-open-tasks")).toBeNull();
    localStorage.removeItem("ai-team-shared-thread");
  });

  it("sends to the team and renders per-agent bubbles", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    const fn = chatBackend();
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-input");
    fireEvent.change(screen.getByTestId("team-chat-input"), { target: { value: "Research the launch market" } });
    fireEvent.click(screen.getByTestId("team-chat-send"));
    await screen.findByText(/Here's a plan for the launch/);
    const call = fn.mock.calls.find((c: any) => c[0].endsWith("/team/messages"));
    expect(call).toBeTruthy();
    expect(JSON.parse(call![1].body).message).toContain("Research the launch market");
  });

  it("lists conversations in the sidebar and lets you switch threads", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    const fn = vi.fn(async (url: string) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversations")) return ok({ items: [{ thread_id: "t-other", title: "Launch ideas", agent_id: "strategist" }] });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.includes("/team/progress?")) return ok({ items: [] });
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("conv-t-other");
    fireEvent.click(screen.getByTestId("conv-t-other"));
    await waitFor(() => {
      expect(fn.mock.calls.find((c: any) => c[0] && c[0].includes("/memory/conversation?thread_id=t-other"))).toBeTruthy();
    });
  });

  it("shows the team progress feed for the thread", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    globalThis.fetch = vi.fn(async (url: string) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/team/progress?")) return ok({ items: [{ id: "p1", agent_id: "strategist", status: "completed", detail: "plan ready" }] });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      return ok({ items: [] });
    });
    render(<TeamChat />);
    await screen.findByTestId("team-progress");
    expect(screen.getByText(/plan ready/)).toBeInTheDocument();
  });

  it("delegates a message into a structured plan (approve/authorize/run stay separate)", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    const fn = vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/projects") && init?.method === "POST") {
        return ok({ id: "prj-1", status: "awaiting_plan_approval" });
      }
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-input");
    fireEvent.click(screen.getByTestId("mode-delegate"));
    fireEvent.change(screen.getByTestId("team-chat-input"), { target: { value: "goal: Launch the On Us platform in the Bay Area" } });
    fireEvent.click(screen.getByTestId("team-chat-delegate"));
    const msg = await screen.findByTestId("delegate-msg");
    expect(msg.textContent).toContain("Structured plan created");
    // Intent only: delegation must NOT approve, authorize a plan, or run.
    const urls = fn.mock.calls.map((c: any) => c[0] || "");
    expect(urls.some((u: string) => u.includes("/approve"))).toBe(false);
    expect(urls.some((u: string) => u.includes("/coordination-plan/authorize"))).toBe(false);
    expect(urls.some((u: string) => u.endsWith("/run"))).toBe(false);
  });

  it("routes Enter in Delegate mode through the structured planner, not the chat", async () => {
    // Regression: pressing Enter in "Delegate to the team" must call POST /projects
    // (which feeds the structured approval flow) and never fall through to the
    // conversational /team/messages path.
    localStorage.removeItem("ai-team-shared-thread");
    const fn = vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/projects") && init?.method === "POST") {
        return ok({ id: "prj-x", status: "awaiting_plan_approval" });
      }
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-input");
    fireEvent.click(screen.getByTestId("mode-delegate"));
    fireEvent.change(screen.getByTestId("team-chat-input"), { target: { value: "goal: Launch the On Us platform in the Bay Area" } });
    fireEvent.keyDown(screen.getByTestId("team-chat-input"), { key: "Enter" });
    const msg = await screen.findByTestId("delegate-msg");
    expect(msg.textContent).toContain("Structured plan created");
    await waitFor(() => {
      const urls = fn.mock.calls.map((c: any) => c[0] || "");
      expect(urls.some((u: string) => u.endsWith("/projects"))).toBe(true);
      expect(urls.some((u: string) => u.includes("/team/messages"))).toBe(false);
    });
  });

  it("shows an explicit failure on structured planning error instead of falling back to TeamGoals", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    const fn = vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/projects") && init?.method === "POST") {
        // no .id -> treated as a planning failure; must NOT fall back to TeamGoal.
        return ok({ detail: "structured planner returned HTTP 502" });
      }
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-input");
    fireEvent.click(screen.getByTestId("mode-delegate"));
    fireEvent.change(screen.getByTestId("team-chat-input"), { target: { value: "goal: Draft a strategy" } });
    fireEvent.click(screen.getByTestId("team-chat-delegate"));
    const msg = await screen.findByTestId("delegate-msg");
    expect(msg.textContent).toContain("Could not delegate");
    expect(msg.textContent).toContain("No plan was saved");
    const urls = fn.mock.calls.map((c: any) => c[0] || "");
    // The silent legacy fallback must not fire.
    expect(urls.some((u: string) => u.includes("/team/goals/draft"))).toBe(false);
  });

});

describe("Pipeline (component)", () => {
  it("renders the ladder and highlights the approval stage for a pending proposal", async () => {
    globalThis.fetch = vi.fn(async (url: string) => {
      if (url.endsWith("/work/proposals")) return ok({ items: [{ id: "p1", title: "Launch app", work_type: "project", status: "proposed" }] });
      return ok({ items: [] });
    });
    render(<Pipeline />);
    await screen.findByTestId("pipeline-stages");
    expect(screen.getByTestId("pipeline-chat")).toBeInTheDocument();
    expect(screen.getByTestId("pipeline-approval")).toHaveClass("pipeline__stage--now");
    expect(screen.getByTestId("pipeline-created")).toHaveClass("pipeline__stage--upcoming");
  });

  it("shows created work as done and routes to Task Center after approval", async () => {
    let jumped: string | undefined;
    globalThis.fetch = vi.fn(async (url: string) => {
      if (url.endsWith("/work/proposals")) return ok({ items: [{ id: "p1", title: "Launch app", work_type: "goal", status: "approved" }] });
      return ok({ items: [] });
    });
    render(<Pipeline onJump={(t) => { jumped = t; }} />);
    await screen.findByTestId("pipeline-stages");
    expect(screen.getByTestId("pipeline-approval")).toHaveClass("pipeline__stage--done");
    fireEvent.click(screen.getByTestId("pipeline-goto-tasks"));
    expect(jumped).toBe("tasks");
  });

  it("renders the coordination (team goal) ladder and jumps to Coordination when a plan awaits authorization", async () => {
    let jumped: string | undefined;
    globalThis.fetch = vi.fn(async (url: string) => {
      if (url.endsWith("/team/goals"))
        return ok({ items: [{ id: "g1", title: "Launch On Us", status: "approved", plan_authorized: false, has_execution: false, deliverable_accepted: false, materialized: false }] });
      return ok({ items: [] });
    });
    render(<Pipeline onJump={(t) => { jumped = t; }} />);
    fireEvent.click(screen.getByTestId("pipeline-mode-goals"));
    await screen.findByTestId("pipeline-goal-stages");
    // Approved goal, plan not yet authorized => next action is the plan stage.
    expect(screen.getByTestId("pipeline-goal-approved")).toHaveClass("pipeline__stage--done");
    expect(screen.getByTestId("pipeline-goal-plan")).toHaveClass("pipeline__stage--now");
    expect(screen.getByTestId("pipeline-goal-projects")).toHaveClass("pipeline__stage--upcoming");
    fireEvent.click(screen.getByTestId("pipeline-goto-coord-plan"));
    expect(jumped).toBe("home");
  });

  it("marks the coordination ladder through materialization and routes to Projects", async () => {
    let jumped: string | undefined;
    globalThis.fetch = vi.fn(async (url: string) => {
      if (url.endsWith("/team/goals"))
        return ok({ items: [{ id: "g2", title: "Launch On Us", status: "approved", plan_authorized: true, has_execution: true, deliverable_accepted: true, materialized: true }] });
      return ok({ items: [] });
    });
    render(<Pipeline onJump={(t) => { jumped = t; }} />);
    fireEvent.click(screen.getByTestId("pipeline-mode-goals"));
    await screen.findByTestId("pipeline-goal-stages");
    expect(screen.getByTestId("pipeline-goal-execute")).toHaveClass("pipeline__stage--done");
    expect(screen.getByTestId("pipeline-goal-deliverable")).toHaveClass("pipeline__stage--done");
    expect(screen.getByTestId("pipeline-goal-projects")).toHaveClass("pipeline__stage--done");
    fireEvent.click(screen.getByTestId("pipeline-goto-goal-projects"));
    expect(jumped).toBe("projects");
  });
});

describe("TeamStatus (component)", () => {
  function backend(progress: any[], blocked: any[]) {
    return vi.fn(async (url: string) => {
      if (url.includes("/team/progress")) return ok({ items: progress });
      if (url.includes("/team/comm/blocked")) return ok({ items: blocked });
      return ok({ items: [] });
    });
  }

  it("renders latest agent states, recent activity, and blocked coordination", async () => {
    globalThis.fetch = backend(
      [
        { id: "p1", agent_id: "strategist", status: "completed", detail: "plan ready" },
        { id: "p2", agent_id: "tutor", status: "completed", detail: "explained the market" },
        { id: "p3", agent_id: "soundboard", status: "working", detail: "reflecting on ideas" },
      ],
      [
        { id: "c1", from_agent: "workspace_architect", to_agent: "communications", content: "depth limit reached" },
      ]
    ) as any;
    render(<TeamStatus />);
    await screen.findByTestId("team-status");
    // agent state chips reflect the latest status per agent
    expect(screen.getByTestId("team-status-agent-strategist")).toHaveTextContent("completed");
    expect(screen.getByTestId("team-status-agent-soundboard")).toHaveTextContent("working");
    // recent activity entries
    expect(screen.getByTestId("team-status-progress-0")).toHaveTextContent("plan ready");
    // blocked coordination surfaced to the human
    expect(screen.getByTestId("team-status-blocked-0"))
      .toHaveTextContent(/Workspace Architect → Communications/);
  });

  it("shows empty and offline states", async () => {
    globalThis.fetch = backend([], []) as any;
    render(<TeamStatus />);
    await screen.findByTestId("team-status");
    expect(screen.getByTestId("team-status-agents-empty")).toBeInTheDocument();
    expect(screen.getByTestId("team-status-progress-empty")).toBeInTheDocument();
    expect(screen.getByTestId("team-status-blocked-empty")).toBeInTheDocument();

    globalThis.fetch = vi.fn(() => Promise.reject(new Error("offline"))) as any;
    render(<TeamStatus />);
    expect(await screen.findByText("Could not load team status.")).toBeInTheDocument();
  });
});

describe("Team Memory (component)", () => {
  function memoryBackend(initial: any, onMutate?: (kind: string) => void) {
    let state = { ...initial };
    const fn = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      if (url.endsWith("/memory/profile"))
        return ok({ items: state.profile });
      if (url.includes("/memory/proposals?") && method === "GET")
        return ok({ proposals: state.proposals });
      if (method === "POST" && url.includes("/memory/proposals/") && url.includes("/approve")) {
        if (onMutate) onMutate("approve");
        return ok({ ok: true });
      }
      if (method === "POST" && url.includes("/memory/proposals/") && url.includes("/reject")) {
        if (onMutate) onMutate("reject");
        return ok({ ok: true });
      }
      if (method === "POST" && url.includes("/memory/revoke/")) {
        if (onMutate) onMutate("revoke");
        return ok({ ok: true });
      }
      if (method === "POST" && url.endsWith("/memory/proposals")) {
        if (onMutate) onMutate("propose");
        return ok({ ok: true, proposal_id: "np1" });
      }
      return ok({ items: [], proposals: [] });
    });
    return fn;
  }

  it("lists approved memories and pending proposals", async () => {
    globalThis.fetch = memoryBackend({
      profile: [{ id: "m1", key: "Launch window", value: "prefer spring", created_at: "2026-01-01T00:00:00Z" }],
      proposals: [{ id: "p1", key: "Use Figma", value: "Design tool", agent_id: "strategist", confidence: 0.8 }],
    }) as any;
    render(<TeamMemory />);
    await screen.findByTestId("tm-memory-m1");
    expect(screen.getByText("Launch window")).toBeInTheDocument();
    expect(screen.findByTestId("tm-proposal-p1")).toBeTruthy();
    expect(screen.getByTestId("tm-approve-p1")).toBeInTheDocument();
    expect(screen.getByTestId("tm-reject-p1")).toBeInTheDocument();
    expect(screen.getByTestId("tm-revoke-m1")).toBeInTheDocument();
  });

  it("approving a proposal calls the human-only endpoint", async () => {
    const fn = memoryBackend({
      profile: [],
      proposals: [{ id: "p1", key: "Use Figma", value: "Design tool", agent_id: "strategist" }],
    });
    globalThis.fetch = fn as any;
    render(<TeamMemory />);
    await screen.findByTestId("tm-approve-p1");
    fireEvent.click(screen.getByTestId("tm-approve-p1"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0].includes("/memory/proposals/p1/approve"));
      expect(call).toBeTruthy();
      expect(call![1].method).toBe("POST");
    });
  });

  it("rejecting a proposal calls the endpoint and a post-mutation reload occurs", async () => {
    const fn = memoryBackend(
      { profile: [], proposals: [{ id: "p1", key: "Use Figma", value: "Design tool" }] },
      () => { /* reload re-reads state */ }
    );
    globalThis.fetch = fn as any;
    render(<TeamMemory />);
    await screen.findByTestId("tm-reject-p1");
    fireEvent.click(screen.getByTestId("tm-reject-p1"));
    await waitFor(() => {
      expect(fn.mock.calls.find((c: any) => c[0].includes("/memory/proposals/p1/reject"))).toBeTruthy();
    });
  });

  it("proposes a durable memory after human input", async () => {
    const fn = memoryBackend({ profile: [], proposals: [] });
    globalThis.fetch = fn as any;
    render(<TeamMemory />);
    await screen.findByTestId("tm-propose");
    fireEvent.change(screen.getByTestId("tm-title"), { target: { value: "Prefers async" } });
    fireEvent.change(screen.getByTestId("tm-value"), { target: { value: "No sync standups" } });
    fireEvent.click(screen.getByTestId("tm-propose-btn"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0].endsWith("/memory/proposals") && c[1]?.method === "POST");
      expect(call).toBeTruthy();
      const body = JSON.parse(call![1].body);
      expect(body.key).toBe("Prefers async");
      expect(body.value).toBe("No sync standups");
    });
    expect(await screen.findByTestId("tm-note")).toBeInTheDocument();
    expect(screen.getByTestId("tm-note").textContent).toMatch(/must approve/);
  });
});

describe("Task Center delete", () => {
  it("deletes a task via DELETE, refreshes, and removes it from the list", async () => {
    const deleteCalls: string[] = [];
    const taskRoute = (url: string, opts?: any) => {
      if (opts?.method === "DELETE") {
        deleteCalls.push(url);
        return ok({ ok: true });
      }
      // keep showing the item until a delete happens; then the reload is empty,
      // proving the Task Center refresh removes it after the DELETE succeeds.
      if (deleteCalls.length > 0) return ok({ items: [] });
      return ok({
        items: [{
          task_id: "a1", kind: "assignment", status: "awaiting_execution",
          title: "Research market", agent_id: "strategist",
          project_name: "Launch", goal_title: "Win SF Bay Area",
          next_action: "Approved. Start execution when ready.",
        }],
      });
    };
    globalThis.fetch = makeFetch({
      [`${API}/tasks`]: taskRoute,
      [`${API}/tasks/a1`]: (url: string, opts?: any) => {
        deleteCalls.push(url);
        return ok({ ok: true });
      },
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Task Center" }));
    expect(await screen.findByText("Research market")).toBeInTheDocument();
    const del = screen.getByTestId("delete-task-a1");
    expect(del).toBeInTheDocument();
    fireEvent.click(del);
    await waitFor(() => expect(deleteCalls.length).toBeGreaterThan(0));
    expect(deleteCalls[0]).toBe(`${API}/tasks/a1`);
    // refresh after delete reloads the (now empty) task list
    expect(await screen.findByText(/No tasks yet/)).toBeInTheDocument();
  });
});
