# Personal AI Team — Codebase Breakdown, Current State, and Roadmap

**Purpose:** a study-and-critique document that explains, end to end, how this system works
from browser to database, where it is today, and what it takes to reach your full
"approval-gated agentic operating system" vision — plus why the chosen steps are right and
what the alternatives are.

**How to read this:** every section separates **verified facts** (things I confirmed in the
code or a live check) from **assessment/judgment** (my engineering reasoning). Treat your
job as the critic: challenge the judgments, not the verified facts.

> Verified: 2026-11-07. Backend suite: **469 tests OK** (live-Ollama tests opt-in via
> `PAT_RUN_LIVE_TESTS`). Frontend: 4 files, **58 passed / 12 skipped**, TypeScript + Vite
> clean. Working tree clean at `c6c55af`.

---

## 1. System at a glance

It is a **local-first web app**: React/Vite frontend, Python FastAPI backend, SQLite, a local
Ollama model. No cloud dependency for the core loop.

```
Browser (React/Vite)
   │  fetch() → JSON  (direct to :8001)
   ▼
FastAPI (api/app.py)  ── middleware: identity/auth (fail-closed)
   │  routers/
   ▼
core/project_planner + project_runner  (structured workflow)
   │                 build_runtime → orchestrator → agents
   ▼
ModelRouter → llm_client → Ollama (:11434)
   │
   ▼
SQLite (data/pat.db)  — via storage/database.py
```

> **Architectural status (verified):** the legacy "System A" (TeamGoal/coordination +
> workspace/goal/deliverable + episodes) has been removed from the **live path**. The
> application is now **one system**: the structured `projects`/`actions` workflow plus the
> shared capabilities (memory, brand, agents, chat, feedback, evaluations). Some legacy core
> *modules* and DB tables remain **inert** (present but not invoked) — see §5 and §9.

---

## 2. What exists today (verified)

### 2.1 Frontend (`frontend/src/`)
| File | Responsibility | State |
|---|---|---|
| `App.tsx` | Shell, nav, tabs, state, renders panels | Live (~3,300 lines). Tabs: **Home · Projects · Task Center · Settings**. |
| `team_chat.tsx` | Home chat. Modes: ask team / designate / **delegate** | Live. Delegate → `POST /projects`. |
| `structured_projects.tsx` | The **only** project surface: plan → approve → run (live progress) → review | Live. |
| `command_center_sidebar.tsx`, `workflow_overview.tsx`, `team_status.tsx`, `team_memory.tsx`, `evaluation_panel.tsx`, `pipeline.tsx` | Panels/status/learning | Live/auxiliary. |
| `coordination.ts` | Legacy TeamGoal helpers (`proposeTeamGoal`, `validateTeamGoalDraft`) | **Inert** — still imported by `App.tsx` line 6 but never triggered (its call site was removed with the Projects legacy UI). |
| `diff.ts`, `markdown.tsx`, `knownSamples.ts`, `uiText.ts`, `main.tsx`, CSS | Utilities/bootstrap | Live. |
| *(deleted)* `coordination_panel.tsx`, `review_center.tsx`, Activity-tab code | — | Removed. |

**Nav tabs today:** Home, Projects, Task Center, Settings. *(Activity and the Projects →
Proposals subsection were removed.)*

### 2.2 Backend (`api/`, `core/`, `agents/`, `storage/`)
- **Mounted routers** (`api/app.py`: `memory`, `agents`, `brand`, `team`, `agent_comm`,
  `progress`, `feedback`, `evaluations`, `projects`, `actions` — 10 total).
  *(Removed: `workspaces`, `work`, `tasks`, `episodes`, `team_goals`, `team_goals_execution`,
  `review_center`.)*
- **Core (live):** `orchestrator.py` (dispatch), `model_router.py` + `llm_client.py`
  (Ollama), `project_planner.py` (structured plan), `project_runner.py` (parallel dependency
  waves + retries), `output_contracts.py` (per-type JSON summaries), `action_executor.py`
  (safe outward-action stub), `brand.py`/`brand_scope.py` (brand facts), `auth.py` (tokens),
  `runtime.py` (wires registry/services), `policy.py`, `memory.py`, `feedback.py`, `tools`
  (registry + local simulation tools).
