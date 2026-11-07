# Personal AI Team — Architecture Review, Roadmap & M1.1 Execution-Reliability Plan

**Type:** documentation only (no application code or schema changes yet).
**Status:** review & plan — awaiting approval to implement M1.1.
**Companion:** `CODEBASE_BREAKDOWN_AND_ROADMAP.md` (overview), `ROADMAP.md` (phase tracker).

---

## 1. Purpose

Help you (a) understand the whole system and (b) decide the next milestone. The milestone
agreed is **M1 — make the existing system fast, recoverable, and trustworthy** (not bigger),
starting with **M1.1 — Execution Recovery + Idempotency**.

---

## 2. Verified architecture snapshot

- **Stack:** React/Vite → FastAPI → SQLite → Ollama (`llama3.1:8b`). Local-only core loop.
- **Agents (6):** `strategist`=Aisha, `communications`=Brandon, `tutor`=Brittany,
  `soundboard`=Portia, `workspace_architect`=Alex, `executive_assistant`=Taylor. Identities and
  permissions live in versioned `manifest.json`; shared base in `agents/base.py`.
- **Workflow (one live path):** delegate → `POST /projects` (planner, `json_schema`) →
  validate → approve → run (parallel dependency waves) → drafts (`output_json`) → review
  (approve/edit/send_back) → `pending_actions` (human-gated). Outward actions are a stub.
- **Data:** `agent_projects`, `agent_tasks` (note: global PK, remapped to `<project_id>::N`),
  `pending_actions`, `activity_log`. Scoped by `tenant_id`+`user_id`.
- **Auth/approval:** middleware fails closed (valid `x-token` or `LOCAL_MODE` trusted identity,
  else 401). `_require_human` enforces `role ∈ {user,admin}` on approve/run/review/action.
  `LOCAL_MODE=1` is *not* real auth (remote access requires more).
- **Concurrency:** `Database` serializes all `execute`/`transaction` through one
  `threading.Lock`. Parallel model calls; **serialized DB writes**.
- **Benchmarks:** planner ~27–38s; full 6-task run ~8.4 min (down from ~12 min).

---

## 3. Findings & risks (ranked)

1. **No interrupted-run recovery** — a restart mid-run leaves tasks stuck in `running`; a later
   `run()` sees only `pending` tasks as runnable → "unresolved task dependencies" → `failed`.
2. **No idempotency** on create (double-submit duplicates projects) or run (duplicate run calls).
3. **Synchronous long-run endpoint** holds a FastAPI worker; frontend polls as a workaround.
4. **Output contracts are best-effort** — malformed structured output can advance.
5. **One model for all roles**; **agent selection is model-driven** (planner only checks the
   agent name exists, not task↔capability fit).
6. **Inert legacy + `/team` System A surfaces** remain (not live; future cleanup).
7. **SQLite single-writer** — throughput ceiling under real parallelism.
8. **`LOCAL_MODE=1` ≠ authentication** for any network-reachable surface.

---

## 4. Prioritized roadmap

- **M1 – Reliability & speed (first):** M1.1 Execution recovery + idempotency → M1.2 Model-role
  separation + benchmark → M1.3 Capability-based agent selection → M1.4 Output-contract tiers.
- **M2 – Trust & learning:** preference-learning loop; unified approval center.
- **M3 – Integration (gated):** simulated → email/calendar → social/browser → travel; each an
  independent approval step.
- **M4 – Mobile (only after real auth):** React Native client; `LOCAL_MODE=1` never counts as
  auth on the network.

---

## 5. M1.1 — Execution Recovery + Idempotency (investigation & plan)

### 5.1 Execution lifecycle (current, verified)

```
POST /projects          create_project: one transaction inserts project (awaiting_plan_approval)
                                        + all tasks (pending). No idempotency key.
POST /projects/{id}/plan/approve        project.pending -> running.
POST /projects/{id}/run                 ProjectRunner.run():  (synchronous, in-endpoint)
    - requires status == "running"
    - builds `completed` from tasks already status='done'
    - wave loop: runnable = tasks status='pending' whose depends_on ⊆ completed
      - each _run_task: UPDATE status='running' -> build_runtime -> dispatch -> 
                        UPDATE status='done', output, output_json
    - end: status -> awaiting_review ; on unresolved deps or exception -> status='failed'
```

