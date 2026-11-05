// T2-C-6 — coordination API-layer tests.
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  listTeamGoals,
  reviewCoordinationPlan,
  authorizeCoordinationPlan,
  initiateExecution,
  executeNextStep,
  reviewStep,
  aggregateDeliverable,
  reviewDeliverable,
  getExecutionStatus,
  listDeliverableVersions,
  getDeliverableVersion,
  stepStatusLabel,
  execStatusLabel,
  versionStatusLabel,
  humanizeAgent,
} from "./coordination";

function ok(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
}
function fail(status: number, data: unknown) {
  return Promise.resolve({ ok: false, status, json: () => Promise.resolve(data) });
}

function useFetch(fn: (url: string, init?: any) => any) {
  const spy = vi.fn(fn);
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("coordination API layer", () => {
  it("lists team goals", async () => {
    useFetch(() => ok({ items: [{ id: "g1", title: "Launch", coordinator_agent: "workspace_architect", status: "approved" }] }));
    const res = await listTeamGoals();
    expect(res.items).toHaveLength(1);
    expect(res.items[0].id).toBe("g1");
  });

  it("reviews a coordination plan", async () => {
    useFetch((_url) => ok({ team_goal_id: "g1", coordinator: "workspace_architect", steps: [], plan_valid: true, errors: [], warnings: [], transient: true } as any));
    const p = await reviewCoordinationPlan("g1");
    expect(p.plan_valid).toBe(true);
    expect(p.transient).toBe(true);
  });

  it("authorizes a coordination plan", async () => {
    useFetch((_url, _init) => ok({ plan_id: "p1", team_goal_id: "g1", coordinator: "workspace_architect", status: "authorized", steps: [], reused: false }));
    const p = await authorizeCoordinationPlan("g1");
    expect(p.plan_id).toBe("p1");
  });

  it("initiates an execution", async () => {
    useFetch((_url, _init) => ok({ execution_id: "e1", plan_id: "p1", team_goal_id: "g1", status: "running", reused: false }));
    const e = await initiateExecution("p1");
    expect(e.execution_id).toBe("e1");
  });

  it("executes the next step as a human request", async () => {
    useFetch((_url, _init) => ok({ execution_id: "e1", step: 1, agent_id: "strategist", status: "awaiting_review" }));
    const r = await executeNextStep("p1", "e1");
    expect(r.step).toBe(1);
  });

  it("reviews a step with a decision + note", async () => {
    useFetch((url, init) => {
      const body = JSON.parse((init as any).body);
      expect(body.decision).toBe("revision_requested");
      expect(body.note).toBe("rework the plan");
      return ok({ execution_id: "e1", step: 1, decision: "revision_requested", run_status: "running" });
    });
    const r = await reviewStep("p1", "e1", 1, "revision_requested", "rework the plan");
    expect(r.decision).toBe("revision_requested");
  });

  it("aggregates the deliverable", async () => {
    useFetch(() => ok({ deliverable_id: "d1", status: "pending" }));
    const d = await aggregateDeliverable("p1", "e1");
    expect(d.status).toBe("pending");
  });

  it("reviews a deliverable with specific rework steps", async () => {
    useFetch((url, init) => {
      const body = JSON.parse((init as any).body);
      expect(body.decision).toBe("revision_requested");
      expect(body.rework_steps).toEqual([1, 2]);
      return ok({ execution_id: "e1", decision: "revision_requested", run_status: "running" });
    });
    const r = await reviewDeliverable("p1", "e1", "revision_requested", undefined, [1, 2]);
    expect(r.decision).toBe("revision_requested");
  });

  it("gets execution status", async () => {
    useFetch(() => ok({ execution_id: "e1", plan_id: "p1", team_goal_id: "g1", status: "running" }));
    const s = await getExecutionStatus("p1", "e1");
    expect(s.status).toBe("running");
  });

  it("lists deliverable versions", async () => {
    useFetch(() => ok({ execution_id: "e1", versions: [{ version_id: "v1", version: 1, content: {}, status: "pending" }] }));
    const r = await listDeliverableVersions("p1", "e1");
    expect(r.versions).toHaveLength(1);
    expect(r.versions[0].version).toBe(1);
  });

  it("gets a single deliverable version", async () => {
    useFetch(() => ok({ version_id: "v2", version: 2, content: { steps: [] }, status: "approved", revision_of: "v1" }));
    const v = await getDeliverableVersion("p1", "e1", "v2");
    expect(v.status).toBe("approved");
    expect(v.revision_of).toBe("v1");
  });

  it("surfaces backend detail on error", async () => {
    useFetch(() => fail(409, { detail: "invalid transition" }));
    await expect(executeNextStep("p1", "e1")).rejects.toThrow(/invalid transition/);
  });

  it("maps status labels and agent slugs", () => {
    expect(stepStatusLabel("awaiting_review")).toBe("Ready for review");
    expect(execStatusLabel("ready_for_review")).toBe("Ready for review");
    expect(versionStatusLabel("revision_requested")).toBe("Revision requested");
    expect(humanizeAgent("workspace_architect")).toBe("Workspace Architect");
    expect(humanizeAgent("")).toBe("Unknown agent");
  });
});
