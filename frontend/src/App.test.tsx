import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import App from "./App";

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
    // default: empty lists
    return ok({ items: [] });
  });
  return fn;
}

// Drive the Work view into the "Acme" workspace / "Launch" project used by
// the fixtures below, waiting for the async workspace/project data to arrive.
async function openWorkProject() {
  fireEvent.click(screen.getByRole("button", { name: "Work" }));
  await screen.findByRole("option", { name: "Acme" });
  fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: "w1" } });
  await screen.findByRole("option", { name: "Launch" });
  fireEvent.change(screen.getByLabelText("Project"), { target: { value: "p1" } });
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
      ["overview", "Overview"],
      ["workspace", "Workspaces"],
      ["work", "Work"],
      ["episodes", "Activity"],
      ["agents", "Agents"],
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
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));

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
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
    expect(await screen.findByText("Acme")).toBeInTheDocument();
  });

  it("disables create when offline", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("offline"))) as any;
    render(<App />);
    await screen.findByText(/read-only/);
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
    fireEvent.click(await screen.findByText("Acme"));
    expect(await screen.findByText(/Launch/)).toBeInTheDocument();
    expect(screen.getByText(/Active/)).toBeInTheDocument();
  });

  it("creates a project against the selected workspace", async () => {
    const fn = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
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
    expect(await screen.findByText(/summary of your AI team/i)).toBeInTheDocument();
    expect(screen.getAllByText("Open goals").length).toBeGreaterThan(0);
    expect(screen.getByText("Launch")).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
    fireEvent.click(await screen.findByText("Acme"));
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
    fireEvent.click(screen.getByRole("button", { name: "Work" }));
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

describe("Agents", () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    expect(await screen.findByRole("button", { name: "tutor" })).toBeInTheDocument();
    for (const n of ["strategist", "executive_assistant", "communications", "soundboard", "workspace_architect"]) {
      expect(screen.getByRole("button", { name: n })).toBeInTheDocument();
    }
    expect(screen.getByText(/Select an agent to begin/)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    fireEvent.click(await screen.findByRole("button", { name: "strategist" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "Plan the quarter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));

    expect(await screen.findByText(/Ollama unreachable/)).toBeInTheDocument();
  });

  it("keeps the run button disabled with no task entered", async () => {
    globalThis.fetch = makeFetch(agentsFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    fireEvent.click(await screen.findByRole("button", { name: "strategist" }));
    const input = screen.getByPlaceholderText("Give your agent a task…");
    fireEvent.change(input, { target: { value: "Plan the quarter" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Agent" }));

    expect(await screen.findByText(/Ollama unreachable/)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
    expect(await screen.findByText("My Team")).toBeInTheDocument();
    expect(screen.queryByText("E2E Workspace")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show sample data" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
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
    await screen.findByText(/Launch/);
    fireEvent.click(screen.getByText(/Launch/));
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
    expect(await screen.findByText("Assignment")).toBeInTheDocument();
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

describe("Conversation Browser", () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    expect(await screen.findByText("Grow my business")).toBeInTheDocument();
    expect(screen.getAllByText("Aisha").length).toBeGreaterThanOrEqual(1); // agent label on the conversation + card
    expect(screen.getByText(/Agent unknown/)).toBeInTheDocument();
    expect(screen.getByText("Legacy talk")).toBeInTheDocument();
  });

  it("filters conversations by agent", async () => {
    globalThis.fetch = makeFetch(convosFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    fireEvent.click(await screen.findByText("Grow my business"));
    const tr = await screen.findByTestId("transcript");
    expect(tr).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Plan" })).toBeInTheDocument(); // Markdown heading renders
    expect(screen.getByText("deep q15")).toBeInTheDocument(); // far beyond the 12-message window
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    fireEvent.click(await screen.findByText("Grow my business"));
    await screen.findByTestId("transcript");
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    // Browser still lists the saved conversations after starting fresh.
    expect(screen.getByText("Grow my business")).toBeInTheDocument();
    expect(screen.getByText("Legacy talk")).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Work" }));
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

  it("approves a pending proposal through the Phase C endpoint", async () => {
    const fn = makeFetch({
      [`${API}/work/feed`]: () =>
        ok({ items: [{ id: "pend1", work_type: "project", action: "create", status: "proposed", proposed_change: "create project", decision: null }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Work" }));
    fireEvent.click(await screen.findByTestId("approve-pend1"));
    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/work/proposals/pend1/approve`,
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("shows linked work for an opened conversation", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    fireEvent.click(await screen.findByText("Grow my business"));
    expect(await screen.findByTestId("linked-work")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Launch Goal" })).toBeInTheDocument();
  });
});
