import { test, expect } from "@playwright/test";

const AGENTS = [
  "tutor",
  "strategist",
  "executive_assistant",
  "communications",
  "soundboard",
  "workspace_architect",
];

test("agents tab lists all six agents and gates the run flow", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "agents" }).click();

  for (const name of AGENTS) {
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  }

  // Selecting an agent reveals the task input, with Run disabled until text is entered.
  await page.getByRole("button", { name: "tutor", exact: true }).click();
  await expect(page.getByPlaceholder("Give your agent a task…")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run" })).toBeDisabled();
});

test("running a task against an agent produces a reply", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await page.getByRole("button", { name: "agents" }).click();
  await page.getByRole("button", { name: "tutor", exact: true }).click();

  await page.getByPlaceholder("Give your agent a task…").fill("Say hello in one sentence.");
  await page.getByRole("button", { name: "Run" }).click();

  const reply = page.getByTestId("agent-reply");
  await expect(reply).toBeVisible();
  await expect(reply).not.toHaveText(/^\s*$/);
});
