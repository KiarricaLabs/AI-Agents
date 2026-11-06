import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import App from "./App";
import { Coordination } from "./coordination_panel";
import { ReviewCenter } from "./review_center";
import { TeamMemory } from "./team_memory";
import { TeamChat } from "./team_chat";
import { Pipeline } from "./pipeline";

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
      ["activity", "Activity"],
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

describe("Episodes", () => {
  const agentsFixture = () => ({
    [`${API}/agents`]: () =>
      ok({ agents: [{ name: "tutor", display_name: "Brittany", archetype: "The Educator" }] }),
  });

  it("shows empty state when there are no episodes", async () => {
    globalThis.fetch = makeFetch() as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    expect(await screen.findByText(/No agent activity yet/)).toBeInTheDocument();
  });

  it("renders episode progress and running controls with the agent display name", async () => {
    globalThis.fetch = makeFetch({
      ...agentsFixture(),
      [`${API}/episodes`]: () =>
        ok({ items: [{ id: "e1", agent_id: "tutor", status: "running", progress: 0.5, created_at: "2026-11-01T00:00:00Z" }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));

    expect(await screen.findByText("Brittany")).toBeInTheDocument();
    expect(screen.getByText(/50%/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("cancels a running episode via POST without opening the detail panel", async () => {
    const fn = makeFetch({
      ...agentsFixture(),
      [`${API}/episodes`]: () =>
        ok({ items: [{ id: "e1", agent_id: "tutor", status: "running", progress: 0.5 }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(`${API}/episodes/e1/cancel`, expect.objectContaining({ method: "POST" }));
    });
    // Cancelling invokes the button handler only; the row click (stopPropagation)
    // must not open the episode detail panel.
    expect(screen.queryByText("Activity detail")).not.toBeInTheDocument();
  });

  it("does not show controls for non-running episodes", async () => {
    globalThis.fetch = makeFetch({
      ...agentsFixture(),
      [`${API}/episodes`]: () =>
        ok({ items: [{ id: "e1", agent_id: "tutor", status: "done", progress: 1 }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    await screen.findByText("Brittany");
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("opens episode detail with its events when a row is clicked", async () => {
    globalThis.fetch = makeFetch({
      ...agentsFixture(),
      [`${API}/episodes`]: () =>
        ok({ items: [{ id: "e1", agent_id: "tutor", status: "running", progress: 0.5, created_at: "2026-11-01T00:00:00Z" }] }),
      [`${API}/episodes/e1`]: () =>
        ok({
          episode: { id: "e1", agent_id: "tutor", status: "running", progress: 0.5, created_at: "2026-11-01T00:00:00Z" },
          events: [
            { status: "started", detail: "dispatched", created_at: "2026-11-01T00:00:01Z" },
            { status: "checkpoint", detail: "40%", created_at: "2026-11-01T00:00:05Z" },
          ],
        }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    fireEvent.click(await screen.findByText("Brittany"));

    expect(await screen.findByText("Activity detail")).toBeInTheDocument();
    expect(await screen.findByText("Started")).toBeInTheDocument();
    expect(screen.getByText("Checkpoint")).toBeInTheDocument();
    expect(screen.getByText("dispatched")).toBeInTheDocument();
  });
});

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

describe("Execution tracking (M10 D2)", () => {
  const workFixture = (over: Record<string, Route> = {}) => ({
    [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
    [`${API}/workspaces/goals`]: () => ok({ items: [{ id: "g1", title: "Ship v1", project_id: "p1", status: "open" }] }),
    [`${API}/workspaces/assignments`]: () => ok({ items: [{ id: "a1", goal_id: "g1", agent_id: "tutor", status: "queued" }] }),
    [`${API}/workspaces/deliverables`]: () => ok({ items: [] }),
    ...over,
  });

  it("starts tracking from the Work tab using the assigned agent", async () => {
    const fn = makeFetch(workFixture({
      [`${API}/work/goal/g1/execute`]: () => ok({ episode_id: "ep1", status: "running", already_active: false, work_type: "goal", work_id: "g1", agent_id: "tutor" }),
    }));
    globalThis.fetch = fn as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click((await screen.findAllByText("Ship v1"))[0]); // goals list row (first "Ship v1" in DOM)
    fireEvent.click(await screen.findByTestId("track-g1"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/goal/g1/execute`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ agent_id: "tutor" }) })
      );
    });
    expect(await screen.findByText("Tracking")).toBeInTheDocument();
  });

  it("records an evidence-gated checkpoint from Activity", async () => {
    const fn = makeFetch({
      [`${API}/episodes`]: () => ok({ items: [{ id: "e1", agent_id: "tutor", status: "running", progress: 0, created_at: "2026-11-01T00:00:00Z" }] }),
      [`${API}/episodes/e1`]: () => ok({ episode: { id: "e1", agent_id: "tutor", status: "running", progress: 0 }, events: [] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    fireEvent.click(await screen.findByText(/Tutor/));
    await screen.findByTestId("checkpoint-btn");
    fireEvent.change(screen.getByLabelText("Evidence summary"), { target: { value: "milestone reached" } });
    fireEvent.click(screen.getByTestId("checkpoint-btn"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/episodes/e1/checkpoint`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ progress: 0.5, evidence: { summary: "milestone reached" } }),
        })
      );
    });
  });

  it("does not post a checkpoint with empty evidence", async () => {
    const fn = makeFetch({
      [`${API}/episodes`]: () => ok({ items: [{ id: "e1", agent_id: "tutor", status: "running", progress: 0, created_at: "2026-11-01T00:00:00Z" }] }),
      [`${API}/episodes/e1`]: () => ok({ episode: { id: "e1", agent_id: "tutor", status: "running", progress: 0 }, events: [] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    fireEvent.click(await screen.findByText(/Tutor/));
    fireEvent.click(await screen.findByTestId("checkpoint-btn"));
    expect(fn).not.toHaveBeenCalledWith(
      `${API}/episodes/e1/checkpoint`,
      expect.objectContaining({ method: "POST" })
    );
    expect(await screen.findByTestId("ep-error")).toBeInTheDocument();
  });

  it("completes an episode with validation evidence from Activity", async () => {
    const fn = makeFetch({
      [`${API}/episodes`]: () => ok({ items: [{ id: "e1", agent_id: "tutor", status: "running", progress: 0, created_at: "2026-11-01T00:00:00Z" }] }),
      [`${API}/episodes/e1`]: () => ok({ episode: { id: "e1", agent_id: "tutor", status: "running", progress: 0 }, events: [] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    fireEvent.click(await screen.findByText(/Tutor/));
    await screen.findByTestId("complete-btn");
    fireEvent.change(screen.getByLabelText("Completion evidence"), { target: { value: "work verified done" } });
    fireEvent.click(screen.getByTestId("complete-btn"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/episodes/e1/complete`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ evidence: { summary: "work verified done" } }),
        })
      );
    });
  });
});

describe("Evidence application & execution history (M10 D3)", () => {
  const epFixture = (episode: any, events: any[] = []) => ({
    [`${API}/episodes`]: () => ok({ items: [{ id: episode.id, agent_id: episode.agent_id, status: episode.status, progress: episode.progress, applied_at: episode.applied_at, created_at: "2026-11-01T00:00:00Z" }] }),
    [`${API}/episodes/${episode.id}`]: () => ok({ episode, events }),
  });

  it("applies a completed episode to its goal via confirmation", async () => {
    const fn = makeFetch(epFixture({ id: "e1", agent_id: "tutor", status: "done", progress: 1, applied_at: null }));
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    fireEvent.click(await screen.findByText(/Tutor/));
    await screen.findByTestId("apply-btn");
    fireEvent.click(screen.getByTestId("apply-btn"));
    fireEvent.click(await screen.findByTestId("confirm-apply"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(`${API}/episodes/e1/apply`, expect.objectContaining({ method: "POST" }));
    });
  });

  it("does not offer apply for an already-applied episode", async () => {
    globalThis.fetch = makeFetch(epFixture({ id: "e1", agent_id: "tutor", status: "done", progress: 1, applied_at: "2026-11-01T00:00:00Z", applied_by: "u1" })) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    fireEvent.click(await screen.findByText(/Tutor/));
    expect(await screen.findByTestId("episode-applied")).toBeInTheDocument();
    expect(screen.queryByTestId("apply-btn")).not.toBeInTheDocument();
  });

  it("shows execution history in the goal detail panel", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
      [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", workspace_id: "w1" }] }),
      [`${API}/workspaces/goals`]: () => ok({ items: [{ id: "g1", title: "Ship v1", project_id: "p1", status: "in_progress" }] }),
      [`${API}/workspaces/assignments`]: () => ok({ items: [] }),
      [`${API}/workspaces/deliverables`]: () => ok({ items: [] }),
      [`${API}/work/goal/g1/execution`]: () => ok({ work_type: "goal", work_id: "g1", episodes: [{ episode_id: "ep9", agent_id: "tutor", status: "done", progress: 1, evidence_summary: "ship verified", applied_at: "2026-11-01T00:00:00Z", applied_by: "u1" }] }),
    }) as any;
    render(<App />);
    await openWorkProject();
    fireEvent.click((await screen.findAllByText("Ship v1"))[0]);
    const panel = await screen.findByTestId("exec-g1");
    expect(panel).toBeInTheDocument();
    expect(screen.getByText("ship verified")).toBeInTheDocument();
    expect(screen.getByText("Applied")).toBeInTheDocument();
  });
});

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
    expect(link.textContent).toContain("Open coordination");
    fireEvent.click(link);
    expect(await screen.findByTestId("coordination-panel")).toBeInTheDocument();
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

describe("Coordination panel (component)", () => {
  const GOAL = {
    id: "g1", title: "Launch", coordinator_agent: "workspace_architect",
    status: "approved",
  };
  const PLAN_STEPS = [
    { seq: 1, agent_id: "workspace_architect", responsibility: "Draft brief",
      depends_on_seq: null, capability_ok: true, delegation_ok: true, valid: true,
      error: null, status: "pending", effective_permissions: ["work:propose:goal"] },
    { seq: 2, agent_id: "strategist", responsibility: "Refine brief",
      depends_on_seq: 1, capability_ok: true, delegation_ok: true, valid: true,
      error: null, status: "pending", effective_permissions: ["work:propose:goal"] },
  ];
  const REVIEW = {
    team_goal_id: "g1", coordinator: "workspace_architect", steps: PLAN_STEPS,
    plan_valid: true, errors: [], warnings: [], transient: true,
  };
  const PLAN = {
    plan_id: "p1", team_goal_id: "g1", goal_id: null,
    coordinator: "workspace_architect", expected_deliverable: "Launch brief",
    status: "authorized", steps: PLAN_STEPS, reused: false,
  };

  function execSummary(s: any) {
    return {
      execution_id: s.executionId, plan_id: "p1", team_goal_id: "g1",
      status: s.runStatus,
      steps: s.steps.map((st: any) => ({
        seq: st.seq, status: st.status, error: null,
        has_evidence: st.status !== "pending",
      })),
      deliverable: s.deliverable,
    };
  }

  function nextEligible(s: any) {
    const sorted: any[] = [...s.steps].sort((a: any, b: any) => a.seq - b.seq);
    for (const step of sorted) {
      if (["awaiting_review", "in_progress", "accepted", "rejected"].includes(step.status)) continue;
      const dep = PLAN_STEPS.find((p) => p.seq === step.seq)!.depends_on_seq;
      if (dep != null) {
        const d = s.steps.find((x: any) => x.seq === dep);
        if (!d || d.status !== "accepted") continue;
      }
      return step;
    }
    return null;
  }

  function dependentClosure(s: any, targets: number[]): number[] {
    const deps: Record<number, number | null> = { 1: null, 2: 1 };
    const closure = new Set(targets);
    let changed = true;
    while (changed) {
      changed = false;
      for (const [seq, dep] of Object.entries(deps)) {
        if (dep != null && closure.has(dep) && !closure.has(Number(seq))) {
          closure.add(Number(seq)); changed = true;
        }
      }
    }
    return [...closure].sort((a, b) => a - b);
  }

  // State-machine fetch stub simulating the T2-C-3/4/5 backend for one goal.
  function coordBackend() {
    const s: any = {
      runStatus: "", executionId: "e1", steps: [], deliverable: null, versions: [],
    };
    const fn = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      const body = init?.body ? JSON.parse(init.body) : {};
      if (method === "GET" && url.endsWith("/team/goals")) return ok({ items: [GOAL] });
      if (method === "GET" && url.endsWith("/coordination-plan")) return ok(REVIEW);
      if (method === "POST" && url.endsWith("/coordination-plan/authorize")) return ok(PLAN);
      if (method === "POST" && url.endsWith("/execution/initiate")) {
        s.runStatus = "running";
        s.steps = PLAN_STEPS.map((p) => ({ seq: p.seq, status: "pending" }));
        s.deliverable = null; s.versions = [];
        return ok({ execution_id: s.executionId, plan_id: "p1", team_goal_id: "g1", status: "running", reused: false });
      }
      if (method === "POST" && url.endsWith("/run")) {
        // Autonomous run: all eligible steps run + auto-accept, then aggregate.
        s.steps.forEach((st: any) => { st.status = "accepted"; });
        s.runStatus = "ready_for_review";
        s.deliverable = {
          deliverable_id: "d1", execution_id: s.executionId, title: "Launch brief",
          content: { expected_deliverable: "Launch brief", steps: [] },
          status: "pending", review_note: null, reused: false,
        };
        s.versions = [{
          version_id: "v1", deliverable_id: "d1", execution_id: s.executionId,
          version: 1, content: s.deliverable.content, status: "pending",
          review_note: null, revision_of: null,
          created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
        }];
        return ok({ execution_id: s.executionId, all_accepted: true,
                    run_status: "ready_for_review", deliverable: s.deliverable });
      }
      if (method === "POST" && url.endsWith("/step/execute")) {
        const el = nextEligible(s);
        if (!el) return fail({ detail: "no eligible step" }, 409);
        s.steps.find((x: any) => x.seq === el.seq)!.status = "awaiting_review";
        return ok({ execution_id: s.executionId, step: el.seq, status: "awaiting_review" });
      }
      const stepReview = url.match(/\/step\/(\d+)\/review$/);
      if (method === "POST" && stepReview) {
        const seq = Number(stepReview[1]);
        s.steps.find((x: any) => x.seq === seq)!.status = body.decision;
        if (body.decision === "accepted" && s.steps.every((x: any) => x.status === "accepted")) {
          s.runStatus = "ready_for_review";
        }
        return ok({ execution_id: s.executionId, step: seq, decision: body.decision, run_status: s.runStatus });
      }
      if (method === "POST" && url.endsWith("/aggregate")) {
        s.deliverable = {
          deliverable_id: "d1", execution_id: s.executionId, title: "Launch brief",
          content: { expected_deliverable: "Launch brief", steps: [] },
          status: "pending", review_note: null, reused: false,
        };
        s.versions = [{
          version_id: "v1", deliverable_id: "d1", execution_id: s.executionId,
          version: 1, content: s.deliverable.content, status: "pending",
          review_note: null, revision_of: null,
          created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
        }];
        return ok(s.deliverable);
      }
      if (method === "POST" && url.endsWith("/deliverable/review")) {
        if (body.decision === "revision_requested") {
          const closure = dependentClosure(s, (body.rework_steps || []).map(Number));
          s.steps.forEach((st: any) => { if (closure.includes(st.seq)) st.status = "revision_requested"; });
          s.deliverable.status = "revision_requested"; s.runStatus = "running";
          return ok({ execution_id: s.executionId, decision: "revision_requested", run_status: "running", steps: closure, version_id: "v1", version: 1 });
        }
        if (body.decision === "accepted") {
          s.deliverable.status = "approved"; s.runStatus = "completed";
          return ok({ execution_id: s.executionId, decision: "accepted", run_status: "completed", version_id: "v1", version: 1, approval: [] });
        }
        if (body.decision === "rejected") {
          s.deliverable.status = "rejected"; s.runStatus = "rejected";
          return ok({ execution_id: s.executionId, decision: "rejected", run_status: "rejected", version_id: "v1", version: 1, approval: [] });
        }
        return fail({ detail: "bad decision" }, 422);
      }
      if (method === "GET" && /\/deliverable\/versions\/[^/]+$/.test(url)) {
        const vid = url.split("/").pop();
        const v = s.versions.find((x: any) => x.version_id === vid);
        return v ? ok(v) : fail({ detail: "version not found" }, 404);
      }
      if (method === "GET" && url.endsWith("/deliverable/versions")) {
        return ok({ execution_id: s.executionId, versions: s.versions });
      }
      if (method === "GET" && url.includes(`/execution/${s.executionId}`)) {
        return ok(execSummary(s));
      }
      return ok({ items: [] });
    });
    return fn;
  }

  async function openToExecution() {
    render(<Coordination />);
    fireEvent.click(await screen.findByTestId("coord-goal-g1"));
    fireEvent.click(await screen.findByTestId("coord-authorize"));
    fireEvent.click(await screen.findByTestId("coord-start-exec"));
  }

  // Wait for a button to become clickable (it may be temporarily disabled by an
  // in-flight async reload) and then click it.
  async function clickEnabled(testId: string) {
    await screen.findByTestId(testId);
    await waitFor(() => expect(screen.getByTestId(testId)).toBeEnabled());
    fireEvent.click(screen.getByTestId(testId));
  }

  it("runs every eligible step autonomously and reaches deliverable review", async () => {
    globalThis.fetch = coordBackend() as any;
    await openToExecution();
    await runAll();
    // No per-step review controls appear — steps auto-accept.
    expect(screen.queryByTestId("coord-accept-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coord-revise-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coord-reject-1")).not.toBeInTheDocument();
    // The deliverable (final review) is the human gate.
    expect(screen.getByTestId("coord-deliv")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^coord-step-/).length).toBe(2);
  });

  it("offers a single Run control, not per-step execute", async () => {
    globalThis.fetch = coordBackend() as any;
    await openToExecution();
    // One autonomous action replaces per-step execution.
    expect(await screen.findByTestId("coord-run")).toBeInTheDocument();
    expect(screen.queryByTestId("coord-exec-next")).not.toBeInTheDocument();
  });

  it("approves a proposed goal inline, then authorizes the plan", async () => {
    let goalStatus = "proposed";
    globalThis.fetch = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      if (method === "GET" && url.endsWith("/team/goals")) {
        return ok({ items: [{ ...GOAL, status: goalStatus }] });
      }
      if (method === "GET" && url.endsWith("/coordination-plan")) {
        return goalStatus === "proposed"
          ? fail({ detail: "not eligible" }, 422)
          : ok(REVIEW);
      }
      if (method === "POST" && url.endsWith(`/team/goals/${GOAL.id}/approve`)) {
        goalStatus = "approved";
        return ok({ status: "approved" });
      }
      return ok({ items: [] });
    }) as any;
    render(<Coordination />);
    fireEvent.click(await screen.findByTestId("coord-goal-g1"));
    // A proposed goal now exposes an inline Approve, so the flow is reachable
    // right here instead of only in the buried Review Center.
    const approve = await screen.findByTestId("coord-approve");
    expect(approve).toBeInTheDocument();
    fireEvent.click(approve);
    // Approving reveals the plan preview + Authorize control in the same panel.
    await screen.findByTestId("coord-authorize");
    expect(screen.queryByTestId("coord-approve")).not.toBeInTheDocument();
  });

  async function runAll() {
    await clickEnabled("coord-run");
    await screen.findByTestId("coord-deliv");
  }

  it("accepts the consolidated deliverable and completes the run", async () => {
    globalThis.fetch = coordBackend() as any;
    await openToExecution();
    await runAll();
    await clickEnabled("coord-accept"); // deliverable accept button
    await waitFor(() =>
      expect(screen.getByTestId("coord-exec").textContent).toContain("Completed"));
  });

  it("requests a deliverable revision and autonomously re-runs rework", async () => {
    globalThis.fetch = coordBackend() as any;
    await openToExecution();
    await runAll();
    await screen.findByTestId("coord-rework-1");
    fireEvent.click(screen.getByTestId("coord-rework-1")); // select step 1 to rework
    await clickEnabled("coord-revision");
    // Revision is recorded, then the affected steps re-run autonomously and the
    // deliverable returns to your review gate.
    await waitFor(() => expect(screen.getByTestId("coord-accept")).toBeEnabled());
  });

  it("rejects the deliverable into a terminal run state", async () => {
    globalThis.fetch = coordBackend() as any;
    await openToExecution();
    await runAll();
    await clickEnabled("coord-reject");
    await waitFor(() =>
      expect(screen.getByTestId("coord-exec").textContent).toContain("Rejected"));
  });

  it("renders immutable deliverable version history and version detail", async () => {
    globalThis.fetch = coordBackend() as any;
    await openToExecution();
    await runAll();
    const versionBtn = await screen.findByTestId("coord-version-v1");
    expect(versionBtn.textContent).toContain("v1");
    fireEvent.click(versionBtn);
    const detail = await screen.findByTestId("coord-version-detail");
    expect(detail.textContent).toContain("Launch brief");
  });
});

describe("Coordination authoring form (component)", () => {
  // Minimal backend stub simulating the propose + project-goal picker endpoints.
  function coordAuthorBackend() {
    const state: any = { goals: [], gid: 0 };
    const fn = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      const body = init?.body ? JSON.parse(init.body) : {};
      if (method === "GET" && url.endsWith("/team/goals")) return ok({ items: state.goals });
      if (method === "GET" && url.endsWith("/workspaces/goals")) {
        return ok({ items: [{ id: "g1", title: "Launch", priority: 1 }] });
      }
      if (method === "POST" && url.endsWith("/team/goals")) {
        state.gid += 1;
        const created = { id: `tg${state.gid}`, title: body.title,
          coordinator_agent: body.coordinator_agent, status: "proposed" };
        state.goals.push(created);
        return ok({ team_goal_id: created.id, status: "proposed", reused: false });
      }
      return ok({ items: [] });
    });
    return fn;
  }

  function openForm() {
    render(<Coordination />);
    fireEvent.click(screen.getByTestId("coord-new-goal"));
    return screen.getByTestId("coord-create");
  }

  async function fillRequired() {
    const picker = screen.getByTestId("coord-goal-picker");
    fireEvent.change(picker, { target: { value: "g1" } });
    fireEvent.change(screen.getByTestId("coord-form-title"), { target: { value: "Launch brief" } });
  }

  it("opens the authoring form and lists project goals", async () => {
    globalThis.fetch = coordAuthorBackend() as any;
    await openForm();
    const picker = screen.getByTestId("coord-goal-picker");
    await waitFor(() =>
      expect(within(picker).getAllByRole("option").map((o) => o.getAttribute("value")))
        .toContain("g1"));
    expect(within(picker).getByRole("option", { name: "Launch" })).toBeInTheDocument();
    expect(screen.getByTestId("coord-form-coordinator")).toBeInTheDocument();
  });

  it("validates required inputs before proposing", async () => {
    globalThis.fetch = coordAuthorBackend() as any;
    await openForm();
    // no title, no project goal selected -> blocked client-side
    fireEvent.click(screen.getByTestId("coord-propose"));
    await screen.findByText(/A title is required/);
    expect(screen.getByTestId("coord-create")).toBeInTheDocument();
  });

  it("proposes a team goal, shows proposed status, and refreshes the list", async () => {
    globalThis.fetch = coordAuthorBackend() as any;
    await openForm();
    await waitFor(() =>
      expect(within(screen.getByTestId("coord-goal-picker")).getByRole("option", { name: "Launch" }))
        .toBeInTheDocument());
    await fillRequired();
    fireEvent.click(screen.getByTestId("coord-propose"));

    await screen.findByText(/Approval is a separate human step/);
    await waitFor(() => expect(screen.queryByTestId("coord-create")).not.toBeInTheDocument());
    // proposed status is visible and the goal list refreshed with the new goal
    await screen.findByTestId("coord-goal-tg1");
    expect(screen.getByTestId("coord-goal-tg1").textContent).toContain("proposed");
  });

  it("adds and removes ordered steps and selects a dependency", async () => {
    globalThis.fetch = coordAuthorBackend() as any;
    await openForm();
    await screen.findByTestId("coord-step-editor-1");
    fireEvent.click(screen.getByTestId("coord-add-step"));
    const editor2 = await screen.findByTestId("coord-step-editor-2");
    expect(within(editor2).getByRole("option", { name: "after #1" })).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("coord-step-dep-2"), { target: { value: "1" } });
    expect(screen.getByTestId("coord-step-dep-2").value).toBe("1");
    // removing a step collapses the sequence back to one editor
    fireEvent.click(screen.getByTestId("coord-step-remove-2"));
    await waitFor(() => expect(screen.queryByTestId("coord-step-editor-2")).not.toBeInTheDocument());
    expect(screen.getByTestId("coord-step-editor-1")).toBeInTheDocument();
  });

  it("surfaces a backend validation error from propose", async () => {
    const fn = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      if (method === "GET" && url.endsWith("/team/goals")) return ok({ items: [] });
      if (method === "GET" && url.endsWith("/workspaces/goals")) {
        return ok({ items: [{ id: "g1", title: "Launch" }] });
      }
      if (method === "POST" && url.endsWith("/team/goals")) {
        return fail({ detail: "unknown coordinator agent" }, 422);
      }
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    await openForm();
    await waitFor(() => expect(within(screen.getByTestId("coord-goal-picker")).getByRole("option", { name: "Launch" })).toBeInTheDocument());
    await fillRequired();
    fireEvent.click(screen.getByTestId("coord-propose"));
    await screen.findByText(/unknown coordinator agent/);
  });

  it("generates an editable draft from a conversation message", async () => {
    const fn = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      if (method === "GET" && url.endsWith("/team/goals")) return ok({ items: [] });
      if (method === "GET" && url.endsWith("/workspaces/goals")) {
        return ok({ items: [{ id: "g1", title: "Launch" }] });
      }
      if (method === "POST" && url.endsWith("/team/goals/draft")) {
        return ok({
          title: "Launch strategy", summary: "research", expected_deliverable: "one-page plan",
          coordinator_agent: "workspace_architect",
          steps: [
            { seq: 1, agent_id: "strategist", responsibility: "research", depends_on_seq: null },
            { seq: 2, agent_id: "tutor", responsibility: "explain", depends_on_seq: 1 },
          ],
        });
      }
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    await openForm();
    fireEvent.change(screen.getByTestId("coord-draft-message"),
      { target: { value: "- strategist: research\n- tutor: explain" } });
    fireEvent.click(screen.getByTestId("coord-draft-gen"));
    await waitFor(() => expect(screen.getByTestId("coord-form-title")).toHaveValue("Launch strategy"));
    expect(screen.getByTestId("coord-form-deliverable")).toHaveValue("one-page plan");
    expect(screen.getByTestId("coord-form-coordinator").value).toBe("workspace_architect");
    // draft pre-fills two editable steps -- and does NOT propose/close the form
    await screen.findByTestId("coord-step-editor-2");
    expect(screen.getByTestId("coord-create")).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalledWith(expect.stringMatching(/\/team\/goals$/), expect.anything());
  });
});

describe("Review & Action Center (component)", () => {
  function reviewBackend(initial: any, onApprove?: () => void) {
    let state = initial;
    const fn = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      if (method === "GET" && url.endsWith("/team/review")) return ok(state);
      if (method === "POST" && url.includes("/approve")) {
        if (onApprove) onApprove();
        return ok({ status: "approved" });
      }
      return ok({ items: [], counts: {} });
    });
    return fn;
  }

  it("shows an empty state when nothing needs attention", async () => {
    globalThis.fetch = reviewBackend({ items: [], counts: {} }) as any;
    render(<ReviewCenter />);
    await screen.findByTestId("review-empty");
    expect(screen.getByTestId("review-center")).toBeInTheDocument();
  });

  it("renders sections and items from the aggregate", async () => {
    globalThis.fetch = reviewBackend({
      items: [
        { type: "goal_approval", goal_id: "tg1", title: "Launch", coordinator_agent: "workspace_architect" },
        { type: "step_review", execution_id: "e1", plan_id: "p1", goal_id: "tg1", goal_title: "Launch", seq: 1, agent_id: "strategist" },
      ],
      counts: { goal_approval: 1, step_review: 1 },
    }) as any;
    render(<ReviewCenter />);
    await screen.findByTestId("review-section-goal_approval");
    await screen.findByTestId("review-section-step_review");
    expect(screen.getAllByTestId("review-item-goal_approval")).toHaveLength(1);
    expect(screen.getAllByTestId("review-item-step_review")).toHaveLength(1);
  });

  it("approves a proposed goal inline and reloads", async () => {
    let state: any = { items: [{ type: "goal_approval", goal_id: "tg1", title: "Launch" }], counts: { goal_approval: 1 } };
    globalThis.fetch = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      if (method === "GET" && url.endsWith("/team/review")) return ok(state);
      if (method === "POST" && url.endsWith("/tg1/approve")) {
        state = { items: [], counts: {} };  // approve removes the item
        return ok({ status: "approved" });
      }
      return ok({ items: [], counts: {} });
    }) as any;
    render(<ReviewCenter />);
    await screen.findByTestId("review-section-goal_approval");
    fireEvent.click(screen.getByTestId("review-approve"));
    await screen.findByTestId("review-empty");
  });

  it("dismisses a review item via POST and reloads the list", async () => {
    let state: any = {
      items: [{ type: "goal_approval", goal_id: "tg1", title: "Launch", key: "goal:tg1" }],
      counts: { goal_approval: 1 },
    };
    const dismissCalls: string[] = [];
    globalThis.fetch = vi.fn(async (url: string, init?: any) => {
      const method = (init?.method || "GET").toUpperCase();
      if (method === "GET" && url.endsWith("/team/review")) return ok(state);
      if (method === "POST" && url.endsWith("/team/review/dismiss")) {
        dismissCalls.push(url);
        state = { items: [], counts: {} }; // dismissal removes it from the list
        return ok({ dismissed: true });
      }
      return ok({ items: [], counts: {} });
    }) as any;
    render(<ReviewCenter />);
    await screen.findByTestId("review-section-goal_approval");
    fireEvent.click(screen.getByTestId("review-dismiss-goal_approval"));
    await screen.findByTestId("review-empty");
    expect(dismissCalls.length).toBeGreaterThan(0);
  });

  it("renders a blocked_communication section with from\u2192to metadata", async () => {
    globalThis.fetch = reviewBackend({
      items: [{
        type: "blocked_communication",
        id: "cm1",
        from_agent: "strategist",
        to_agent: "tutor",
        content: "ask tutor for sources",
        message: "depth limit reached",
        depth: 3,
      }],
      counts: { blocked_communication: 1 },
    }) as any;
    render(<ReviewCenter />);
    await screen.findByTestId("review-section-blocked_communication");
    const row = screen.getByTestId("review-row-blocked_communication");
    expect(row).toBeInTheDocument();
    // from → to subtitle and the error/explanation message are shown.
    expect(row.textContent).toContain("→");
    expect(row.textContent).toMatch(/depth limit reached/);
  });

  it("routes an 'Open in AI Team' action to onOpen", async () => {
    let opened: string | undefined;
    globalThis.fetch = reviewBackend({
      items: [{ type: "plan_authorization", goal_id: "tg9", title: "Auth Me" }],
      counts: { plan_authorization: 1 },
    }) as any;
    render(<ReviewCenter onOpen={(id?: string) => { opened = id; }} />);
    await screen.findByTestId("review-row-plan_authorization");
    fireEvent.click(screen.getByTestId("review-open"));
    expect(opened).toBe("tg9");
  });
});

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

  it("extracts a project draft and files it as a proposal for approval", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    const fn = vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/workspaces")) return ok({ items: [{ id: "w1", name: "Acme" }] });
      if (url.endsWith("/workspaces/projects")) return ok({ items: [] });
      if (url.endsWith("/workspaces/goals")) return ok({ items: [] });
      if (url.endsWith("/work/extract")) return ok({ kind: "project", draft: { kind: "project", title: "Launch a mobile app", description: null }, persisted: false });
      if (url.endsWith("/work/proposals")) return ok({ ok: true });
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-input");
    fireEvent.click(screen.getByTestId("mode-propose"));
    fireEvent.change(screen.getByTestId("team-chat-input"), { target: { value: "project: Launch a mobile app" } });
    fireEvent.click(screen.getByTestId("prop-extract"));
    await screen.findByTestId("prop-title");
    expect(screen.getByTestId("prop-title").value).toBe("Launch a mobile app");
    fireEvent.change(screen.getByTestId("prop-parent"), { target: { value: "w1" } });
    fireEvent.click(screen.getByTestId("prop-file"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0].endsWith("/work/proposals"));
      expect(call).toBeTruthy();
      const body = JSON.parse(call![1].body);
      expect(body.work_type).toBe("project");
      expect(body.payload.workspace_id).toBe("w1");
      // Task Center ↔ group-chat linkage: proposal carries the source thread.
      expect(body.thread_id).toBe("team-1");
    });
    expect(screen.getByTestId("prop-msg").textContent).toMatch(/Proposal created/);
  });

  it("auto-creates a workspace when proposing a project with no parent selected", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    const fn = vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/workspaces") && init?.method === "POST") return ok({ id: "w9" });
      if (url.endsWith("/workspaces")) return ok({ items: [] });
      if (url.endsWith("/workspaces/projects")) return ok({ items: [] });
      if (url.endsWith("/workspaces/goals")) return ok({ items: [] });
      if (url.endsWith("/work/extract")) return ok({ kind: "project", draft: { kind: "project", title: "Build a product", description: null }, persisted: false });
      if (url.endsWith("/work/proposals")) return ok({ ok: true });
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-input");
    fireEvent.click(screen.getByTestId("mode-propose"));
    fireEvent.change(screen.getByTestId("team-chat-input"), { target: { value: "project: Build a product" } });
    fireEvent.click(screen.getByTestId("team-chat-propose"));
    await screen.findByTestId("prop-title");
    // No parent chosen -> proposing files the project under an auto-created workspace.
    fireEvent.click(screen.getByTestId("prop-file"));
    await waitFor(() => {
      const wsCall = fn.mock.calls.find((c: any) => c[0].endsWith("/workspaces") && c[1]?.method === "POST");
      expect(wsCall).toBeTruthy();
      const prop = fn.mock.calls.find((c: any) => c[0].endsWith("/work/proposals") && c[1]?.method === "POST");
      expect(prop).toBeTruthy();
      expect(JSON.parse(prop![1].body).payload.workspace_id).toBe("w9");
    });
  });

  it("proposes a plan to /team/plans with milestones and deliverables", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    const fn = vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/work/extract")) return ok({ kind: "plan", draft: { kind: "plan", title: "Launch", milestones: [{ title: "Phase 1" }], tasks: [{ title: "Research", agent: "strategist", milestone_index: 0 }], deliverables: [{ title: "Brief" }] }, persisted: false });
      if (url.endsWith("/team/plans")) return ok({ proposal_id: "pl1", status: "proposed" });
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-input");
    fireEvent.click(screen.getByTestId("mode-propose"));
    fireEvent.change(screen.getByTestId("prop-kind"), { target: { value: "plan" } });
    fireEvent.change(screen.getByTestId("team-chat-input"), { target: { value: "plan: Launch" } });
    fireEvent.click(screen.getByTestId("team-chat-propose"));
    await screen.findByTestId("prop-title");
    fireEvent.click(screen.getByTestId("prop-file"));
    await waitFor(() => {
      const call = fn.mock.calls.find((c: any) => c[0].endsWith("/team/plans") && c[1]?.method === "POST");
      expect(call).toBeTruthy();
      const body = JSON.parse(call![1].body);
      expect(body.milestones[0].title).toBe("Phase 1");
      expect(body.tasks[0].agent).toBe("strategist");
      expect(body.deliverables[0].title).toBe("Brief");
    });
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

  it("delegates a message into a proposed TeamGoal (approve/authorize/run stay separate)", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    const fn = vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/team/goals/draft")) {
        return ok({
          title: "Launch plan", coordinator_agent: "workspace_architect",
          summary: null, expected_deliverable: "Launch brief",
          steps: [{ seq: 1, agent_id: "strategist", responsibility: "Research the Bay Area", depends_on_seq: null }],
        });
      }
      if (url.endsWith("/team/goals/validate")) {
        return ok({
          coordinator: "workspace_architect",
          steps: [{ seq: 1, agent_id: "strategist", responsibility: "Research the Bay Area",
            capability_ok: true, delegation_ok: true, valid: true, error: null }],
          plan_valid: true, errors: [],
        });
      }
      if (url.endsWith("/team/goals") && init?.method === "POST") {
        return ok({ team_goal_id: "tg-d", status: "proposed", reused: false });
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
    expect(msg.textContent).toContain("proposed");
    expect(screen.getByTestId("delegate-draft").textContent).toContain("Launch plan");
    // Intent only: delegation must NOT approve, authorize a plan, or run.
    const urls = fn.mock.calls.map((c: any) => c[0] || "");
    expect(urls.some((u: string) => u.includes("/approve"))).toBe(false);
    expect(urls.some((u: string) => u.includes("/coordination-plan/authorize"))).toBe(false);
    expect(urls.some((u: string) => u.endsWith("/run"))).toBe(false);
  });

  it("auto-reassigns an invalid delegated step to a capable agent before proposing", async () => {
    localStorage.removeItem("ai-team-shared-thread");
    let proposedSteps: any = null;
    const fn = vi.fn(async (url: string, init?: any) => {
      if (url.endsWith("/team/threads")) return ok({ thread_id: "team-1" });
      if (url.includes("/memory/conversation?")) return ok({ items: [] });
      if (url.endsWith("/team/goals/draft")) {
        return ok({
          title: "Launch plan", coordinator_agent: "workspace_architect",
          summary: null, expected_deliverable: "Launch brief",
          steps: [{ seq: 1, agent_id: "communications", responsibility: "Prioritize the launch", depends_on_seq: null }],
        });
      }
      if (url.endsWith("/team/goals/validate")) {
        // communications undeclared -> suggest strategist (capable + delegable).
        return ok({
          coordinator: "workspace_architect",
          steps: [{ seq: 1, agent_id: "communications", responsibility: "Prioritize the launch",
            capability_ok: false, delegation_ok: false, valid: false,
            error: "step 1: delegation not authorized",
            valid_agent_ids: ["strategist"], suggested_agent_id: "strategist" }],
          plan_valid: false, errors: ["step 1: delegation not authorized"],
        });
      }
      if (url.endsWith("/team/goals") && init?.method === "POST") {
        proposedSteps = JSON.parse(init.body).steps;
        return ok({ team_goal_id: "tg-d", status: "proposed", reused: false });
      }
      return ok({ items: [] });
    });
    globalThis.fetch = fn as any;
    render(<TeamChat />);
    await screen.findByTestId("team-chat-input");
    fireEvent.click(screen.getByTestId("mode-delegate"));
    fireEvent.change(screen.getByTestId("team-chat-input"), { target: { value: "goal: Launch the plan" } });
    fireEvent.click(screen.getByTestId("team-chat-delegate"));
    const msg = await screen.findByTestId("delegate-msg");
    expect(msg.textContent).toContain("proposed");
    expect(msg.textContent).toMatch(/auto-assigned/i);
    // Proposed step was reassigned to the suggested capable agent.
    expect(proposedSteps).toBeTruthy();
    expect(proposedSteps[0].agent_id).toBe("strategist");
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
