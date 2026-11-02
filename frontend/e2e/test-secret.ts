// Shared test-only signing secret for Playwright E2E.
//
// This value is injected into the isolated E2E backend process (see
// playwright.config.ts) and used by cross_tenant.spec.ts to forge test tokens.
// It is a clearly-labelled test key, never a production secret, and it must
// never be imported from `src/` (so it can never enter the Vite/frontend bundle).
export const E2E_AUTH_SECRET =
  "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e7d";
