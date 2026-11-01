import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import App from "./App";

const API = "http://127.0.0.1:8001";

function ok(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
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
    for (const t of ["workspaces", "projects", "goals", "assignments", "deliverables", "episodes"]) {
      expect(screen.getByRole("button", { name: t })).toBeInTheDocument();
    }
  });
});

describe("Workspaces", () => {
  it("creates a workspace via POST with the entered name", async () => {
    const fn = makeFetch();
    globalThis.fetch = fn as any;
    render(<App />);

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
    expect(await screen.findByText("Acme")).toBeInTheDocument();
  });

  it("disables create when offline", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("offline"))) as any;
    render(<App />);
    await screen.findByText(/offline - read only/);
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  });
});

describe("Projects", () => {
  it("renders projects with status", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch", status: "active" }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "projects" }));
    expect(await screen.findByText(/Launch/)).toBeInTheDocument();
    expect(screen.getByText(/active/)).toBeInTheDocument();
  });

  it("creates a project against the first workspace", async () => {
    const fn = makeFetch({
      [`${API}/workspaces`]: () => ok({ items: [{ id: "w1", name: "Acme" }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    // wait for workspaces to load before switching tabs
    await screen.findByText("Acme");
    fireEvent.click(screen.getByRole("button", { name: "projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces/projects`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ workspace_id: "w1", name: "New Project" }) })
      );
    });
  });
});

describe("Goals", () => {
  it("renders goals with priority", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces/goals`]: () => ok({ items: [{ id: "g1", title: "Ship v1", priority: 1 }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "goals" }));
    expect(await screen.findByText(/Ship v1/)).toBeInTheDocument();
    expect(screen.getByText(/\(p1\)/)).toBeInTheDocument();
  });

  it("creates a goal against the first project", async () => {
    const fn = makeFetch({
      [`${API}/workspaces/projects`]: () => ok({ items: [{ id: "p1", name: "Launch" }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    // wait for projects to load before clicking create
    fireEvent.click(screen.getByRole("button", { name: "projects" }));
    await screen.findByText(/Launch/);
    fireEvent.click(screen.getByRole("button", { name: "goals" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Goal" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces/goals`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ project_id: "p1", title: "New Goal", priority: 1 }) })
      );
    });
  });
});

describe("Assignments", () => {
  it("renders assignments with agent and priority", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/workspaces/assignments`]: () => ok({ items: [{ id: "a1", agent_id: "tutor", priority: 2 }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "assignments" }));
    expect(await screen.findByText(/tutor/)).toBeInTheDocument();
    expect(screen.getByText(/\(p2\)/)).toBeInTheDocument();
  });
});

describe("Deliverables", () => {
  const versionsFixture = () => ({
    [`${API}/workspaces/deliverables`]: () =>
      ok({ items: [{ id: "d1", title: "Report" }] }),
    [`${API}/workspaces/deliverables/d1/versions`]: () =>
      ok({
        items: [
          { id: "v1", version: 1, content: "hello", status: "approved" },
          { id: "v2", version: 2, content: "hello world", status: "pending" },
        ],
      }),
  });

  it("lists deliverables by id", async () => {
    globalThis.fetch = makeFetch(versionsFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "deliverables" }));
    expect(await screen.findByText(/Report/)).toBeInTheDocument();
  });

  it("loads versions and renders a diff between v1 and the latest version", async () => {
    globalThis.fetch = makeFetch(versionsFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "deliverables" }));
    fireEvent.click(await screen.findByText(/Report/));

    expect(await screen.findByText(/Compare v1 vs v2/)).toBeInTheDocument();
    // changed lines are prefixed with "~ "; the diff container shows both versions' changed content
    expect(screen.getByTestId("diff")).toHaveTextContent("hello world");
  });

  it("shows approve/reject controls only for non-approved versions", async () => {
    globalThis.fetch = makeFetch(versionsFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "deliverables" }));
    fireEvent.click(await screen.findByText(/Report/));

    // v1 is approved -> no buttons; v2 is pending -> one Approve + one Reject
    const approve = await screen.findByRole("button", { name: "Approve" });
    const reject = screen.getByRole("button", { name: "Reject" });
    expect(approve).toBeInTheDocument();
    expect(reject).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Approve" })).toHaveLength(1);
  });

  it("rejects a version via POST with a reason", async () => {
    const fn = makeFetch(versionsFixture());
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "deliverables" }));
    fireEvent.click(await screen.findByText(/Report/));
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces/versions/v2/reject`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "requested revision" }) })
      );
    });
  });

  it("approves a version via POST", async () => {
    const fn = makeFetch(versionsFixture());
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "deliverables" }));
    fireEvent.click(await screen.findByText(/Report/));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/workspaces/versions/v2/approve`,
        expect.objectContaining({ method: "POST" })
      );
    });
  });
});

describe("Episodes", () => {
  it("shows empty state when there are no episodes", async () => {
    globalThis.fetch = makeFetch() as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "episodes" }));
    expect(await screen.findByText(/No episodes/)).toBeInTheDocument();
  });

  it("renders episode progress and running controls", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/episodes`]: () =>
        ok({ items: [{ id: "e1", agent_id: "tutor", status: "running", progress: 0.5 }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "episodes" }));

    expect(await screen.findByText(/tutor/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("cancels a running episode via POST", async () => {
    const fn = makeFetch({
      [`${API}/episodes`]: () =>
        ok({ items: [{ id: "e1", agent_id: "tutor", status: "running", progress: 0.5 }] }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "episodes" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(`${API}/episodes/e1/cancel`, expect.objectContaining({ method: "POST" }));
    });
  });

  it("does not show controls for non-running episodes", async () => {
    globalThis.fetch = makeFetch({
      [`${API}/episodes`]: () =>
        ok({ items: [{ id: "e1", agent_id: "tutor", status: "done", progress: 1 }] }),
    }) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "episodes" }));
    await screen.findByText(/tutor/);
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "agents" }));
    expect(await screen.findByRole("button", { name: "tutor" })).toBeInTheDocument();
    for (const n of ["strategist", "executive_assistant", "communications", "soundboard", "workspace_architect"]) {
      expect(screen.getByRole("button", { name: n })).toBeInTheDocument();
    }
    expect(screen.getByText(/Select an agent to begin/)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "agents" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "Explain gravity" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(fn).toHaveBeenCalledWith(
        `${API}/agents/tutor/run`,
        expect.objectContaining({ method: "POST", body: JSON.stringify({ task: "Explain gravity" }) })
      );
    });
    expect(await screen.findByText("Gravity pulls objects together.")).toBeInTheDocument();
    expect(screen.getByText(/Processed at: local:ollama:llama3.1/)).toBeInTheDocument();
  });

  it("shows an error when agent execution fails", async () => {
    const fn = makeFetch({
      ...agentsFixture(),
      [`${API}/agents/strategist/run`]: () =>
        Promise.resolve({ ok: false, status: 502, json: () => Promise.resolve({ detail: "Ollama unreachable" }) }),
    });
    globalThis.fetch = fn as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "agents" }));
    fireEvent.click(await screen.findByRole("button", { name: "strategist" }));
    fireEvent.change(screen.getByPlaceholderText("Give your agent a task…"), {
      target: { value: "Plan the quarter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText(/Ollama unreachable/)).toBeInTheDocument();
  });

  it("keeps the run button disabled with no task entered", async () => {
    globalThis.fetch = makeFetch(agentsFixture()) as any;
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "agents" }));
    fireEvent.click(await screen.findByRole("button", { name: "tutor" }));
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
  });
});
