import { test, expect } from "@playwright/test";

test("offline indicator via data fetch failure", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Personal AI Team/)).toBeVisible();
  // Simulate backend outage by routing API to an unreachable host
  await page.route("**/workspaces**", (route) => route.abort());
  await page.route("**/health**", (route) => route.abort());
  await page.reload();
  await expect(page.getByText(/offline/)).toBeVisible();
});