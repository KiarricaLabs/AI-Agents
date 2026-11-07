# Personal AI Team — Codebase Breakdown, Current State, and Roadmap

**Purpose:** a study-and-critique document that explains, end to end, how this system works
from browser to database, where it is today, and the smallest set of steps that gets it to
your full "approval-gated agentic operating system" vision — plus why those steps are the
right ones and what the alternatives are.

**How to read this:** every section separates **verified facts** (things I confirmed in the
code or a live check) from **assessment/judgment** (my engineering reasoning). Treat your
job as the critic: challenge the judgments, not the verified facts.

> Verified date: 2026-11-07. Backend suite: 849 tests passing. Frontend: 4 test files,
> 133 passing / 40 skipped, TypeScript + Vite build clean.

---

## 1. System at a glance

It is a **local-first web app** with a React/Vite frontend, a Python FastAPI backend, a
SQLite database, and a local Ollama model. There is no cloud dependency for the core loop.

```
Browser (React/Vite)
   │  fetch() → JSON
   ▼
FastAPI (api/app.py)  ── middleware: identity/auth
   │  routers/
   ▼
Service + core layers
   ├─ core/planner + runner  (structured workflow)
   ├─ orchestrator + agents  (legacy + dispatch)
   │
   ▼
ModelRouter → Ollama (localhost:11434)   ModelRouter → llm_client
   │
   ▼
SQLite (data/pat.db)  — via storage/database.py
```

Two distinct "operating systems" are currently mounted in the same app. **This is the single
most important finding** and it is the root of most confusion. See §5.

---

## 2. What exists today (verified)

### 2.1 Frontend (`frontend/src/`)
| File | Responsibility |
|---|---|
| `App.tsx` | Shell, tab navigation, state, renders panels. Largest file (~3600 lines). |
| `team_chat.tsx` | The Home chat. Modes: ask team / designate / propose / **delegate**. |
| `structured_projects.tsx` | The **new** project panel: plan → approve → run → review. |
| `coordination_panel.tsx` | The **legacy** TeamGoal coordination UI. |
| `command_center_sidebar.tsx` | Status counters and command sidebar. |
| `workflow_overview.tsx` | Educational workflow/state diagram. |
| `review_center.tsx`, `evaluation_panel.tsx`, `team_status.tsx`, `team_memory.tsx` | review / eval / agent status / memory screens. |
| `main.tsx`, `App.css`, `index.css` | bootstrap + styling. |

Tabs exposed in `App.tsx` navigation: Home, Projects, Proposals, Task Center, Activity,
Settings, plus agent/memory/review surfaces. The tabs are not one unified lifecycle — see §5.

### 2.2 Backend (`api/`, `core/`, `agents/`, `storage/`)
- **Router inventory** (see the route map in §8): `projects`, `actions`, `agents`, `brand`,
  `episodes`, `memory`, `feedback`, `evaluations`, `team`, `team/goals`, `work`, `workspaces`.
- **Core services:** `orchestrator.py` (dispatch), `model_router.py` + `llm_client.py`
  (Ollama), `project_planner.py` (structured plan), `project_runner.py` (dependency runner —
  parallel waves + retries), `output_contracts.py` (per-type JSON summaries),
  `action_executor.py` (safe outward-action stub), `brand.py`/`brand_scope.py` (brand facts),
  `auth.py` (tokens), `runtime.py` (wires registry/services into an orchestrator).
- **Agents (6):** `strategist`, `communications`, `tutor`, `soundboard`,
  `workspace_architect`, `executive_assistant`. Each has a `manifest.json` (identity,
  personality, capabilities, tools, permissions) and an `agent.py` (class). Shared base is
  `agents/base.py`.
- **Storage:** `storage/database.py` (schema + migrations), plus many incremental migration
  files (`migrations_*.py`). A `postgres.py` exists (optional non-SQLite path — not the live driver).