- **Agents (6):** `strategist`, `communications`, `tutor`, `soundboard`,
  `workspace_architect`, `executive_assistant`. Each has `manifest.json` (identity,
  personality, capabilities, tools, permissions) + `agent.py`. Shared base: `agents/base.py`.
- **Inert legacy core modules** (present, not on the live path): `workspace.py`,
  `work_proposals.py`, `coordination*.py`, `plan.py`, `execution.py`, `episodes.py`,
  `task_center.py`, `team_goal.py`, `team_plan.py`, `message_extractor.py`,
  `message_work_extractor.py`. *(System B no longer reaches them — the tool registry no
  longer registers `work_propose_*`.)*
- **Storage:** `storage/database.py` (schema + migrations) + incremental `migrations_*.py`.

### 2.3 Configuration (`config/settings.py`)
- `PAT_AI_PROVIDER` `ollama`; `PAT_AI_MODEL` `llama3.1`; base `http://localhost:11434`.
- `LOCAL_MODE=1` (trusted local identity); `LOCAL_USER` `local`.
- `PAT_DB_PATH` for test isolation.
- Planner timeout `PAT_PLANNER_TIMEOUT_SECONDS` (180s); runner parallelism
  `PAT_RUNNER_PARALLEL` (3); task retries `PAT_TASK_RETRIES` (3); live tests
  `PAT_RUN_LIVE_TESTS` (opt-in).

---

## 3. Database (structured workflow) — verified DDL

```
agent_projects
  id UUID PK, tenant_id, user_id, goal, status
    ('awaiting_plan_approval'|'running'|'awaiting_review'|'done'|'failed')
  , plan_json, created_at, updated_at

agent_tasks
  id TEXT PK (GLOBAL — unique across ALL projects), project_id, tenant_id, user_id
  , agent, instruction, depends_on (JSON array), status ('pending'|'running'|'done'|'failed')
  , review_status ('pending'|'approved'), deliverable_type, acceptance_criteria
  , output (prose), output_json (optional JSON), created_at, updated_at

pending_actions
  id/tenant_id/user_id, project_id, task_id, agent, type (e.g. 'ig_post'),
  payload (JSON), status ('pending'|'approved'|'executed'|'rejected'), result

activity_log
  id/tenant_id/user_id, timestamp, agent, event, details (JSON)   -- audit trail
```

**Observations (verified):**
1. `agent_tasks.id` is a **global primary key**, but the planner emits simple ids
   (`task-1`). Two projects can collide → we remap ids to `<project_id>::task-N` at insert
   (see §7.1). This is a real design smell.
2. No **enforced foreign keys** in SQLite — `project_id` is logical only. Integrity is
   application-enforced.
3. Scoping is **by column** (`tenant_id`, `user_id`) on every query.
4. Legacy tables (`workspaces`, `projects`, `goals`, `deliverables`, `team_goals`,
   `coordination_*`, `episodes`, `work_proposals`, etc.) still exist but are **no longer
   routed/rendered** — kept read-only by choice.

---

## 4. End-to-end flow (the one "happy path")

`App.tsx` → Home chat → **Delegate to the team** (`team_chat.tsx`):

1. `POST /projects` `{ goal }` → `StructuredProjectPlanner.plan()` prompts the model with
   `business_profile.md` + a JSON **schema**; validated by Pydantic `ProjectPlan` +
   `_validate_task_graph` (unique ids, registered agents, no outward actions); task ids are
   remapped to project-unique; rows inserted as `awaiting_plan_approval`.
2. **Human approves** `POST /projects/{id}/plan/approve` → `running`.
3. **Run** `POST /projects/{id}/run` → `ProjectRunner.run()` executes tasks in parallel
   dependency waves; each `_run_task` adds output-contract guidance, detects & **retries**
   known model-failure fallbacks, stores `output` (prose) + `output_json`. The frontend
   **polls every 4s** while `running` so per-task status updates live.
4. **Human reviews drafts** `POST /projects/tasks/{id}/review` (approve/edit/send_back).
   All done+approved → project `done`.
