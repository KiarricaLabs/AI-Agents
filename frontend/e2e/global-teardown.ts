import { rmSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const E2E_DB = path.resolve(ROOT, "data", "pat.test.db");

export default function globalTeardown(): void {
  // Remove the dedicated E2E database (and any SQLite sidecar files) after the
  // backend has stopped, so test records never accumulate between runs.
  for (const suffix of ["", "-wal", "-shm"]) {
    const p = `${E2E_DB}${suffix}`;
    if (existsSync(p)) rmSync(p);
  }
}