### 5.2 Transaction boundaries & concurrency (verified)

- `create_project` inserts the project **and** all its tasks inside one `transaction()` (atomic
  under the lock) — all-or-nothing.
- Each per-task status write (`running`, then `done`) is a single `execute()` — atomic under the
  lock.
- Because all writes serialize on `self._lock`, there are no SQLite data races, but two
  **concurrent `run()` calls** on the same project could both pass the `status=="running"`
  check before either updates it → **duplicate execution risk**. Fix by an atomic ownership
  claim (below).

### 5.3 Recovery semantics — the key question

> "Distinguish an abandoned task from one that completed work but crashed before persisting."

**Verified reality:** a task's state is stored only when the DB write happens. `_run_task` marks
`running`, then does the model call, then writes `done` + `output`. If the process dies
between the model finishing and the `done` write, that output is **never persisted** — it is
lost by definition. There is **no** persisted "done" that is later stranded as stale `running`,
because `done` and its output are written in the same atomic `execute`.

**Therefore:** resetting a task stuck in `status='running'` back to `pending` is **safe** — the
aborted attempt produced no persisted artifact, so re-running regenerates it. We never
overwrite a valid deliverable, because a valid deliverable is one whose `done`+`output` was
persisted, and that task is not in `running`.

To avoid clobbering a *legitimately in-flight* task (of a run that is not actually dead), we
need to know a run attempt is superseded. Solution: **monotonic run attempts** (below).

### 5.4 Smallest safe schema change (additive only)

Two additive integer columns + one text column (all with defaults → safe, non-breaking):

```
agent_projects : ADD run_attempt   INTEGER NOT NULL DEFAULT 0
                 ADD idempotency_key TEXT NULL            -- + UNIQUE index (nullable)
agent_tasks    : ADD task_attempt  INTEGER NOT NULL DEFAULT 0
```

No new tables, **no second state machine** — reuse `agent_projects.status` + `agent_tasks.status`.

- **Migration:** additive `ALTER TABLE ... ADD COLUMN ...` in `storage/database.py
  _apply_migrations` (already the idempotent additive pattern used today). Rollback = drop the
  three columns; since they're additive with defaults, dropping is trivial and nothing existing
  depends on them yet.

### 5.5 Behavior changes (REVISED) — ownership, keys, locking

**Single-owner claim (atomic state transition, not `IN ('approved','running')`).**
Ownership is encoded by the project status itself. The ONLY way to become the owner of a run
is the atomic transition **from the unclaimed state `approved` → `running`**:
```
UPDATE agent_projects
SET status='running', run_attempt = run_attempt+1, run_key=:key, run_heartbeat_at=:now
WHERE id=:id AND tenant_id=:t AND user_id=:u AND status='approved'
  AND (run_key IS NULL OR run_key <> :key)
```
- `rows == 1` → this caller owns **the** new attempt. No other request can claim it, because
  the status is no longer `approved`.
- `rows == 0` → not claimable now (already owned, or same key already in use).

**Three cases are distinguished by (status, run_key, heartbeat / run_attempt):**
- **New execution:** status `approved` → the claim above succeeds.
- **Existing active execution:** status `running` and heartbeat fresh. A duplicate run request
  is refused (409). A request with the **same `run_key`** returns the current in-progress state
  (idempotent) — it never starts a second run.
- **Recovery of an abandoned execution:** status `running` but the heartbeat has gone **stale**
  (older than a threshold, e.g. 3× the model timeout) because the owner process died.
  Recovery is two **short, atomic** transitions:
  1. Abandon the stale attempt: `SET status='approved', run_attempt=run_attempt+1
     WHERE status='running' AND (heartbeat stale)`; then
  2. Claim as new (the claim above).
  A **live** owner (fresh heartbeat) blocks step 1 → it cannot be stolen.

**Why this prevents two concurrent executions (incl. across processes):**
- SQLite is single-writer; the app lock serializes writers within a process, and SQLite's file
  write-lock serializes writers **across** FastAPI processes. Only the single statement that
  observes `status='approved'` (and atomically sets it to `running`) becomes the owner.
