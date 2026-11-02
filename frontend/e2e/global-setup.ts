import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const REAL_DB = path.resolve(ROOT, "data", "pat.db");
const E2E_DB = path.resolve(ROOT, "data", "pat.test.db");

export default function globalSetup(): void {
  // Re-assert the safety net at setup time: the E2E database must never be the
  // real application database. No startup deletion happens here — cleanup is
  // done in global-teardown after the backend has been stopped.
  if (E2E_DB === REAL_DB) {
    throw new Error(
      `Refusing to run E2E: test DB resolves to the real DB (${REAL_DB})`
    );
  }
}
