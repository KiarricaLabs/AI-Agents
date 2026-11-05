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

let goalId: string;

test.beforeAll(() => {
  goalId = seed();
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
