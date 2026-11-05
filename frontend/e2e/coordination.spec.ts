// T2-C-7 Phase 2 — Coordination workflow E2E.
//
// Exercises the real frontend + backend against the dedicated isolated E2E DB
// (see playwright.config.ts). A deterministic, approved TeamGoal is seeded via
// the real services (seed_coordination.py) because TeamGoal *propose* has no
// HTTP endpoint. Everything after that is driven through the actual UI and
// HTTP API:
//   1. Open the AI Team coordination panel.
//   2. Select the eligible TeamGoal and review its plan.
//   3. Authorize the frozen plan (human action).
//   4. Initiate execution (human action).
//   5. Verify execution status + ordered steps.
//   6. Verify NO automatic dispatch/advance.
//   7. Verify deliverable version history pre-aggregation empty state.
//
// Safety: no agent step is dispatched, no Ollama/live model is invoked, and no
// run-all/auto-advance is introduced. All coordination mutations are human-only
// server-side; this spec only verifies the wiring, it does not weaken it.
import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { API } from "./env";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const E2E_DB = path.resolve(ROOT, "data", "pat.test.db");
// Matches playwright.config.ts's interpreter choice for the backend.
const PYTHON = process.env.PAT_PYTHON || "/Users/kiarricafavors/AI Agent/venv/bin/python";

// Seed an approved TeamGoal into the isolated E2E DB; returns its id.
function seed(): string {
  const out = execFileSync(PYTHON, [path.join(__dirname, "seed_coordination.py")], {
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: ROOT, PAT_DB_PATH: E2E_DB, PAT_LOCAL_MODE: "1" },
    encoding: "utf8",
  }).trim();
  if (!out) throw new Error("coordination E2E seed returned no team_goal id");
  return out.split("\n").pop() as string;
}

// Seed an owned project goal (no TeamGoal) so the authoring form picker has a
// real, owner-scoped option; returns its id.
function seedProjectGoal(): string {
  const out = execFileSync(
    PYTHON,
    [path.join(__dirname, "seed_coordination.py"), "--project-goal"],
    {
      cwd: ROOT,
      env: { ...process.env, PYTHONPATH: ROOT, PAT_DB_PATH: E2E_DB, PAT_LOCAL_MODE: "1" },
      encoding: "utf8",
    }).trim();
  if (!out) throw new Error("coordination E2E project-goal seed returned no id");
  return out.split("\n").pop() as string;
}

let goalId: string;
let projectGoalId: string;

test.beforeAll(() => {
  goalId = seed();
  projectGoalId = seedProjectGoal();
});

test("reviews, authorizes, and starts a coordination execution without auto-advance", async ({ page }) => {
  // 1. Open the AI Team coordination panel.
  await page.goto("/");
  await page.getByRole("button", { name: "AI Team" }).click();
  await expect(page.getByTestId("coordination-panel")).toBeVisible();

  // 2. Select the seeded, eligible TeamGoal and review its plan preview.
  const goalBtn = page.getByTestId(`coord-goal-${goalId}`);
  await expect(goalBtn).toBeVisible();
  await goalBtn.click();
  const steps = page.getByTestId("coord-steps");
  await expect(steps).toBeVisible();

  // 3. Authorize the frozen coordination plan (explicit human action).
  await expect(page.getByTestId("coord-authorize")).toBeEnabled();
  await page.getByTestId("coord-authorize").click();

  // 4. Initiate execution (explicit human action).
  await expect(page.getByTestId("coord-start-exec")).toBeEnabled();
  await page.getByTestId("coord-start-exec").click();

  // 5. Execution is running; ordered steps render.
  await expect(page.getByTestId("coord-exec")).toContainText("Running");
  const stepItem = page.getByTestId("coord-step-1");
  await expect(stepItem).toContainText("Strategist");
  await expect(stepItem).toContainText("Planned");

  // 6. NO automatic dispatch / advance: step 1 is still pending (no review
  //    affordance) and the next step requires an explicit human click.
  await expect(page.getByTestId("coord-accept-1")).toHaveCount(0);
  await expect(page.getByTestId("coord-exec-next")).toBeEnabled();
  await expect(page.getByTestId("coord-accept-2")).toHaveCount(0);

  // 7. Deliverable version history is in its pre-aggregation empty state.
  await expect(page.getByTestId("coord-versions")).toHaveCount(0);
});

test("creates and approves a TeamGoal through the UI (no auto-execution)", async ({ page, request }) => {
  const TITLE = "UI Created Goal";

  await page.goto("/");
  await page.getByRole("button", { name: "AI Team" }).click();
  await expect(page.getByTestId("coordination-panel")).toBeVisible();

  // Open the authoring form and select an owned project goal.
  await page.getByTestId("coord-new-goal").click();
  await expect(page.getByTestId("coord-create")).toBeVisible();
  const picker = page.getByTestId("coord-goal-picker");
  // options inside the collapsed select are not "visible"; assert presence by text
  await expect(picker).toContainText("E2E Project Goal");
  await picker.selectOption(projectGoalId);

  // Title + a valid ordered step (coordinator defaults to workspace_architect).
  await page.getByTestId("coord-form-title").fill(TITLE);
  // Responsibility must match a declared strategist capability (plan builder
  // rejects capability-unrelated text).
  await page.getByTestId("coord-step-resp-1").fill("Strategy for the launch");

  await page.getByTestId("coord-propose").click();

  // Propose-only result: success message + proposed status in the refreshed list.
  await expect(page.getByText(/Approval is a separate human step/)).toBeVisible();
  const goalButton = page.getByRole("button", { name: new RegExp(TITLE) });
  await expect(goalButton).toContainText("proposed");

  // Proposing alone must NOT authorize a plan or start execution.
  await goalButton.click();
  await expect(page.getByTestId("coord-authorize")).toHaveCount(0);
  await expect(page.getByTestId("coord-start-exec")).toHaveCount(0);

  // Explicit human approval through the existing human-only backend decision.
  const list = await (await request.get(`${API}/team/goals`)).json();
  const fresh = list.items.find((g: any) => g.title === TITLE);
  expect(fresh).toBeTruthy();
  expect(fresh!.status).toBe("proposed");
  const appr = await request.post(`${API}/team/goals/${fresh!.id}/approve`, { data: {} });
  expect(appr.status()).toBe(200);

  // Reload the UI: goal is approved and eligible for plan review, but execution
  // is still NOT initiated and no agent step is dispatched.
  await page.getByTestId("coord-refresh").click();
  const approvedBtn = page.getByRole("button", { name: new RegExp(TITLE) });
  await expect(approvedBtn).toContainText("approved");
  await approvedBtn.click();
  await expect(page.getByTestId("coord-authorize")).toBeEnabled();
  await expect(page.getByTestId("coord-start-exec")).toHaveCount(0);
  await expect(page.getByTestId("coord-exec")).toHaveCount(0);
  await expect(page.getByTestId("coord-exec-next")).toHaveCount(0);
});

test("validates a missing title before proposing", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "AI Team" }).click();
  await expect(page.getByTestId("coordination-panel")).toBeVisible();

  await page.getByTestId("coord-new-goal").click();
  await expect(page.getByTestId("coord-create")).toBeVisible();

  // Submit with an empty title -> blocked client-side, form stays open.
  await page.getByTestId("coord-propose").click();
  await expect(page.getByText(/A title is required/)).toBeVisible();
  await expect(page.getByTestId("coord-create")).toBeVisible();
});
