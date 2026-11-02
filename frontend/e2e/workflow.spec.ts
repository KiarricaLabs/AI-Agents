import { test, expect } from "@playwright/test";

test("create workspace via UI", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "workspace" }).click();
  await page.getByPlaceholder("Workspace name").fill("E2E Workspace");
  await page.getByRole("button", { name: "Create" }).click();
  // verify persisted on backend
  const resp = await request.get("http://127.0.0.1:8001/workspaces");
  const data = await resp.json();
  const items = data.items ?? [];
  expect(items.some((w: any) => w.name === "E2E Workspace")).toBeTruthy();
});