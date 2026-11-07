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

describe("Workspaces", () => {
  it("creates a workspace via POST with the entered name", async () => {
    const fn = makeFetch();
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));

    const input = screen.getByPlaceholderText("Workspace name");
    fireEvent.change(input, { target: { value: "Acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Acme" }) })
      );
    });
  });

  it("renders workspace list from the API", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(await screen.findByText("Acme")).toBeInTheDocument();
  });

  it("disables create when offline", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("offline"))) as any;
    render(<App />);
    await screen.findByText(/read-only/);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  });
});

describe("Projects", () => {
  it("renders projects with status within a selected workspace", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", status: "active", workspace_id: "w1" }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    // Open the workspace from the workspace LIST (the recent-projects overview also mentions Acme).
    fireEvent.click((await screen.findAllByText("Acme"))[1]);
    expect(await screen.findByText(/Launch/)).toBeInTheDocument();
    expect(screen.getByText(/Active/)).toBeInTheDocument();
  });

  it("creates a project against the selected workspace", async () => {
    const fn = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(await screen.findByText("Acme"));
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces/projects`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ workspace_id: "w1", name: "New Project" }) })
      );
    });
  });
});

describe("Overview", () => {
  it("renders dashboard stats and recent projects", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () =>
        ok({ items: [{ id: "p1", name: "Launch", status: "active", workspace_id: "w1", created_at: "2026-01-01T00:00:00Z" }] }),
    }) as any;
    render(<App />);
    expect(await screen.findByText(/your AI team's command center/i)).toBeInTheDocument();
    // Home is the team/command center: Recent projects & Open goals moved to Projects.
    expect(screen.queryByText("Recent projects")).not.toBeInTheDocument();
    expect(screen.queryByText("Open goals")).not.toBeInTheDocument();
  });
});

describe("Project Detail", () => {
  it("reveals goals, assignments, and deliverables for a selected project", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", status: "active", workspace_id: "w1" }] }),
      [`${API}/workspaces/goals`]: () => ok({ items: [{ id: "g1", title: "Ship v1", project_id: "p1", status: "open", priority: 1 }] }),
      [`${API}/workspaces/assignments`]: () => ok({ items: [{ id: "a1", goal_id: "g1", agent_id: "tutor", status: "queued", priority: 1 }] }),
      [`${API}/workspaces/deliverables`]: () => ok({ items: [{ id: "d1", title: "Report", project_id: "p1" }] }),
      [`${API}/agents`]: () => ok({ agents: [{ name: "tutor", display_name: "Brittany", archetype: "The Educator" }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    // Open the workspace from the workspace LIST (the overview also mentions Acme).
    fireEvent.click((await screen.findAllByText("Acme"))[1]);
    fireEvent.click(await screen.findByText("Launch"));

    expect((await screen.findAllByText("Ship v1")).length).toBeGreaterThan(0);
    expect(screen.getByText("Brittany")).toBeInTheDocument();
    expect(screen.getByText("Report")).toBeInTheDocument();
  });
});

describe("Work view — Goals", () => {
  const goalsFixtures = () => ({
    [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    [`${API}/workspaces/projects`]: () =>
      ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
    [`${API}/workspaces/goals`]: () =>
      ok({
        items: [
          { id: "g1", title: "Ship v1", project_id: "p1", status: "open", priority: 1 },
          { id: "g2", title: "Ship v2", project_id: "p1", status: "done", priority: 2 },
        ],
      }),
  });

  it("renders goals scoped to the selected project with their status", async () => {
    globalThis.fetch = makeFetch(goalsFixtures()) as any;
    render(<App />);
    await openWorkProject();

    expect(await screen.findByText(/Ship v1/)).toBeInTheDocument();
    expect(screen.getAllByText("Done").length).toBeGreaterThanOrEqual(1);
  });

  it("shows a select-project empty state before a project is chosen", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    expect(await screen.findByText(/Select a workspace and project/)).toBeInTheDocument();
  });

  it("filters goals by status and text search", async () => {
    globalThis.fetch = makeFetch(goalsFixtures()) as any;
    render(<App />);
    await openWorkProject();
    await screen.findByText(/Ship v1/);

    fireEvent.change(screen.getByPlaceholderText("Search goals…"), { target: { value: "v2" } });
    expect(screen.queryByText(/Ship v1/)).not.toBeInTheDocument();
    expect(screen.getByText(/Ship v2/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search goals…"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Goal status filter"), { target: { value: "done" } });
    expect(screen.queryByText(/Ship v1/)).not.toBeInTheDocument();
    expect(screen.getByText(/Ship v2/)).toBeInTheDocument();
  });

  it("creates a goal against the selected project", async () => {
    const fn = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () =>
        ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    const btn = await screen.findByRole("button", { name: "Create Goal" });
    expect(btn).toBeEnabled();
    fireEvent.click(btn);

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces/goals`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ project_id: "p1", title: "New Goal", priority: 1 }) })
      );
    });
  });
});

