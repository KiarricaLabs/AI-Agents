import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Repository root (playwright.config.ts lives in frontend/).
const ROOT = path.resolve(__dirname, "..");
const REAL_DB = path.resolve(ROOT, "data", "pat.db");

// Dedicated E2E database — a clearly isolated file, never the real data/pat.db.
// Cleanup happens only in global-teardown (after the backend has stopped), so
// there is no startup deletion that could race with the freshly launched backend.
const E2E_DB = path.resolve(ROOT, "data", "pat.test.db");

// Safety net at config load: fail before any test starts if the two ever collide.
if (E2E_DB === REAL_DB) {
  throw new Error(`Refusing to run E2E: test DB resolves to the real DB (${REAL_DB})`);
}

// Python interpreter for the backend. Override with PAT_PYTHON if needed.
const PYTHON = process.env.PAT_PYTHON || "/Users/kiarricafavors/AI Agent/venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: { baseURL: "http://localhost:5173" },
  webServer: [
    {
      // Isolated backend. reuseExistingServer is false so a real (non-test)
      // backend can never be reused for E2E; port 8001 must be free.
      command: `PAT_DB_PATH='${E2E_DB}' PAT_LOCAL_MODE=1 '${PYTHON}' -m uvicorn api.app:app --host 127.0.0.1 --port 8001`,
      url: "http://127.0.0.1:8001/health",
      reuseExistingServer: false,
      cwd: ROOT,
      timeout: 60_000,
    },
  ],
});
