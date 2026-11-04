import { test, expect } from "@playwright/test";

test("real offline reload serves cached shell", async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  // First load: registers and activates the service worker.
  await page.goto("/");
  await expect(page.getByText(/Personal AI Team/)).toBeVisible();

  // Wait for the service worker to be active.
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });

  // Reload once so (a) the page is controlled by the service worker and
  // (b) the hashed JS/CSS assets pass through its fetch handler and get cached.
  await page.reload();
  await expect(page.getByText(/Personal AI Team/)).toBeVisible();

  // Ensure this page is actually controlled before going offline.
  await page.evaluate(async () => {
    if (!navigator.serviceWorker.controller) {
      await new Promise<void>((resolve) => {
        navigator.serviceWorker.addEventListener("controllerchange", () => resolve(), { once: true });
      });
    }
  });

  await ctx.setOffline(true);
  await page.reload();
  await expect(page.getByText(/Personal AI Team/)).toBeVisible();
  await page.getByRole("button", { name: "Projects" }).click();

  // Write paths remain disabled while offline.
  await expect(page.getByRole("button", { name: "Create" })).toBeDisabled();

  await ctx.close();
});