### 2.3 Configuration (`config/settings.py`)
- `PAT_AI_PROVIDER` default `ollama`; `PAT_AI_MODEL` default `llama3.1` (live server runs
  `llama3.1:latest`); base URL `http://localhost:11434`.
- `LOCAL_MODE` default `1` (trusted local identity); `LOCAL_USER` default `local`.
- `DB_PATH` default `data/pat.db`; test isolation requires `PAT_DB_PATH`.
- Planner timeout default 180s (`PAT_PLANNER_TIMEOUT_SECONDS`); runner parallelism default
  3 (`PAT_RUNNER_PARALLEL`); task retries default 3 (`PAT_TASK_RETRIES`).

---

## 3. Database schema (structured workflow)

The **new** workflow uses four tables (verified DDL):

```
agent_projects
  id          TEXT PRIMARY KEY      -- uuid
  tenant_id   TEXT NOT NULL         -- multi-tenancy scope
  user_id     TEXT NOT NULL         -- per-user scope
  goal        TEXT NOT NULL
  status      TEXT  'awaiting_plan_approval'|'running'|'awaiting_review'|'done'|'failed'
  plan_json   TEXT NOT NULL         -- the full structured plan (goal + tasks array)
  created_at / updated_at TEXT

agent_tasks
  id                  TEXT PRIMARY KEY   -- GLOBAL pk; must be unique across ALL projects
  project_id          TEXT NOT NULL       -- FK → agent_projects.id (not an enforced FK in SQLite)
  tenant_id / user_id TEXT NOT NULL
  agent               TEXT NOT NULL       -- e.g. 'strategist'
  instruction         TEXT NOT NULL
  depends_on          TEXT   '[]'          -- JSON array of task ids (dependency graph)
  status              'pending'|'running'|'done'|'failed'
  review_status       'pending'|'approved'
  deliverable_type    TEXT   'draft'       -- e.g. 'positioning_statement','content_calendar'
  acceptance_criteria TEXT   '[]'
  output              TEXT                -- readable prose the human reviews
  output_json         TEXT                -- optional structured summary (JSON), may be NULL
  created_at / updated_at TEXT

pending_actions
  id/tenant_id/user_id, project_id, task_id
  agent, type (e.g. 'ig_post'), payload(JSON), status 'pending'|'approved'|'executed'|'rejected'
  result

activity_log
  id/tenant_id/user_id, timestamp, agent, event, details(JSON)  -- audit trail
```

**Key observations (verified):**
1. `agent_tasks.id` is a **global** primary key. The planner emits simple ids (`task-1`);
   two projects can therefore collide. We fixed this by remapping ids to
   `<project_id>::task-N` at insert (see §7.1). This is a real design smell worth knowing.
2. There are **no enforced foreign keys** in SQLite DDL — `project_id` is a logical
   relationship only. Integrity is enforced in application code, not the database.
3. Scoping is done **by column** (`tenant_id`, `user_id`) on every query, not by row-level
   permissions. Correct, but easy to forget.

The **legacy** workflow uses many more tables: `workspaces`, `projects`, `goals`,
`assignments`, `deliverables`, `deliverable_versions`, `work_proposals`,
`goal_update_proposals`, `tasks`, `task_events`, `episodes`, `team_goals`,
`team_goal_steps`, `coordination_*`, `brand*`, `memory_items`, `conversation_*`,
`agent_feedback`, `users`, `tenants`, `refresh_tokens`, etc.

---

## 4. End-to-end data flow (the "happy path" you want)

Trace of an On Us Instagram campaign through the **new** structured workflow:

1. **UI** `App.tsx` → delegate → `team_chat.tsx` calls `POST /projects` with `{"goal": …}`.
2. **API** `api/routers/projects.py::create_project` → middleware already set identity
   (`tenant_id`, `user_id`, `role=admin` in local mode). `_require_human()` passes.