describe("Work view — Assignments", () => {
  const assignmentFixtures = () => ({
    [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    [`${API}/workspaces/projects`]: () =>
      ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
    [`${API}/workspaces/goals`]: () =>
      ok({ items: [{ id: "g1", title: "Ship v1", project_id: "p1", status: "open", priority: 1 }] }),
    [`${API}/workspaces/assignments`]: () =>
      ok({ items: [{ id: "a1", goal_id: "g1", agent_id: "tutor", status: "queued", priority: 2 }] }),
    [`${API}/agents`]: () =>
      ok({ agents: [{ name: "tutor", display_name: "Brittany", archetype: "The Educator" }] }),
  });

  it("renders assignments with agent name, archetype, and linked goal", async () => {
    globalThis.fetch = makeFetch(assignmentFixtures()) as any;
    render(<App />);
    await openWorkProject();

    expect(await screen.findByText("The Educator")).toBeInTheDocument();
    expect(screen.getAllByText("Brittany").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Ship v1").length).toBeGreaterThanOrEqual(1);
  });

  it("filters assignments by agent", async () => {
    globalThis.fetch = makeFetch({
      ...assignmentFixtures(),
      [`${API}/workspaces/assignments`]: () =>
        ok({
          items: [
            { id: "a1", goal_id: "g1", agent_id: "tutor", status: "queued", priority: 1 },
            { id: "a2", goal_id: "g1", agent_id: "strategist", status: "queued", priority: 2 },
          ],
        }),
      [`${API}/agents`]: () =>
        ok({
          agents: [
            { name: "tutor", display_name: "Brittany", archetype: "The Educator" },
            { name: "strategist", display_name: "Aisha", archetype: "The Visionary" },
          ],
        }),
    }) as any;
    render(<App />);
    await openWorkProject();
    await screen.findByText("The Educator");

    fireEvent.change(screen.getByLabelText("Assignment agent filter"), { target: { value: "strategist" } });
    expect(screen.queryByText("The Educator")).not.toBeInTheDocument();
    expect(screen.getByText("The Visionary")).toBeInTheDocument();
  });
});

describe("Work view — Deliverables", () => {
  const deliverableFixtures = () => ({
    [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    [`${API}/workspaces/projects`]: () =>
      ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
    [`${API}/workspaces/deliverables`]: () =>
      ok({
        items: [
          { id: "d1", title: "Report", project_id: "p1", latest_status: "approved", latest_version: 2 },
        ],
      }),
    [`${API}/workspaces/deliverables/d1/versions`]: () =>
      ok({
        items: [
          { id: "v1", version: 1, content: "hello", status: "approved" },
          { id: "v2", version: 2, content: "hello world", status: "pending" },
        ],
      }),
  });

  it("lists deliverables with their latest-version status", async () => {
    globalThis.fetch = makeFetch(deliverableFixtures()) as any;
    render(<App />);
    await openWorkProject();

    expect(await screen.findByText(/Report/)).toBeInTheDocument();
    expect(screen.getAllByText("Approved").length).toBeGreaterThanOrEqual(1);
  });

  it("loads versions and renders a diff between v1 and the latest version", async () => {
    globalThis.fetch = makeFetch(deliverableFixtures()) as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Report/));

    expect(await screen.findByText(/Comparison: v1 → v2/)).toBeInTheDocument();
    expect(screen.getByTestId("diff")).toHaveTextContent("hello world");
  });

  it("shows approve/reject controls only for non-approved versions", async () => {
    globalThis.fetch = makeFetch(deliverableFixtures()) as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Report/));

    const approve = await screen.findByRole("button", { name: "Approve" });
    const revision = screen.getByRole("button", { name: "Request revision" });
    expect(approve).toBeInTheDocument();
    expect(revision).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Approve" })).toHaveLength(1);
    // The approved v1 must not show approval controls.
    expect(screen.getAllByRole("button", { name: "Request revision" })).toHaveLength(1);
  });

  it("rejects a version via POST with a reason", async () => {
    const fn = makeFetch(deliverableFixtures());
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Report/));
    fireEvent.click(await screen.findByRole("button", { name: "Request revision" }));
    fireEvent.change(
      screen.getByPlaceholderText("Share what needs to change"),
      { target: { value: "Needs more details" } }
    );
    fireEvent.click(await screen.findByRole("button", { name: "Send request" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces/versions/v2/reject`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Needs more details" }) })
      );
    });
  });

  it("approves a version via POST", async () => {
    const fn = makeFetch(deliverableFixtures());
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Report/));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm approve" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces/versions/v2/approve`,
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("keeps the approve prompt open and shows an error when approve fails", async () => {
    const fn = makeFetch({
      ...deliverableFixtures(),
      [`${API}/workspaces/versions/v2/approve`]: () =>
        fail({ detail: "version already decided" }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Report/));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm approve" }));

    expect(await screen.findByTestId("version-error")).toHaveTextContent("version already decided");
    // Prompt stays open and success is not implied.
    expect(screen.getByRole("button", { name: "Confirm approve" })).toBeInTheDocument();
  });

  it("keeps the reject prompt open and preserves the reason when reject fails", async () => {
    const fn = makeFetch({
      ...deliverableFixtures(),
      [`${API}/workspaces/versions/v2/reject`]: () =>
        fail({ detail: "cannot reject" }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Report/));
    fireEvent.click(await screen.findByRole("button", { name: "Request revision" }));
    fireEvent.change(screen.getByPlaceholderText("Share what needs to change"), {
      target: { value: "fix intro" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Send request" }));

    expect(await screen.findByTestId("version-error")).toHaveTextContent("cannot reject");
    // Prompt stays open and the typed reason is preserved.
    expect(screen.getByRole("button", { name: "Send request" })).toBeInTheDocument();
    expect((screen.getByPlaceholderText("Share what needs to change") as HTMLInputElement).value).toBe("fix intro");
  });

  it("shows a load error when refreshing versions fails instead of silently showing stale data", async () => {
    const fn = makeFetch({
      ...deliverableFixtures(),
      [`${API}/workspaces/deliverables/d1/versions`]: () => fail({ detail: "boom" }, 500),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Report/));

    expect(await screen.findByTestId("version-error")).toHaveTextContent("Could not refresh deliverable versions.");
  });

  it("filters deliverables by status", async () => {
    globalThis.fetch = makeFetch({
      ...deliverableFixtures(),
      [`${API}/workspaces/deliverables`]: () =>
        ok({
          items: [
            { id: "d1", title: "Report", project_id: "p1", latest_status: "approved", latest_version: 2 },
            { id: "d2", title: "Draft", project_id: "p1", latest_status: "draft", latest_version: 1 },
          ],
        }),
    }) as any;
    render(<App />);
    await openWorkProject();
    await screen.findByText(/Report/);

    fireEvent.change(screen.getByLabelText("Deliverable status filter"), { target: { value: "draft" } });
    expect(screen.queryByText(/Report/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Draft").length).toBeGreaterThanOrEqual(1);
  });
});

;

describe.skip("Agents", () => {
  const agentsFixture = () => ({
    [`${API}/agents`]: () =>
      ok({
        agents: [
          { name: "tutor", role: "Personal tutor", personality: "patient", capabilities: ["explain"] },
          { name: "strategist", role: "Strategist", capabilities: ["plan"] },
          { name: "executive_assistant", role: "Executive Assistant" },
          { name: "communications", role: "Communications" },
          { name: "soundboard", role: "Soundboard" },
          { name: "workspace_architect", role: "Workspace Architect" },
        ],
      }),
  });

  it("lists all six agents and shows a selection prompt", async () => {
    globalThis.fetch = makeFetch(agentsFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    expect(await screen.findByRole("button", { name: "tutor" })).toBeInTheDocument();
    for (const n of ["strategist", "executive_assistant", "communications", "soundboard", "workspace_architect"]) {
      expect(screen.getByRole("button", { name: n })).toBeInTheDocument();
    }
    expect(screen.getByText(/Select an agent to begin/)).toBeInTheDocument();
  });

  it("renders the coordination panel and lists team goals", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/team/goals`]: () =>
        ok({ items: [{ id: "g1", title: "Launch", coordinator_agent: "workspace_architect", status: "approved" }] }),
      [`${API}/team/goals/g1`]: () =>
        ok({ id: "g1", title: "Launch", coordinator_agent: "workspace_architect", status: "approved", steps: [] }),
      [`${API}/team/goals/g1/coordination-plan`]: () =>
        ok({ team_goal_id: "g1", coordinator: "workspace_architect", steps: [], plan_valid: true, errors: [], warnings: [], transient: true }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    // Coordination panel present after agents/conversations load
    const panel = await screen.findByTestId("coordination-panel");
    expect(panel).toBeInTheDocument();
    const goalBtn = await screen.findByTestId("coord-goal-g1");
    expect(goalBtn.textContent).toContain("Launch");
  });

  it("shows agent display name and archetype when the backend provides them", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/agents`]: () =>
        ok({
          agents: [
            {
              name: "tutor",
              display_name: "Brittany",
              archetype: "The Educator",
              role: "Personal tutor",
              personality: "patient",
              capabilities: ["explain"],
            },
          ],
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    expect(await screen.findByText("Brittany")).toBeInTheDocument();
    expect(screen.getByText("The Educator")).toBeInTheDocument();
    // The card's accessible name remains the slug for stable lookups.
    expect(screen.getByRole("button", { name: "tutor" })).toBeInTheDocument();
  });

  it("shows responsibilities on the agent card", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/agents`]: () =>
        ok({
          agents: [
            {
              name: "tutor",
              display_name: "Brittany",
              archetype: "The Educator",
              role: "Personal tutor",
              responsibilities: "Explain concepts and build durable understanding.",
            },
          ],
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    expect(
      await screen.findByText("Explain concepts and build durable understanding.")
    ).toBeInTheDocument();
  });

  it("shows the agent detail panel with model, capabilities, tools, and assigned work", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/agents`]: () =>
        ok({
          agents: [
            {
              name: "tutor",
              display_name: "Brittany",
              archetype: "The Educator",
              role: "Personal tutor",
              personality: "patient",
              responsibilities: "Explain concepts and build durable understanding.",
              capabilities: ["explain", "quiz"],
              tools: ["calculate"],
              model: "llama3.1",
            },
          ],
        }),
      [`${API}/workspaces/goals`]: () =>
        ok({ items: [{ id: "g1", title: "Master algebra", project_id: "p1" }] }),
      [`${API}/workspaces/assignments`]: () =>
        ok({ items: [{ id: "a1", agent_id: "tutor", goal_id: "g1", status: "queued" }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));

    expect(await screen.findByTestId("agent-detail")).toBeInTheDocument();
    // responsibilities appear on both the card and the detail panel after selection.
    expect(screen.getAllByText("Explain concepts and build durable understanding.").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/model · llama3\.1/)).toBeInTheDocument();
    expect(screen.getByText("Capabilities")).toBeInTheDocument();
    expect(screen.getByText("explain")).toBeInTheDocument();
    expect(screen.getByText("quiz")).toBeInTheDocument();
    expect(screen.getByText("Tools")).toBeInTheDocument();
    expect(screen.getByText("calculate")).toBeInTheDocument();
    expect(screen.getByText("Assigned work")).toBeInTheDocument();
    expect(screen.getByText("Master algebra")).toBeInTheDocument();
  });

  it("submits a task and renders the reply with its execution location", async () => {
    const fn = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "Gravity pulls objects together.",
          location: "local:ollama:llama3.1",
          facts: [],
          proposals: [],
          tool_results: [],
        }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "Explain gravity" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/agents/tutor/run`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ task: "Explain gravity" }) })
      );
    });
    expect(await screen.findByText("Gravity pulls objects together.")).toBeInTheDocument();
    expect(screen.getByText(/Execution: local:ollama:llama3\.1/)).toBeInTheDocument();
  });

  it("shows an error when agent execution fails", async () => {
    const fn = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/strategist/run`]: () =>
        Promise.resolve({ ok: false, status: 502, json: () => Promise.resolve({ detail: "Ollama unreachable" }) }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "strategist" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "Plan the quarter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));

    // D4.2 L3: a 5xx renders a generic friendly error, never raw backend detail.
    expect(
      await screen.findByText(/couldn\u2019t complete the request right now/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Ollama unreachable/)).not.toBeInTheDocument();
  });

  it("keeps the run button disabled with no task entered", async () => {
    globalThis.fetch = makeFetch(agentsFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
    expect(screen.getByRole("button", { name: "Run Agent" })).toBeDisabled();
  });

  it("carries the thread id across turns and shows the context indicator", async () => {
    const fn = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/tutor/run`]: (url: string, opts?: any) => {
        const reqBody = JSON.parse(opts.body);
        return ok({
          agent: "tutor",
          reply: "ack",
          location: "local:ollama:llama3.1",
          facts: [],
          proposals: [],
          tool_results: [],
          thread_id: "tid-1",
          context_messages: reqBody.thread_id ? 2 : 0,
        });
      },
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));

    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    await screen.findByTestId("agent-reply");

    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "again" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));

    await waitFor(() => {
      const calls = fn.mock.calls.filter((c: any) => c[0] === `${API}/agents/tutor/run`);
      expect(calls.length).toBeGreaterThanOrEqual(2);
      expect(JSON.parse(calls[calls.length - 1][1].body).thread_id).toBe("tid-1");
    });

    expect(await screen.findByText(/This conversation · 2 message\(s\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New conversation" })).toBeInTheDocument();
  });

  it("resets to a fresh thread via New conversation", async () => {
    globalThis.fetch = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "ack",
          location: "local:ollama:llama3.1",
          facts: [],
          proposals: [],
          tool_results: [],
          thread_id: "tid-1",
          context_messages: 2,
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    await screen.findByText(/This conversation · 2 message\(s\)/);

    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByRole("button", { name: "New conversation" })).not.toBeInTheDocument();
    expect(screen.getByText(/This conversation · 0 message\(s\)/)).toBeInTheDocument();
  });

  it("clears the input immediately when a submission is accepted", async () => {
    let resolveRun!: (v: unknown) => void;
    const runPromise = new Promise((res) => {
      resolveRun = res;
    });
    globalThis.fetch = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/tutor/run`]: () => runPromise,
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
    const input = screen.getByPlaceholderText("Give your agent a task…");
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));

    // While the request is in flight, the input is cleared and ready for the next message.
    await waitFor(() => expect(input).toHaveValue(""));

    resolveRun({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          agent: "tutor",
          reply: "hi",
          location: "local:ollama:llama3.1",
          facts: [],
          proposals: [],
          tool_results: [],
        }),
    });
    await screen.findByTestId("agent-reply");
  });

  it("preserves the input when a submission fails", async () => {
    globalThis.fetch = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/strategist/run`]: () =>
        Promise.resolve({ ok: false, status: 502, json: () => Promise.resolve({ detail: "Ollama unreachable" }) }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "strategist" }));
    const input = screen.getByPlaceholderText("Give your agent a task…");
    fireEvent.change(input, { target: { value: "Plan the quarter" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));

    // D4.2 L3: friendly 5xx message shown, and the message text is preserved.
    expect(
      await screen.findByText(/couldn\u2019t complete the request right now/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Ollama unreachable/)).not.toBeInTheDocument();
    expect(input).toHaveValue("Plan the quarter");
  });

  it("submits on Enter (without Shift) as well as the button", async () => {
    const fn = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "ack",
          location: "local:ollama:llama3.1",
          facts: [],
          proposals: [],
          tool_results: [],
        }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
    const input = screen.getByPlaceholderText("Give your agent a task…");
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/agents/tutor/run`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ task: "hello" }) })
      );
    });
  });

  it("renders markdown in the agent reply", async () => {
    globalThis.fetch = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/tutor/run`]: () =>
        ok({
          agent: "tutor",
          reply: "# Greeting\n\nHello **world**",
          location: "local:ollama:llama3.1",
          facts: [],
          proposals: [],
          tool_results: [],
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "hi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Greeting" })).toBeInTheDocument();
    expect(screen.getByText("world").tagName).toBe("STRONG");
  });
});

describe("UI Cleanup & sample-data handling", () => {
  // A real ID present in KNOWN_SAMPLE_IDS (test-origin record in the local DB).
  const SAMPLE_WID = "024df94a-70d1-4419-980b-ffb02dae8073";

  beforeEach(() => {
    localStorage.clear();
  });

  it("hides known sample workspaces by default and reveals them via the toggle", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () =>
        ok({
          items: [
            { id: SAMPLE_WID, name: "E2E Workspace" },
            { id: "w-real", name: "My Team" },
          ],
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(await screen.findByText("My Team")).toBeInTheDocument();
    expect(screen.queryByText("E2E Workspace")).not.toBeInTheDocument();
    // Sample controls live in Settings (kept out of the main navigation).
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Show sample data" }));
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(await screen.findByText("E2E Workspace")).toBeInTheDocument();
  });

  it("keeps legitimate records visible when they share a test record's name", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () =>
        ok({
          items: [
            { id: SAMPLE_WID, name: "E2E Workspace" },
            { id: "w-real-2", name: "E2E Workspace" },
          ],
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    await screen.findByText("E2E Workspace");
    // Hiding is by ID only, so exactly one (the legitimate) record remains.
    expect(screen.getAllByText("E2E Workspace").length).toBe(1);
  });

  it("opens a project's detail from Overview recent projects", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () =>
        ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1", status: "active" }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(await screen.findByText(/Launch/));
    expect(await screen.findByText(/No goals for this project yet/)).toBeInTheDocument();
  });

  it("opens a goal detail panel from the Work view", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () =>
        ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
      [`${API}/workspaces/goals`]: () =>
        ok({ items: [{ id: "g1", title: "Ship v1", project_id: "p1", status: "open", progress: 40 }] }),
    }) as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Ship v1/));
    expect(await screen.findByText("Progress")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
  });

  it("opens an assignment detail panel from the Work view", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () =>
        ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
      [`${API}/workspaces/goals`]: () =>
        ok({ items: [{ id: "g1", title: "Ship v1", project_id: "p1", status: "open" }] }),
      [`${API}/workspaces/assignments`]: () =>
        ok({ items: [{ id: "a1", goal_id: "g1", agent_id: "tutor", status: "queued" }] }),
      [`${API}/agents`]: () =>
        ok({ agents: [{ name: "tutor", display_name: "Brittany", archetype: "The Educator" }] }),
    }) as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(screen.getByTestId("assignment-a1"));
    // Target the detail panel's heading (the composer also lists "Assignment").
    expect(await screen.findByRole("heading", { name: "Assignment" })).toBeInTheDocument();
    expect(screen.getAllByText("Ship v1").length).toBeGreaterThanOrEqual(1);
  });

  it("lists a deliverable's full version history with readable content", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () =>
        ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
      [`${API}/workspaces/deliverables`]: () =>
        ok({ items: [{ id: "d1", title: "Report", project_id: "p1", latest_status: "pending", latest_version: 2 }] }),
      [`${API}/workspaces/deliverables/d1/versions`]: () =>
        ok({
          items: [
            { id: "v1", version: 1, content: "First draft", status: "draft" },
            { id: "v2", version: 2, content: "# Final\n\nDetailed output", status: "pending" },
          ],
        }),
    }) as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByText(/Report/));
    expect(await screen.findByText("v1")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    // The draft content appears both as the version body and in the diff summary.
    expect(screen.getAllByText("First draft").length).toBeGreaterThanOrEqual(1);
  });
});

describe.skip("Conversation Browser", () => {
  const agentsFixture = () => ({
    [`${API}/agents`]: () =>
      ok({ agents: [{ name: "strategist", display_name: "Aisha", archetype: "The Visionary" }] }),
  });
  const convosFixture = () => ({
    ...agentsFixture(),
    [`${API}/memory/conversations`]: () =>
      ok({
        items: [
          { thread_id: "tid-a", agent_id: "strategist", title: "Grow my business", is_renamed: false, last_activity: "2026-11-02T00:00:00Z", message_count: 4 },
          { thread_id: "tid-legacy", agent_id: null, title: "Legacy talk", is_renamed: false, last_activity: "2026-11-01T00:00:00Z", message_count: 2 },
        ],
      }),
  });
  const transcriptFixture = (extra: any[] = []) => ({
    ...convosFixture(),
    [`${API}/memory/conversation?thread_id=tid-a`]: () =>
      ok({
        items: [
          { role: "user", content: "grow my business", created_at: "2026-11-01T00:00:01Z" },
          { role: "assistant", content: "# Plan\n\nThree objectives", created_at: "2026-11-01T00:00:02Z" },
          { role: "user", content: "go on", created_at: "2026-11-01T00:00:03Z" },
          { role: "assistant", content: "Step two", created_at: "2026-11-01T00:00:04Z" },
          ...extra,
        ],
      }),
  });

  it("lists conversations with agent names and Agent unknown", async () => {
    globalThis.fetch = makeFetch(convosFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    expect(await screen.findByText("Grow my business")).toBeInTheDocument();
    expect(screen.getAllByText("Aisha").length).toBeGreaterThanOrEqual(1); // agent label on the conversation + card
    expect(screen.getByText(/Agent unknown/)).toBeInTheDocument();
    expect(screen.getByText("Legacy talk")).toBeInTheDocument();
  });

  it("filters conversations by agent", async () => {
    globalThis.fetch = makeFetch(convosFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    await screen.findByText("Grow my business");
    fireEvent.change(screen.getByLabelText("Filter conversations by agent"), { target: { value: "strategist" } });
    expect(screen.getByText("Grow my business")).toBeInTheDocument();
    expect(screen.queryByText("Legacy talk")).not.toBeInTheDocument();
  });

  it("opens a conversation and renders the full transcript (not limited to 12)", async () => {
    const longTail: any[] = [];
    for (let i = 3; i < 16; i++) {
      longTail.push({ role: "user", content: `deep q${i}`, created_at: `2026-11-01T00:00:0${i % 10}Z` });
      longTail.push({ role: "assistant", content: `deep a${i}`, created_at: `2026-11-01T00:00:0${(i + 1) % 10}Z` });
    }
    globalThis.fetch = makeFetch(transcriptFixture(longTail)) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Grow my business"));
    const tr = await screen.findByTestId("transcript");
    expect(tr).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Plan" })).toBeInTheDocument(); // Markdown heading renders
    expect(screen.getByText("deep q15")).toBeInTheDocument(); // far beyond the 12-message window
  });

  it("shows message timestamps and no thinking indicator while idle", async () => {
    globalThis.fetch = makeFetch(transcriptFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Grow my business"));
    await screen.findByTestId("transcript");
    expect(screen.getByTestId("msg-0")).toBeInTheDocument();
    expect(screen.getByTestId("msg-time-0").textContent).not.toBe("");
    expect(screen.getByTestId("msg-time-1").textContent).not.toBe("");
    expect(screen.queryByTestId("chat-thinking")).toBeNull();
  });

  it("continuing appends to the same thread", async () => {
    const fn = makeFetch({
      ...transcriptFixture(),
      [`${API}/agents/strategist/run`]: (url: string, opts?: any) => {
        const req = JSON.parse(opts.body);
        return ok({
          agent: "strategist", reply: "Continuing here", location: "local:ollama:llama3.1",
          facts: [], proposals: [], tool_results: [],
          thread_id: req.thread_id, context_messages: 2,
        });
      },
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Grow my business"));
    await screen.findByTestId("transcript");
    // Set the active thread, then send a message.
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "next" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    await waitFor(() => {
      const calls = fn.mock.calls.filter((c: any) => c[0] === `${API}/agents/strategist/run`);
      expect(calls.length).toBeGreaterThanOrEqual(1);
      expect(JSON.parse(calls[0][1].body).thread_id).toBe("tid-a");
    });
    expect(await screen.findByText("Continuing here")).toBeInTheDocument();
  });

  it("renames a conversation via PATCH", async () => {
    const fn = makeFetch(convosFixture());
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    await screen.findByText("Grow my business");
    fireEvent.click(screen.getAllByRole("button", { name: "Rename" })[0]);
    fireEvent.change(screen.getByPlaceholderText("Rename conversation"), { target: { value: "My Growth Plan" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/memory/conversations/tid-a`,
        expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "My Growth Plan" }) })
      );
    });
  });

  it("New Conversation does not delete saved conversations", async () => {
    globalThis.fetch = makeFetch(transcriptFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Grow my business"));
    await screen.findByTestId("transcript");
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    // Browser still lists the saved conversations after starting fresh.
    expect(screen.getByText("Grow my business")).toBeInTheDocument();
    expect(screen.getByText("Legacy talk")).toBeInTheDocument();
  });
});