- Because ownership moves only `approved → running`, a second request — concurrent or
  sequential — finds `running` and cannot claim. Recovery requires a **stale** heartbeat, so a
  live owner is never displaced.

**Heartbeat (short writes, never around a model call):** the runner sets
`run_heartbeat_at` at the start of each task and after each task. These are single
`execute()`s under the lock (microseconds); the model generation happens **between** them,
outside any transaction/lock → we never hold a SQLite write lock while Ollama generates.

**Task attempts (consistent):** when a task starts under `run_attempt = N`, we set
`task_attempt = N`. Recovery reconcile:
```
UPDATE agent_tasks SET status='pending', task_attempt=0
WHERE project_id=:id AND status='running' AND task_attempt < :N
```
Only earlier-attempt, still-`running` tasks are reset. **`done` tasks (with persisted output)
are never touched** → valid deliverables are preserved and not re-run.

**Idempotency keys (client-supplied, separate for create vs run, tenant/user-scoped):**
- **Create:** `idempotency_key TEXT NULL` on `agent_projects` + a **UNIQUE index on
  `(tenant_id, user_id, idempotency_key)`** (nullable → ignores NULLs, so no-key creates are
  unaffected). A duplicate create key returns the **original** project (200) for its current
  status — after `completed`, `failed`, or an interrupted project, the same key always maps to
  that original project; it never creates a second one.
- **Run:** `run_key TEXT NULL` on `agent_projects`, scoped to the project. Behavior by state:
  - **Completed** (`awaiting_review`/`done`): same `run_key` → return current state. No re-run.
  - **Failed**: same `run_key` → return the stored failure (idempotent). Retrying must use a
    **new** run_key.
  - **Interrupted**: same `run_key` on a stale lease → triggers **recovery of that attempt**
    (finish, not a new parallel run).
  - **Fresh key**: a new claim (new attempt) — a deliberate re-run.

### 5.6 Transaction boundaries & locking (explicit)
- DB locks/transactions protect **only short state transitions**: insert project+tasks
  (`create_project`), the ownership claim, heartbeat writes, reconcile, per-task `running`/
  `done`. Each is a single short `execute()`/`transaction()`.
- **Model generation never runs inside a transaction or while holding the lock.** The runner
  writes `running`, releases the lock, calls `runtime.dispatch()` (Ollama), then re-acquires to
  write `done`. No lock is held across a model call. This is already true today and stays true.

### 5.7 Regression test plan (includes the concurrency + kill/restart you asked for)
- **Recovery:** project `running` with some tasks stuck `running` (old attempt) → run()
  reconciles them to `pending` and completes; **no `done` task or its output is touched**.
- **Concurrent execution:** fire N `run()` calls (threads/processes) → assert exactly one
  attempt becomes owner; others get 409/idempotent response, never a second execution.
- **Duplicate run key:** completed = same result, no re-run; failed = same failure, no auto-retry;
  interrupted = recovery of the same attempt.
- **Duplicate create key:** one project, returns original for all statuses.
- **Task attempts:** assert `task_attempt == run_attempt` after a run; a stale `running` task of
  an earlier attempt is the only thing reset.
- **Process-kill/restart:** integration test that simulates a crash (seed the DB to a
  mid-run `running` state from a prior attempt), then runs recovery and asserts completion —
  plus a manual live check by killing the worker mid-run and re-running.
- Human approval gates unchanged (approve/run/review still require role ∈ {user, admin}).

---

## 6. Revisions & decisions

**Addressed per your review:** (1) single-owner claim via `approved→running` (not
`IN ('approved','running')`); (2) client-supplied keys, create vs run separate, tenant/user
scoped; (3) locks cover only short state changes — never around model generation.

**Final decisions to confirm to implement:**
1. Approve additive schema: `agent_projects(+run_attempt, run_key, run_heartbeat_at,
   idempotency_key [+unique index], last_error)`, `agent_tasks(+task_attempt)` — all additive
   with defaults, backward-compatible; rollback = drop the columns.
2. Idempotency keys are **client-supplied** (create key and run key), scoped to tenant/user.
3. Output-validation tiers stay **out of M1.1**.
4. Runs stay synchronous (no background worker in M1.1).

*Documentation only. No application code or schema changed.*