5. **Outward actions** → `pending_actions`; only a human approves/executes; the
   `action_executor.py` stub records without an external call.

---

## 5. Consolidation summary (what the last N commits did)

> Verified via git log + live checks. Test totals dropped from **849 → 469** backend and
> **133 → 58** frontend because the removed tests were legacy-only (System A) coverage.

| Area | Before | After |
|---|---|---|
| Backend routers | 17 (7 legacy) | 10 — all legacy routers gone |
| Frontend tabs | + Proposals, + Activity | Home · Projects · Task Center · Settings |
| Projects tab | Workspace browser + Proposals | `StructuredProjects` only |
| Chat | proposal mode + fallback to TeamGoal | delegate-to-team only; `POST /projects` failure is explicit |
| Tool registry | registered `work_propose_*` | simulation tools only |
| Agent manifests | declared `work_propose_*` | stripped (13 removed) |
| Live-Ollama tests | always ran | opt-in `PAT_RUN_LIVE_TESTS` |

**What remains "System A-shaped" (inert, not invoked):** legacy core modules (§2.2) and
legacy DB tables (§3.4). They compile and are never reached on the live path.

---

## 6. Security model (verified)

- **Identity middleware** (`api/app.py`): every non-public path needs either a valid
  `x-token` (verified → `user_id/tenant_id/role`) or local mode (trusted configured identity,
  `role=admin`); otherwise **fails closed** 401.
- **Human-only gates** (`_require_human`): only `role ∈ {user, admin}` may approve plans,
  run, review, edit, approve/execute actions. Agents get 403.
- **Scoping**: every project/task/action query filters by `tenant_id` AND `user_id`.
- **No outward side effects**: runner prompt forbids sending/post/DM/pay/book; planner rejects
  those instruction terms; `action_executor` is a stub.
- **Kill switch**: `PAT_AGENT_KILL_SWITCH`.

**Assessment:** strong for a local app (fail-closed identity, human gates, scoping). Risks:
relying on `role` from request state (fine today, brittle at scale), and `LOCAL_MODE=1`
trusts any local process as admin (acceptable on a personal machine, dangerous if networked).

---

## 7. Notable fixes/improvements (so you can critique)

### 7.1 Global task-ID collision
`agent_tasks.id` is a global PK but the model reuses `task-1`… → `UNIQUE constraint failed`
on a second project. Fix: `create_project` remaps ids to `<project_id>::task-N` and rewrites
`depends_on`. Alternatives: composite PK (cleaner, bigger migration) vs. prompting the model
(unreliable). Chosen: localized remap.

### 7.2 Model-failure placeholders marked "done"
When Ollama is overloaded, `BaseAgent` returns a graceful fallback string (no exception); the
runner recorded it as a valid draft. Fix: `_run_task` detects those fallbacks and **retries**
(default 3×) before recording; persistent failures → `failed` (honest). Trade-off: retries
extend wall time on a slow model.

### 7.3 Delegate routing + feedback + live progress
- Delegate-mode **Enter** used to fall through to the chat (`send()` excluded the delegate
  mode) → fixed to route through `POST /projects`.
- Delegating now shows a sent bubble + "Generating your team plan…" working state.
- Running now **polls** (`/projects/{id}` every 4s) so per-task status updates live instead
  of a frozen spinner.

---

## 8. Route map (verified, current)

Routers mounted in `api/app.py`:
- `/projects` — structured plan→approve→run→review→summary (the System B core).
- `/actions` — outward-action queue + approve/execute (stub).
- `/agents` — manifests, health, model-health.
- `/brand` — brands, facts, proposals/history.
- `/memory` — memory items, proposals, revoke.
- `/feedback` — feedback lessons.
- `/evaluations` — agent-output evaluation.
- `/team` (+ `/team/comm`, agent_comm, progress) — chat threads/messages + coordination/agent comm.
- `/progress`, `/team/progress`.

**Known residual:** the `/team` router still contains legacy `/plans`, `/milestones`,
`/dependencies` endpoints (System A) that back the still-present-but-unused coordination
code. These are candidates for the next cleanup pass (see §9, part 2).

