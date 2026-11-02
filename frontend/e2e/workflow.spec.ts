import { test, expect } from "@playwright/test";

test("create workspace via UI", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Workspaces" }).click();
  await page.getByPlaceholder("Workspace name").fill("E2E Workspace");
  await page.getByRole("button", { name: "Create" }).click();
  // Verify it is genuinely persisted on the backend (poll to avoid the async
  // create race under parallel load, while still asserting real persistence).
  await expect
    .poll(async () => {
      const resp = await request.get("http://127.0.0.1:8001/workspaces");
      const data = await resp.json();
      return (data.items ?? []).some((w: any) => w.name === "E2E Workspace");
    }, { timeout: 5000 })
    .toBe(true);
});