describe.skip("Phase 1: agent idea-draft to proposal capture", () => {
  function agentsFixture() {
    return {
      [`${API}/agents`]: () =>
        ok({ agents: [{ name: "strategist", display_name: "Aisha", archetype: "The Visionary", responsibilities: "Planning" }] }),
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", status: "active", workspace_id: "w1" }] }),
      [`${API}/agents/strategist/run`]: () =>
        ok({
          agent: "strategist", reply: "Here is a goal idea: improve onboarding.", location: "local:ollama:llama3.1",
          facts: [], proposals: [], tool_results: [], thread_id: "t-1", context_messages: 1,
        }),
    };
  }

  it("lets the user promote an agent idea into an approvable goal proposal", async () => {
    const fn = makeFetch(agentsFixture());
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Aisha"));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "draft a goal" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    await screen.findByText(/improve onboarding/);
    fireEvent.click(screen.getByTestId("draft-open"));
    fireEvent.change(screen.getByPlaceholderText("Short title for this idea"), { target: { value: "Improve onboarding" } });
    fireEvent.click(screen.getByTestId("draft-submit"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/proposals`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            work_type: "goal", action: "create",
            payload: { project_id: "p1", title: "Improve onboarding" },
            agent_id: "strategist",
          }),
        })
      );
    });
    expect(await screen.findByTestId("draft-goto")).toBeInTheDocument();
  });

  it("creates a proposal from the always-available composer without needing a reply", async () => {
    // No run route at all: the composer must work deterministically without a
    // generated reply (the safest path when the model is slow or offline).
    const fn = makeFetch(agentsFixture());
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Aisha"));
    await screen.findByTestId("draft-composer");
    fireEvent.change(screen.getByTestId("draft-composer-type"), { target: { value: "project" } });
    fireEvent.change(screen.getByTestId("draft-composer-title"), {
      target: { value: "Launch new community portal" },
    });
    fireEvent.click(screen.getByTestId("draft-composer-submit"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/proposals`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            work_type: "project", action: "create",
            payload: { workspace_id: "w1", name: "Launch new community portal" },
            agent_id: "strategist",
          }),
        })
      );
    });
  });

  it("suggests ideas as parented proposals via the brainstorm action", async () => {
    const fn = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/strategist/run`]: (url: string, opts?: any) => {
        const body = JSON.parse(opts.body);
        return ok({
          agent: "strategist", reply: "Three ideas below.",
          location: "local:ollama:llama3.1", facts: [], tool_results: [],
          proposals: ["ip1", "ip2", "ip3"],
          proposal_results: [
            { status: "saved", proposal_id: "ip1" },
            { status: "saved", proposal_id: "ip2" },
            { status: "saved", proposal_id: "ip3" },
          ],
          thread_id: "t-1", context_messages: 1,
          received: body,
        });
      },
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Aisha"));
    fireEvent.click(screen.getByTestId("suggest-ideas"));
    await waitFor(() => {
      const call = fn.mock.calls.find(
        (c: any) => c[0] === `${API}/agents/strategist/run`
      );
      expect(call).toBeTruthy();
      const body = JSON.parse(call[1].body);
      expect(body.work_intent).toBe(true);
      expect(body.project_id).toBe("p1");
      expect(body.workspace_id).toBe("w1");
      expect(body.task).toMatch(/propose|ideas/i);
    });
    expect(await screen.findByText(/idea\(s\) filed as proposals/)).toBeInTheDocument();
    expect(screen.getByTestId("ideas-to-approve")).toBeInTheDocument();
  });

  it("suggests a next step for a goal via the strategies run", async () => {
    const fn = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", status: "active", workspace_id: "w1" }] }),
      [`${API}/workspaces/goals`]: () => ok({ items: [{ id: "g1", project_id: "p1", title: "Launch Goal", status: "open" }] }),
      [`${API}/agents/strategist/run`]: (url: string, opts?: any) => {
        const body = JSON.parse(opts.body);
        return ok({
          agent: "strategist", reply: "Next step proposed.", facts: [], tool_results: [],
          proposals: ["np1"],
          proposal_results: [{ status: "saved", proposal_id: "np1" }],
          thread_id: "t-1", context_messages: 1, received: body,
        });
      },
    });
    globalThis.fetch = fn as any;
    render(<App />);
    // The goal list with "Suggest next step" lives in the Workspaces tab under
    // a selected workspace -> project.
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(await screen.findByText("Acme"));
    fireEvent.click(screen.getByText("Launch"));
    fireEvent.click(await screen.findByTestId("suggest-next-g1"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0] === `${API}/agents/strategist/run`);
      expect(call).toBeTruthy();
      const body = JSON.parse(call[1].body);
      expect(body.work_intent).toBe(true);
      expect(body.project_id).toBe("p1");
      expect(body.task).toMatch(/NEXT step/i);
    });
    const msg = await screen.findByTestId("nextstep-msg-g1");
    expect(msg.textContent || "").toMatch(/Proposed 1 next-step/);
  });

  it("files an approval-gated assignment proposal to a teammate", async () => {
    const fn = makeFetch({
      [`${API}/agents`]: () =>
        ok({ agents: [
          { name: "strategist", display_name: "Aisha", archetype: "Strategist" },
          { name: "communications", display_name: "Brandon", archetype: "Communications" },
        ] }),
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", status: "active", workspace_id: "w1" }] }),
      [`${API}/workspaces/goals`]: () => ok({ items: [{ id: "g1", project_id: "p1", title: "Launch Goal", status: "open" }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(await screen.findByText("Acme"));
    fireEvent.click(screen.getByText("Launch"));
    fireEvent.click(await screen.findByTestId("assign-open-g1"));
    fireEvent.change(screen.getByTestId("assign-owner-g1"), { target: { value: "communications" } });
    fireEvent.click(screen.getByTestId("assign-submit-g1"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/proposals`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            work_type: "assignment", action: "create",
            payload: { goal_id: "g1", agent_id: "communications", priority: 0 },
            agent_id: "strategist",
          }),
        })
      );
    });
    expect(await screen.findByTestId("assign-msg-g1")).toBeInTheDocument();
  });

  it("does not offer proposal capture when generation failed", async () => {
    const fn = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/strategist/run`]: () =>
        ok({
          agent: "strategist", reply: "",
          location: "local:ollama:llama3.1", facts: [], proposals: [], tool_results: [],
          thread_id: "t-1", context_messages: 1,
          generation_error: { code: "model_empty" },
        }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Aisha"));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), { target: { value: "draft a goal" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));
    await screen.findByTestId("gen-failure-panel");
    expect(screen.queryByTestId("draft-open")).not.toBeInTheDocument();
  });
});

describe("D4.3-A1 unified command interface", () => {
  const planFixture = {
    [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", status: "active", workspace_id: "w1" }] }),
    [`${API}/agents`]: () =>
      ok({ agents: [
        { name: "strategist", display_name: "Aisha", archetype: "Strategist" },
        { name: "communications", display_name: "Brandon", archetype: "Communications" },
      ] }),
    [`${API}/agents/plan`]: (url: string, opts?: any) => {
      const sent = JSON.parse(opts.body);
      return ok({
        objective: sent.objective, coordinator: "strategist", reply: "Here is the plan.",
        steps: [
          { work_type: "goal", title: "Scope launch", suggested_agent: "strategist", reason: "plan it", project_id: "p1" },
          { work_type: "deliverable", title: "Landing page", suggested_agent: "communications", reason: "comms", project_id: "p1" },
        ],
        provider: "ollama", sent,
      });
    },
  };

  it("generates and renders a coordinated team plan preview", async () => {
    const fn = makeFetch(planFixture);
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    fireEvent.change(screen.getByTestId("plan-objective"), {
      target: { value: "Help me organize the launch of my new business." },
    });
    fireEvent.click(screen.getByTestId("plan-submit"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0] === `${API}/agents/plan`);
      expect(call).toBeTruthy();
      const body = JSON.parse(call[1].body);
      expect(body.objective).toMatch(/launch/i);
      expect(body.project_id).toBe("p1");
    });
    const panel = await screen.findByTestId("plan-preview");
    expect(panel).toBeInTheDocument();
    // Coordinator + owner suggestions render as display names.
    expect(screen.getAllByText("Aisha").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Brandon").length).toBeGreaterThanOrEqual(1);
    // Titles now render as editable inputs (A2) backed by the plan step value.
    expect(screen.getByDisplayValue(/Scope launch/)).toBeInTheDocument();
    // Preview remains non-destructive: no proposal was created.
    const propCalls = fn.mock.calls.filter((c: any) => c[0] === `${API}/work/proposals` && ((c[1]?.method || "GET").toUpperCase() === "POST"));
    expect(propCalls.length).toBe(0);
  });

  it("shows an honest error when generation fails", async () => {
    const fn = makeFetch({
      ...planFixture,
      [`${API}/agents/plan`]: () => ok({ objective: "x", coordinator: "strategist", reply: "", steps: [], generation_error: { code: "model_unavailable" } }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    fireEvent.change(screen.getByTestId("plan-objective"), { target: { value: "organize" } });
    fireEvent.click(screen.getByTestId("plan-submit"));
    const err = await screen.findByTestId("plan-error");
    expect(err.textContent || "").toMatch(/temporarily unavailable/i);
  });
});

describe("D4.3-A2 plan approval bridge", () => {
  const a2Fixture = {
    [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", status: "active", workspace_id: "w1" }] }),
    [`${API}/workspaces/goals`]: () => ok({ items: [{ id: "g1", project_id: "p1", title: "Launch Goal", status: "open" }] }),
    [`${API}/agents`]: () => ok({ agents: [
      { name: "strategist", display_name: "Aisha", archetype: "Strategist" },
      { name: "communications", display_name: "Brandon", archetype: "Communications" },
      { name: "executive_assistant", display_name: "Taylor", archetype: "Exec" },
    ] }),
    [`${API}/agents/plan`]: () => ok({
      objective: "x", coordinator: "strategist", reply: "",
      steps: [
        { work_type: "goal", title: "Scope launch", suggested_agent: "strategist", project_id: "p1", workspace_id: "w1" },
        { work_type: "deliverable", title: "Landing", suggested_agent: "communications", project_id: "p1", workspace_id: "w1" },
        { work_type: "assignment", title: "Onboard task", suggested_agent: "executive_assistant", project_id: "p1", workspace_id: "w1" },
      ],
    }),
  };

  async function openPlan() {
    await openWorkProject();
    fireEvent.change(screen.getByTestId("plan-objective"), { target: { value: "organize launch" } });
    fireEvent.click(screen.getByTestId("plan-submit"));
    await screen.findByTestId("plan-preview");
  }

  it("edits title/owner and approves a step via /work/proposals", async () => {
    const fn = makeFetch({ ...a2Fixture, [`${API}/work/proposals`]: () => ok({ proposal_id: "pr1" }) });
    globalThis.fetch = fn as any;
    render(<App />);
    await openPlan();
    fireEvent.change(screen.getByTestId("plan-step-title-0"), { target: { value: "Launch website scope" } });
    fireEvent.change(screen.getByTestId("plan-step-owner-0"), { target: { value: "communications" } });
    fireEvent.click(screen.getByTestId("plan-approve-0"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0] === `${API}/work/proposals` && ((c[1]?.method || "GET").toUpperCase() === "POST"));
      expect(call).toBeTruthy();
      const body = JSON.parse(call[1].body);
      expect(body.work_type).toBe("goal");
      expect(body.payload.title).toBe("Launch website scope");
      expect(body.payload.project_id).toBe("p1");
      expect(body.agent_id).toBe("communications"); // owner override, not suggested_agent
    });
    expect(await screen.findByTestId("plan-done-0")).toBeInTheDocument();
  });

  it("creates the generated plan as a coordination TeamGoal (Projects \u2192 pipeline)", async () => {
    let proposed: any = null;
    const fn = makeFetch({
      ...a2Fixture,
      [`${API}/team/goals/validate`]: (url: string, init: any) => {
        const stepsFrom = (a2Fixture[`${API}/agents/plan`]() as any).steps;
        return ok({
          coordinator: "strategist", plan_valid: true, errors: [],
          steps: stepsFrom.map((s: any, i: number) => ({
            seq: i + 1, agent_id: s.suggested_agent, responsibility: s.title,
            capability_ok: true, delegation_ok: true, valid: true, error: null,
          })),
        });
      },
      [`${API}/team/goals`]: (url: string, init: any) => {
        proposed = JSON.parse(init.body);
        return ok({ team_goal_id: "tg-x", status: "proposed", reused: false });
      },
    });
    globalThis.fetch = fn as any;
    render(<App />);
    await openPlan();
    fireEvent.click(screen.getByTestId("plan-delegate"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) =>
        c[0] === `${API}/team/goals` && ((c[1]?.method || "GET").toUpperCase() === "POST"));
      expect(call).toBeTruthy();
    });
    expect(proposed).toBeTruthy();
    expect(proposed.steps.length).toBe(3);
    expect(proposed.steps[0].agent_id).toBe("strategist");
    expect(proposed.coordinator_agent).toBe("strategist");
    expect(await screen.findByTestId("plan-delegate-msg")).toBeInTheDocument();
  });

  it("rejects one step; approve-all skips it and unsupported steps", async () => {
    const fn = makeFetch({ ...a2Fixture, [`${API}/work/proposals`]: () => ok({ proposal_id: "pr" }) });
    globalThis.fetch = fn as any;
    render(<App />);
    await openPlan();
    fireEvent.click(screen.getByTestId("plan-reject-1"));
    fireEvent.click(screen.getByTestId("plan-approve-all"));
    await waitFor(() => {
      const posted = fn.mock.calls
        .filter((c: any) => c[0] === `${API}/work/proposals` && ((c[1]?.method || "GET").toUpperCase() === "POST"))
        .map((c: any) => JSON.parse(c[1].body).work_type);
      expect(posted).toContain("goal");
      expect(posted).not.toContain("deliverable"); // rejected
      expect(posted).not.toContain("assignment"); // no target goal chosen -> not filed
    });
  });

  it("assignment step posts with chosen goal and owner", async () => {
    const fn = makeFetch({ ...a2Fixture, [`${API}/work/proposals`]: () => ok({ proposal_id: "pr" }) });
    globalThis.fetch = fn as any;
    render(<App />);
    await openPlan();
    const goalSel = await screen.findByTestId("plan-step-goal-2");
    fireEvent.change(goalSel, { target: { value: "g1" } });
    fireEvent.click(screen.getByTestId("plan-approve-2"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0] === `${API}/work/proposals` && ((c[1]?.method || "GET").toUpperCase() === "POST"));
      expect(call).toBeTruthy();
      const body = JSON.parse(call[1].body);
      expect(body.work_type).toBe("assignment");
      expect(body.payload.goal_id).toBe("g1");
      expect(body.payload.agent_id).toBe("executive_assistant");
    });
  });

  it("marks unsupported step types instead of offering Approve", async () => {
    const fn = makeFetch({
      ...a2Fixture,
      [`${API}/agents/plan`]: () => ok({
        objective: "x", coordinator: "strategist", reply: "",
        steps: [{ work_type: "goal_update", action: "update", title: "Tweak a goal", project_id: "p1" }],
      }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    await openPlan();
    // Unsupported step: no Approve control, a clear label, and no proposal POST.
    expect(screen.getByTestId("plan-unsupported-0")).toBeInTheDocument();
    expect(screen.queryByTestId("plan-approve-0")).not.toBeInTheDocument();
    expect(fn.mock.calls.filter((c: any) => c[0] === `${API}/work/proposals` && ((c[1]?.method || "GET").toUpperCase() === "POST")).length).toBe(0);
  });
});

describe("D4.3 empty-parent guidance", () => {
  it("shows actionable guidance when no project exists to attach work to", async () => {
    const fn = makeFetch({
      [`${API}/agents`]: () => ok({ agents: [{ name: "strategist", display_name: "Aisha", archetype: "Strategist" }] }),
      [`${API}/workspaces`]: () => ok({ items: [] }),
      [`${API}/workspaces/projects`]: () => ok({ items: [] }),
      [`${API}/agents/plan`]: () => ok({ objective: "x", coordinator: "strategist", reply: "", steps: [] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    const guide = await screen.findByTestId("plan-needs-project");
    expect(guide).toBeInTheDocument();
    expect(guide.textContent || "").toMatch(/no project yet/i);
  });
});

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

describe("Approvals & work navigation (M10 D1)", () => {
  it("shows pending vs decided proposals and limits controls to pending", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/work/feed`]: () =>
        ok({
          items: [
            { id: "pend1", work_type: "project", action: "create", status: "proposed", proposed_change: "create project", decision: null },
            { id: "rej1", work_type: "goal", action: "create", status: "rejected", proposed_change: "create goal", decision: { approver: "u1", decided_at: "2026-01-01T00:00:00Z", rejection_reason: "declined", work_type: "goal", work_id: null, label: null } },
            { id: "app1", work_type: "goal", action: "create", status: "approved", proposed_change: "create goal", decision: { work_id: "g1", work_type: "goal", label: "Launch Goal", approver: "u1", decided_at: "2026-01-01T00:00:00Z" } },
          ],
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    expect(await screen.findByTestId("approvals-panel")).toBeInTheDocument();
    // Distinct badges
    expect(screen.getByText("Pending approval")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    // Controls only for pending
    expect(screen.getByTestId("approve-pend1")).toBeInTheDocument();
    expect(screen.getByTestId("reject-pend1")).toBeInTheDocument();
    expect(screen.queryByTestId("approve-rej1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approve-app1")).not.toBeInTheDocument();
    // Decided shows result navigation + rejection reason
    expect(screen.getByTestId("result-app1")).toBeInTheDocument();
    expect(screen.getByText("declined")).toBeInTheDocument();
  });

  it("labels proposals with work type, generated name, and next step (M11 Fix 3)", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/work/feed`]: () =>
        ok({
          items: [
            { id: "p1", work_type: "project", action: "create", status: "proposed", proposed_change: "create project", decision: null, payload: { name: "On Us Launch" } },
            { id: "p2", work_type: "goal", action: "create", status: "proposed", proposed_change: "create goal", decision: null, payload: { title: "Boost onboarding" } },
            { id: "p3", work_type: "deliverable", action: "create", status: "approved", proposed_change: "create deliverable", decision: { work_id: "d1", work_type: "deliverable", label: "Marketing plan", approver: "u1", decided_at: "2026-01-01T00:00:00Z" }, payload: { title: "Marketing plan" } },
          ],
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    expect(await screen.findByTestId("approvals-panel")).toBeInTheDocument();
    // Generated names shown (not the generic "create goal").
    expect(screen.getByText("On Us Launch")).toBeInTheDocument();
    expect(screen.getByText("Boost onboarding")).toBeInTheDocument();
    expect(screen.getByText("Marketing plan")).toBeInTheDocument();
    // Work-type badge labelled (within the approvals item).
    const firstApprovalItem = screen.getByTestId("proposal-p1");
    expect(firstApprovalItem.textContent).toMatch(/Project/);
    // Next-step hint for pending.
    expect(screen.getAllByText(/Approve to create/).length).toBeGreaterThan(0);
  });

  it("approves a pending proposal through the Phase C endpoint", async () => {
    const fn = makeFetch({
      [`${API}/work/feed`]: () =>
        ok({ items: [{ id: "pend1", work_type: "project", action: "create", status: "proposed", proposed_change: "create project", decision: null }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    fireEvent.click(await screen.findByTestId("approve-pend1"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/proposals/pend1/approve`,
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("approves all pending proposals in one gesture", async () => {
    const fn = makeFetch({
      [`${API}/work/feed`]: () =>
        ok({
          items: [
            { id: "pend1", work_type: "goal", action: "create", status: "proposed", proposed_change: "create goal A", decision: null },
            { id: "pend2", work_type: "goal", action: "create", status: "proposed", proposed_change: "create goal B", decision: null },
            { id: "done1", work_type: "goal", action: "create", status: "approved", proposed_change: "create goal C", decision: { work_id: "g1", work_type: "goal", label: "Goal C", approver: "u1", decided_at: "2026-01-01T00:00:00Z" } },
          ],
        }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    fireEvent.click(await screen.findByTestId("approve-all-pending"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/proposals/pend1/approve`,
        expect.objectContaining({ method: "POST" })
      );
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/proposals/pend2/approve`,
        expect.objectContaining({ method: "POST" })
      );
      // Approved item is never re-approved by the batch action.
      const doneCalls = fn.mock.calls.filter((c: any) => c[0] === `${API}/work/proposals/done1/approve`);
      expect(doneCalls.length).toBe(0);
    });
    expect(await screen.findByText(/Approved 2 proposal/)).toBeInTheDocument();
  });

  it.skip("shows linked work for an opened conversation", async () => {
    const agent = ok({ agents: [{ name: "strategist", display_name: "Aisha", archetype: "The Visionary" }] });
    const fixture = {
      [`${API}/agents`]: () => agent,
      [`${API}/memory/conversations`]: () =>
        ok({ items: [{ thread_id: "tid-a", agent_id: "strategist", title: "Grow my business", is_renamed: false, message_count: 1 }] }),
      [`${API}/memory/conversation?thread_id=tid-a`]: () =>
        ok({ items: [{ role: "user", content: "hi", created_at: "2026-11-01T00:00:00Z" }] }),
      [`${API}/work/links?thread_id=tid-a`]: () =>
        ok({ items: [{ work_type: "goal", work_id: "g1", label: "Launch Goal", thread_id: "tid-a" }] }),
    };
    globalThis.fetch = makeFetch(fixture) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI Team" }));
    fireEvent.click(await screen.findByText("Grow my business"));
    expect(await screen.findByTestId("linked-work")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Launch Goal" })).toBeInTheDocument();
  });
});

;

;

describe("Approved-assignment execution (M10 D4.1)", () => {
  const base = () => ({
    [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
    [`${API}/workspaces/goals`]: () => ok({ items: [{ id: "g1", title: "Ship v1", project_id: "p1", status: "open" }] }),
    [`${API}/workspaces/assignments`]: () => ok({ items: [{ id: "a1", goal_id: "g1", agent_id: "tutor", status: "queued" }] }),
    [`${API}/workspaces/deliverables`]: () => ok({ items: [] }),
  });

  it("shows Run approved only for a genuinely approved assignment", async () => {
    const fn = makeFetch({
      ...base(),
      [`${API}/work/feed`]: () => ok({ items: [{ id: "pr1", work_type: "assignment", status: "approved", result_id: "a1" }] }),
      [`${API}/work/assignment/a1/execute-approved`]: () => ok({ episode_id: "ep1", status: "running", already_active: false, assignment_id: "a1", agent_id: "tutor" }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByTestId("assignment-a1"));
    fireEvent.click(await screen.findByTestId("approved-run-a1"));
    fireEvent.click(await screen.findByTestId("run-a1"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/assignment/a1/execute-approved`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ agent_id: "tutor" }) })
      );
    });
    expect(await screen.findByText("Tracking")).toBeInTheDocument();
  });

  it("does not expose an execution control on an unapproved assignment", async () => {
    globalThis.fetch = makeFetch({ ...base(), [`${API}/work/feed`]: () => ok({ items: [] }) }) as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click(await screen.findByTestId("assignment-a1"));
    expect(await screen.findByTestId("not-approved-a1")).toBeInTheDocument();
    expect(screen.queryByTestId("approved-run-a1")).not.toBeInTheDocument();
  });
});

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