3. **Planner** `StructuredProjectPlanner.plan(goal)` builds a prompt with `business_profile.md`
   injected, calls `ModelRouter.complete()` → Ollama with a JSON **schema** so it returns
   structured JSON (goal + ≤6 tasks; each task: id, agent, instruction, depends_on,
   deliverable_type, acceptance_criteria). Validated by Pydantic `ProjectPlan` +
   `_validate_task_graph` (unique ids, registered agents, no outward actions).
   **On success** task ids are remapped to project-unique ids; project + tasks inserted with
   status `awaiting_plan_approval`.
4. **UI** `structured_projects.tsx` renders the plan (tasks, agents, dependencies).
5. **Human approves** `POST /projects/{id}/plan/approve` → project `running`.
6. **Run** `POST /projects/{id}/run` → `ProjectRunner.run()`. It builds a `runtime`
   (orchestrator + agents + memory + brand + Ollama router). Tasks are executed in
   **parallel dependency waves** (independent tasks overlap); each `_run_task` calls
   `runtime.dispatch(agent, prompt, ctx)`. If the agent returns a known model-failure
   fallback string, it **retries** (default 3×). On success the task is written `done` +
   `review_status=pending`; `output` = prose, `output_json` = parsed structured summary.
7. **UI reviews drafts** — each done task shows its prose (JSON block stripped).
8. **Human approves/rejects/edit/send_back** draft via
   `POST /projects/tasks/{task_id}/review`. When all done+approved → project `done`.
9. **Outward actions** — agents may *queue* a `pending_action`; only a human approves/executes
   it via the `actions` router, and the `action_executor.py` **stub** records it without
   actually calling any external service.

**Verified live run:** created 6-task campaign → approved → ran (~12 min due to slow model;
retries recovered all 6 tasks with real content + JSON, 0 error placeholders) → approved all
6 drafts → summary "6 of 6 task drafts approved".

---

## 5. Current state — the central architectural problem

> Most important judgment in this document. Everything below follows from it.

**There are two overlapping workflow engines running at the same time, sharing the same UI.**

### System A — Legacy TeamGoal (older)
```
Chat → TeamGoal draft → proposal → agent-prose plans → coordination plan
     → approval → execution episodes → deliverable review
```
Tables: `team_goals`, `team_goal_steps`, `coordination_*`, `episodes`, `deliverables`,
`work_proposals`. UI: `coordination_panel.tsx`.

### System B — Structured Projects (newer, aligned with your plan)
```
Goal → structured JSON plan → human approves plan → dependency runner
     → agent drafts → human reviews drafts → human approves actions → coordinator summary
```
Tables: `agent_projects`, `agent_tasks`, `pending_actions`, `activity_log`.
UI: `structured_projects.tsx`.

**Evidence they are both live (verified counts in the real DB):**
- `agent_projects = 3`, `agent_tasks = 18` (System B, new workflow)
- `team_goals = 12`, `team_goal_steps = 33` (System A, legacy workflow)

These are two different notions of "project", "task", "plan", "approval", and "execution".
The UI renders both (Home shows both the legacy Coordination panel and the new Structured
Projects panel; Projects lists both). The statuses don't overlap, the storage doesn't
overlap, and the user can't tell which workflow actually ran.

This is why the app can feel like it "isn't working" even when both systems function: a
request may be routed to one, but the UI shows the other, and the semantics differ.

---

## 6. Security model (verified)

- **Identity middleware** (`api/app.py`): every non-public path requires either
  a) a valid `x-token` (production, `verify_token`) → sets `user_id/tenant_id/role`, or
  b) local mode (`LOCAL_MODE=1`) → trusted configured identity with `role=admin`.
  c) otherwise → **fails closed** with 401.
- **Human-only gates** (`_require_human` in the project/action routers): only `role ∈
  {user, admin}` may approve plans, run, review, edit plan, approve/execute actions. Agent
  role gets 403. **Verified by test** `test_non_human_gets_403_on_human_only_mutations`.
