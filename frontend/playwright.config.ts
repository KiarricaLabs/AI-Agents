import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { E2E_AUTH_SECRET } from "./e2e/test-secret";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Repository root (playwright.config.ts lives in frontend/).
const ROOT = path.resolve(__dirname, "..");

// Dedicated E2E database — a clearly isolated file, never the real data/pat.db.
const E2E_DB = path.resolve(ROOT, "data", "pat.test.db");
const REAL_DB = path.resolve(ROOT, "data", "pat.db");

// Safety net at config load: fail before any test starts if the two ever collide.
if (E2E_DB === REAL_DB) {
  throw new Error(`Refusing to run E2E: test DB resolves to the real DB (${REAL_DB})`);
}

// E2E uses its own dedicated ports (defaults 8011/5273) so it can run on a fresh
// CI runner and never collides with (or reuses) a developer's backends/frontends
// on :8001/:5173. Specs read the same values from the environment.
const BACKEND_PORT = process.env.PAT_E2E_BACKEND_PORT || "8011";
const FRONTEND_PORT = process.env.PAT_E2E_FRONTEND_PORT || "5273";
const BASE_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

// Python interpreter for the backend. Override with PAT_PYTHON if needed.
const PYTHON = process.env.PAT_PYTHON || "/Users/kiarricafavors/AI Agent/venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: { baseURL: BASE_URL },
  webServer: [
    {
      // Isolated backend (dedicated E2E DB, local mode, never the real app DB).
      // reuseExistingServer is false so a real backend can never be reused.
      // PAT_MOCK_AGENTS=1 makes group-chat replies scripted (no Ollama), so the
      // E2E is deterministic and can never depend on a live model.
      command: `PAT_DB_PATH='${E2E_DB}' PAT_LOCAL_MODE=1 PAT_MOCK_AGENTS=1 PAT_AUTH_SECRET='${E2E_AUTH_SECRET}' '${PYTHON}' -m uvicorn api.app:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      reuseExistingServer: false,
      cwd: ROOT,
      timeout: 60_000,
    },
    {
      // Frontend (Vite) so UI specs (page.goto) are self-contained in CI.
      // VITE_API_BASE points the served app at the isolated E2E backend.
      command: `VITE_API_BASE=http://127.0.0.1:${BACKEND_PORT} npm run dev -- --host 127.0.0.1 --port ${FRONTEND_PORT}`,
      url: BASE_URL,
      reuseExistingServer: false,
      cwd: __dirname,
      timeout: 60_000,
    },
  ],
});
