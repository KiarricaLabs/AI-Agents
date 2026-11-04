// Shared E2E runtime values. These must match playwright.config.ts, which reads
// the same env overrides. Defaults are the dedicated E2E ports (not :8001/:5173)
// so tests never collide with (or reuse) a developer's running app.
export const BACKEND_PORT = process.env.PAT_E2E_BACKEND_PORT || "8011";
export const FRONTEND_PORT = process.env.PAT_E2E_FRONTEND_PORT || "5273";
export const API = `http://127.0.0.1:${BACKEND_PORT}`;