- **Multi-tenancy scoping**: every workspace/project/task/action query filters by
  `tenant_id` AND `user_id`. **Verified** by foreign user/tenant → 404 tests.
- **No outward actions**: `project_runner` prompt explicitly forbids sending/post/DM/pay/book;
  planner validation rejects those instruction terms; `action_executor` is a stub.
- **Kill switch**: `PAT_AGENT_KILL_SWITCH` halts the runner (env-guarded).
- **Credential vault**: `storage/credentials.py`; real tokens not present in local mode.

**Assessment:** the security posture is strong for a local app — fail-closed identity, human
gates, scoping, and no real outward side effects. The two real risks are (a) relying on
`role` from request state rather than per-endpoint capability checks (fine today, grows
brittle), and (b) `LOCAL_MODE=1` trusts any local process/session as admin — acceptable for a
personal machine, dangerous if ever exposed on a network.

---

## 7. Work already done (the hardening passes) — so you can critique them

These were the last two changes. Read them as examples of *definable engineering judgment*.

### 7.1 Global task-ID collision (bug + fix)
**Problem (verified):** `agent_tasks.id` is a global PK, but the planner emits simple ids
(`task-1`). A second project from the same prompt collides → `UNIQUE constraint failed`.

**Fix:** in `create_project`, remap every `task.id` to `<project_id>::task-N` and rewrite
`depends_on` refs accordingly (same project). Keeps the planner unchanged, guarantees global
uniqueness, and returns the remapped ids so the UI/later calls agree.

**Alternatives considered:**
1. **Composite PK `(project_id, id)`** — cleaner relational semantics, but requires a
   migration touching every caller + all downstream joins. Higher blast radius now.
2. **Fix it in the planner prompt** ("use unique ids") — unreliable; the model reuses ids.
3. **Remap at insert (chosen)** — smallest, localized change; id is an opaque handle from the
   app's perspective. Trade-off: ids are longer and not human-meaningful.

### 7.2 Model-failure placeholders recorded as "done" (bug + fix)
**Problem (verified in a live run):** when Ollama is overloaded, `BaseAgent` returns a
graceful fallback string ("I couldn't reach the language model…") as a *normal reply*, no
exception. The runner treated any non-empty reply as a valid draft and wrote status `done`.
3 of 6 tasks were error placeholders in the first live run.

**Fix:** `_run_task` detects those known fallback strings and **retries** (default 3×) before
recording; if exhausted, the task/project is marked `failed` (honest, visible).

**Alternatives considered:**
1. **Fail immediately (no retry)** — honest but brittle; a single transient timeout kills
   the whole project.
2. **Reduce parallelism to 1** — the model serializes anyway, but sacrifices the (modest)
   overlap benefit and doesn't fix a genuinely flaky model.
3. **Retry + detect fallback (chosen)** — recovers transient contention; only truly
   persistent failures hard-fail.

**Trade-off / open issue:** retries multiply model calls, which on a slow model extends wall
time (the run exceeded a 700s HTTP timeout and had to be polled). This trades latency for
completeness. The real lever is a faster/capable-enough model (see roadmap, step 2).

---

## 8. Route map (verified inventory)

Routers (prefix | primary purpose):
- `/projects` — structured plan→approve→run→review→summary (the new workflow)
- `/actions` — outward-action queue + approve/execute (stub)
- `/agents` — agent manifests, health, model-health
- `/brand` — brands, brand facts, brand proposals/history
- `/episodes` — legacy execution episodes
- `/memory` — memory items, proposals, revoke
- `/feedback` — feedback lessons
- `/evaluations` — evaluation of agent outputs
- `/team`, `/team/comm`, `/team/goals`, `/team/goals/plans`, `/team/progress` — legacy team/coordination
- `/work` — workspaces/projects/goals/assignments/deliverables/proposals (legacy)
- `/workspaces` — workspaces CRUD

