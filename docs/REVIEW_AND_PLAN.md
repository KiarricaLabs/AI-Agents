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

### 5.5 Behavior changes (the design)

**Ownership claim (solves race + recovery):**
```
claim = "UPDATE agent_projects SET status='running', run_attempt=run_attempt+1
         WHERE id=? AND user_id=? AND tenant_id=? AND status IN ('approved','running')
         AND (run_attempt = ? OR <recovery allowed>)"
```
Atomic under the lock. Only one caller wins a given run attempt.

**Recovery (within the claim):** after claiming `run_attempt = N`, reconcile:
```
UPDATE agent_tasks SET status='pending', output=NULL, task_attempt=0
WHERE project_id=? AND status='running' AND task_attempt < N
```
i.e. any task of an **earlier** attempt that is stuck `running` is reset to `pending` and
re-run under the new attempt. In-flight tasks of the *current* attempt (`task_attempt == N`)
are left alone (they belong to the live run).

**Run idempotency:** the endpoint accepts an optional `X-Idempotency-Key`. If a run is already
active for that key (or `run_attempt == key`'s attempt), return the current status instead of
starting a duplicate. A **legitimate recovery** is a new claim (new attempt) that resumes the
existing project — not a parallel second run.

**Create idempotency:** `create_project` accepts an optional `idempotency_key`; a UNIQUE index
means a duplicate key returns the existing project (200) instead of inserting a new one.

`Idempotency` (same request ⇒ same result) and `recovery` (resume where it left off) remain
separate concerns, satisfied by the same two columns.

### 5.6 Regression test plan

- **Recovery:** set a project `running` with some tasks stuck `running` (simulated crash);
  invoke run → assert tasks reconcile to `pending` and the run completes. Verify **no existing
  `done` task is re-run**.
- **Race/claim:** fire concurrent `run()` calls → assert only one attempt executes.
- **Duplicate run:** same `X-Idempotency-Key` twice → one execution, second returns current
  status.
- **Duplicate create:** same `idempotency_key` twice → one project.
- **Restart resume:** kill the worker mid-run (test harness), restart, run → completes.

---

## 6. Decisions needed before implementation

1. Approve the additive schema (`run_attempt`, `task_attempt`, `idempotency_key`) and the
   ownership-claim + reconcile design.
2. Confirm idempotency keys are **client-supplied** (frontend sends a key) vs server-generated.
3. Output-validation tiers (soft default / strict for structured) stay **out of M1.1** — confirm.
4. Concurrency: acceptable to keep all runs serialized under the lock for now (no DB migration
   to a queue) — confirm we are not adding a background worker in M1.1.

*Documentation only. No application code or schema changed.*
