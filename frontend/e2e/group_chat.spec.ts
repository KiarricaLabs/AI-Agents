// Group-chat E2E (Phase 10–11). Exercises the Home team-chat surface through the
// real frontend + backend.
//
// Safety: NO live-model dependency. To verify agent *replies* deterministically,
// run the e2e backend with PAT_MOCK_AGENTS=1 so /team/messages returns scripted
// mock replies (no Ollama). The wiring assertions (chat renders, proposal panel
// opens) are model-free and hold without a model. Nothing here auto-dispatches,
// auto-advances, or starts work on its own — a chat message alone must not
// produce an approval/run action.
import { test, expect } from "@playwright/test";

test("home renders the AI team group chat", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("team-chat")).toBeVisible();
  await expect(page.getByTestId("team-chat-input")).toBeVisible();
});

test("request-a-proposal panel opens without a model", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("team-chat")).toBeVisible();
  await page.getByTestId("mode-propose").click();
  await expect(page.getByTestId("propose-panel")).toBeVisible();
});

test("a chat message never auto-dispatches or auto-advances work", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("team-chat-input")).toBeVisible();
  await page.getByTestId("team-chat-input").fill("Plan a launch strategy and draft the announcement");
  await page.getByTestId("team-chat-send").click();
  // A message alone must not surface a dispatch/run or approval action.
  await expect(page.getByTestId("team-chat-send")).toBeEnabled();
  await expect(page.getByTestId("run-agent-button")).toHaveCount(0);
  await expect(page.getByTestId("extract-assignment")).not.toBeAttached();
});