Notable endpoints on `/projects`: `POST ""` (create), `GET ""` (list), `GET /{id}`,
`GET /{id}/summary`, `POST /{id}/plan/approve|reject|edit`, `POST /{id}/run`,
`POST /tasks/{id}/review`, `POST /tasks/{id}/rework`.

**Assessment:** the surface is large because it carries one legacy system (work/team/goals/
episodes/deliverables) and the new structured one. Consolidation is roadmap step 1.

---

## 9. Next steps to complete the plan — prioritized with rationale

These are ordered by leverage (biggest correctness/UX gain per unit of effort) and by
"what blocks the next thing."

### Step 1 — Make the structured workflow the single canonical path (highest priority)
Remove silent fallback to legacy TeamGoal in `team_chat.tsx` (currently, if `POST /projects`
fails it silently creates a TeamGoal). A failure should be **visible**. Then stop rendering
the legacy coordination UI on Home/Projects for new work.

**Why it's the right choice:** your plan is a single plan→approve→execute model. Two engines
cannot be the source of truth. Until this is done, every new feature must be built twice or
debugged ambiguously. This is the root of "it feels like it's not working."

**Alternative:** keep both but tag clearly ("experimental"). Trade-off: doubles maintenance,
leaves the ambiguity that causes the current confusion. Not recommended beyond a transition.

### Step 2 — Make the local model fast/reliable enough (biggest UX lever now)
The 8B `llama3.1` is the bottleneck (runs took ~12 min; retries extend them). Options:
1. **Tune `llama3.1`/Ollama** — keep-alive, larger `num_ctx`, KV cache, quantization.
   No code change; but limited upside.
2. **Swap to a faster model** for task execution (e.g. a 4–7B efficient model) and keep a
   larger model (or same) only for planning. Requires a model-role config; small change.
   Best speed/quality trade-off. **My recommendation.**
3. **Use a cloud model** — violates your local-only requirement. Rejected.

**Why before integrations:** a slow/flaky model makes the whole system feel broken at every
step, and retries hide latency. Speed is foundational UX, not polish.

### Step 3 — Add deterministic agent-capability selection
Today the planner lets the model pick agents per task (validated only that the name exists).
A `tutor` doing "content strategy" is evidence of weak matching. Add a server-side
capability map (e.g. `campaign strategy → strategist`, `captions/calendar →
communications`, `risk → soundboard`) and reject invalid assignments deterministically.

**Why:** removes the largest source of low-quality output without touching the model. The
model proposes; server enforces. **Alternative:** keep pure model judgment — simpler but
unreliable.

### Step 4 — Enforce stronger structured output contracts
Extend `output_contracts.py` so each `deliverable_type` requires specific keys and the
runner *blocks* (or visibly flags) tasks whose JSON is missing — currently it's best-effort
and silently tolerates missing structure. Pair with **output schema validation** before a
draft enters review.

**Trade-off:** strictness reduces false "done" states but can reject drafts on a flaky model;
keep a "best-effort + flag" mode, not a hard fail.

### Step 5 — Unify the UI around one lifecycle
Move to consistent tabs: Home (active project), Projects, Approvals, Runs, Agents, Memory,
Settings. Every surface should reference the same `project_id` chain:
`project → tasks → outputs → reviews → actions → executions → summary`.

**Why:** the previous audit's #1 usability problem is duplicated, ambiguous panels.

### Step 6 — Add real integrations (only after simulation is solid)
In order: Email → Calendar → Instagram draft/publish → Browser automation → Travel search →
Booking/payment (each with its own approval gate). Every integration must preserve
`agent proposes → human reviews → human approves → executor acts → result logged`. Keep the
same `pending_actions` + `action_executor` pattern; swap the stub for a real adapter.