---

## 9. Next steps / roadmap

### Done (committed)
- Structured workflow + output contracts; unique-task-id + retry hardening; live run polling;
  full backend System A removal; Projects tab → StructuredProjects; delegate routing/fix.

### Part 2 — finish "cleanly one system" (optional, high blast radius)
Delete the **inert** legacy core modules. Blockers (verified): four kept routers still import
them in *System A surfaces*:
- `agents.py` → `core.workspace` (plan→workspace bridge)
- `team.py` → `core.work_proposals` (legacy `/plans` endpoints)
- `evaluations.py` → `core.coordination_execution`
- `agent_comm.py` → `core.team_goal`

**Why it's more than a delete:** removing those modules requires first pulling those System A
features out of the kept routers, then deleting ~13 core modules + pruning their tests. High
risk, low functional gain (the code is already inert), reversible via git.

### Then: the actual product goals (unchanged priority)
1. **Make the local model faster/reliable enough** — the single biggest UX lever (a run can
   take ~12 min on `llama3.1:latest`). Options: tune Ollama (keep-alive/`num_ctx`/quantization)
   or swap task-execution to a faster model while keeping a larger one for planning.
2. **Deterministic agent-capability selection** — server-side map (e.g. campaign strategy →
   strategist, captions → communications) instead of letting the model pick agents.
3. **Stronger output-contract enforcement** — block/flag drafts missing required keys.
4. **Real integrations** — Email → Calendar → Instagram → browser → travel → booking/payment,
   each human-gated, only after simulation is proven.
5. **Durable learning** — propose preferences from user edits/feedback; store scoped lessons.

---

## 10. Failure scenarios & how to investigate

| Symptom | Likely cause | Check |
|---|---|---|
| Delegate "does nothing" | planner model call slow or errored | `curl /health`, `/agents/model-health`; `activity_log`; `agent_projects.status` |
| "I couldn't reach the language model" | Ollama overloaded/timeout | `curl :11434/api/generate`; watch runner retries |
| Plan/run 403 | role not human / token | `request.state.role`; token validity |
| `UNIQUE constraint failed: agent_tasks.id` | legacy ids + global PK (should be fixed by remap) | verify ids are `<project_id>::…` |
| Run looks frozen | was a synchronous 12-min POST | fixed: run is non-blocking + 4s poll |
| Task shows generic prose | agent-capability mismatch | inspect chosen agent vs task (part 2 roadmap) |
| Suite hangs on live tests | real Ollama slow | set `PAT_RUN_LIVE_TESTS` only for manual smoke runs |

**Hygiene:** `activity_log` (event + `details` JSON) is the audit trail — check it first.
Direct SQL: `sqlite3 data/pat.db "SELECT agent,event,substr(details,1,60) FROM activity_log ORDER BY rowid DESC LIMIT 15;"`

---

## 11. Concepts to internalize

- **Source of truth / canonical model** — one definition of "project/task/plan." The app now
  has one live system.
- **Stop routing vs. delete engine** — removing routers is low-risk and reversible; deleting
  service modules requires breaking every path to them first (the `team.py`/`agents.py` etc.
  dependencies are why the legacy core is still present).
- **Fail-closed vs fail-open** — deny unless explicitly permitted (this app's auth + approvals).
- **Deterministic vs probabilistic control** — the model is probabilistic; server-side
  validation (Pydantic, capability maps, output contracts) is where guarantees live.
- **Best-effort vs blocking enforcement** — reliability vs data-quality trade-off; pick per rule.
- **Proposal ≠ execution** — never let a draft be confused with a completed action.

---

## 12. Open questions for you (the critique)

1. Do you want to push **part 2** (delete the inert legacy core modules) for a zero-dead-code
   state, or are you comfortable with the current functionally-one-system state?
2. Is running the slower-but-capable 8B model acceptable, or should the execution model be
   swapped for speed?
3. Strict (blocking) or best-effort output validation for a flaky local model?

---

*Reflects the consolidated state at `c6c55af`. Re-run the cited tests/commands to re-verify
before relying on anything.*
