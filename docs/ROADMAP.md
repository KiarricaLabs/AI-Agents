# Personal AI Team — Roadmap to an Agentic AI Operating System

Tracked plan for moving the current **one-system structured workflow** to your full
approval-gated Agentic AI Operating System. Companion to
[CODEBASE_BREAKDOWN_AND_ROADMAP.md](CODEBASE_BREAKDOWN_AND_ROADMAP.md) (the codebase overview).

**How to read:** each phase has a goal, ordered tasks, *why* (the leverage), and success
criteria. Check boxes off as completed. Rationale notes record decisions.

> Status baseline: backend 469 tests OK, frontend 58/12, working single system
> (delegate → plan → approve → run → review → done), human-gated, local-only.

---

## North star (from your spec)
A team of agents that: understands objectives → coordinates/delegates → produces a plan →
**you approve** → they execute → you review → they report. They **learn your and On Us's
preferences**, run **locally**, and can eventually act on the internet (email, Instagram,
travel, research) — every real action gated for your approval.

---

## Phase A — Make the core excellent (do first)
**Goal:** the plan→run loop is fast and the drafts are high-quality. *Everything you want to
*feel* agentic is judged against this.*

### A1 — Model speed & reliability ✅ APPROVED (approach decided)
**Decision (2026-11-07):** use a **small/fast execution model** for task execution, keeping a
larger (8B) model for planning. Rationale: best "fast *and* good" balance; keeps local-only.

- [ ] Benchmark current plan + run timings on `llama3.1:latest` (baseline).
- [ ] Tune Ollama (keep-alive, `num_ctx`, KV cache, quantization).
- [ ] Add **model-role config**: planner model vs executor model (in `config/settings.py` +
  `model_router`).
- [ ] Select/test a fast executor model (e.g. a 4–7B) for task output quality.
- [ ] Re-benchmark: target a full plan+run well under the current ~12 min.
- **Success criteria:** a normal campaign project plans and runs to review in minutes; the
  retries added in #26e9c8e rarely trigger.

### A2 — Deterministic agent-capability selection
**Goal:** server code (not just the model) decides which agent fits a task.

- [ ] Define a capability map in one place (`campaign strategy→strategist`,
  `captions/calendar→communications`, `risk→soundboard`, ...).
- [ ] In the planner/runner, reject or auto-route mis-assigned agents deterministically.
- [ ] Unit tests for the map.
- **Success criteria:** no more `tutor→content strategy` mismatches; selection is testable.

### A3 — Stronger output-contract enforcement
- [ ] Require per-`deliverable_type` keys; **block** (or visibly flag) drafts that omit them.
- [ ] Validate `output_json` before a draft enters review.
- **Trade-off:** strictness may reject drafts on a flaky model → provide a "best-effort + flag"
  toggle, not a hard fail.

### A4 — (optional) delete inert legacy core modules
- [ ] Pull System A surfaces out of `agents.py` (→core.workspace), `team.py`
  (→core.work_proposals), `evaluations.py` (→core.coordination_execution),
  `agent_comm.py` (→core.team_goal).
- [ ] Delete the ~13 inert legacy core modules + prune their tests.
- **Why** zero-dead-code clarity. **Risk:** high blast radius; low functional gain (already inert).

---

## Phase B — Real operational autonomy ("agentic" behavior)
**Goal:** the system drives work itself, still approval-gated.

### B1 — Async runner + durable queue
- [ ] Run in a background worker; cancel/resume; survive a backend restart.
- **Success:** a run in progress survives a server restart and continues.
### B2 — Scheduled / event-triggered projects
- [ ] "Every Monday: draft the week's content" — still gated for approval before execution.
### B3 — Unified approval center
- [ ] One surface for plan / draft / outward-action approvals + human escalation.

---

## Phase C — Learning & personalization (your "train the agents to me")
**Goal:** the team learns your style and On Us, durably and transparently.

### C1 — The preference loop
- [ ] On edit/approve/reject, propose a lesson → you approve → store scoped
      (brand / personal / global) → retrieve on later tasks.
- [ ] Reuse existing `memory` + `feedback` infra; never silently rewrite behavior.
- **Success:** a "make it less promotional" correction changes future On Us drafts measurably.
### C2 — Multi-brand context switching
- [ ] A brand registry; the team adapts to a new brand without losing On Us.

---

## Phase D — Real integrations (real-world tasks), each human-gated
Order by consequence: **Email → Calendar → Instagram draft/publish → Browser automation →
Travel search → Booking/Payment** (last always requires an extra confirmation gate).
Swap `action_executor` stub for real adapters one at a time, keeping `pending_actions` +
approval. **Why last:** irreversible side effects + credentials — deferred until the loop is
proven (matches your original intent).

---

## Phase E — Media generation (later)
- [ ] Local image generation as a Content/Creative tool.
- [ ] Driven by the active brand profile + visual guidelines; review before public use.

---

## Sequencing rationale (why these first)
1. **A first** — speed/quality decide whether you'll keep using it and whether agents can
   *demonstrate* they understand your style.
2. **B before D** — real integrations need durable, resumable runs.
3. **C before D** — agents should know your preferences before acting online.
4. **D/E last** — introduce irreversible actions + credentials you wanted deferred.

## Priorities / decisions to revisit
- [ ] Confirm which fast executor model to use (under A1).
- [ ] Strict vs best-effort output validation (A3).
- [ ] Part 2 (A4): worth it, or leave inert?

*Companion: CODEBASE_BREAKDOWN_AND_ROADMAP.md. Verified baseline at `c6c55af`.*