**Why after everything else:** you explicitly want the workflow trained and proven locally
before credentials. Adding real side effects while the model is slow and agent selection is
weak multiplies risk and noise.

### Step 7 — Add durable learning (your "learn and adapt" requirement)
Build the loop `user edits/approves/rejects → system proposes a preference → user approves →
stored scoped lesson → retrieved in future tasks`. Prefer **scoped lessons** (brand-specific
vs personal vs global) and never silently rewrite behavior. Extend the existing `memory`
+ `feedback` infra.

---

## 10. Why these steps and not others

- **Do the correctness/semantics first** (Step 1, one workflow) before building on a
  bifurcated foundation. Building features on two systems compounds debt.
- **Do the model bottleneck before integrations** because every future feature is judged
  against a slow model; it poisons UX and testing.
- **Deterministic capability selection before deeper prompts**, because it's the cheapest
  way to raise output quality and is testable, whereas "better prompts" are not reliably
  testable.
- **Real integrations last**, because they introduce irreversible side effects and
  credential handling — exactly what you want to defer until the loop is proven.

**Trade-offs accepted:** Steps 3–4 add server-side strictness (more rules to maintain) in
exchange for much higher reliability/trustworthiness. Step 1 temporarily makes failures
visible (feels worse short-term) to remove a genuinely worse hidden fallback.

---

## 11. Failure scenarios & how to investigate

| Symptom | Likely cause | How to check |
|---|---|---|
| Request "does nothing" | Planner/model call slow or a fallback path | `curl /health`, `/agents/model-health`; check `activity_log` and `agent_projects.status` |
| "I couldn't reach the language model" | Ollama overloaded/timeout | `curl :11434/api/generate`; watch retries in runner |
| Plan approval/run 403 | role not human / wrong token | `request.state.role`; token validity |
| `UNIQUE constraint failed: agent_tasks.id` | old planner ids + global PK | check for legacy task-ids colliding across projects |
| Task shows generic prose | agent-capability mismatch | inspect the planner's chosen agent vs task; Step 3 |
| Run hangs | slow model + retries | poll `agent_tasks.status`; tail `/tmp/pat-backend.log` (or uvicorn log) |
| Foreign rows visible | scoping bug | check `tenant_id`/`user_id` filters in the query |

**Investigation hygiene:** the `activity_log` table is your audit trail (event +
`details` JSON) — always check it first. The DB is queryable directly:
`sqlite3 data/pat.db "SELECT * FROM activity_log ORDER BY rowid DESC LIMIT 20;"`.

---

## 12. Concepts to internalize before continuing

- **Source of truth (canonical model):** exactly one place defines "a project/task/plan".
  Two engines = no truth. This is Step 1's reason.
- **Fail-closed vs fail-open:** fail-closed (deny unless explicitly permitted) is the safer
  default; this app is fail-closed for auth and (mostly) for approvals.
- **Deterministic vs probabilistic control:** the model is probabilistic; server-side
  validation (Pydantic, capability maps, output contracts) is where you put guarantees.
- **Idempotency & global uniqueness:** a local model can't be trusted to emit unique ids;
  the application must enforce invariants.
- **Best-effort vs blocking enforcement:** trade-off between reliability (never break a
  flaky-model run) and data quality (reject malformed output). Design each rule consciously.
- **Separation of "proposal" from "execution":** your whole plan is this principle — never
  let a draft be confused with a completed/done action.

---

## 13. Open questions for you (the critique)

1. Do you agree one canonical workflow is the first priority, or would you rather fix model
   speed first because it determines whether you'll even keep using the app?
2. Is strict (blocking) or best-effort output validation the right default for your flaky
   8B model, given your tolerance for re-runs?
3. Should agent selection stay model-driven (fast to change) or move to a server-side
   capability map (reliable but more rules to maintain)?

---

*End of document. Numbers are from a live snapshot; re-run the listed SQL/test commands if
you want to re-verify anything before relying on it.*
