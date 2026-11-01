# M8 Plan — Agent Runtime: LLM-backed agents with model routing and tool execution

> Status: **PLANNING ONLY — no implementation authorized yet.**
> This document describes the approved M8 scope. It modifies nothing.

## 1. Overview and rationale

M0–M7 delivered a complete, tenant-safe *infrastructure*: memory, tasks, episodes, delegation, messaging, workspace/project/goal/assignment/deliverable, policy, auth, observability, backup, and a React frontend. What is missing is that **the six agents are stubs** — their `run()` methods return a hardcoded string and never call a model, read memory, or use a tool.

M8 makes the six agents genuinely operational by adding three layers on top of the existing services:

- **ModelRouter** — a provider-agnostic model-routing interface with **Ollama as the only active provider** (local-first, no silent cloud fallback, processing location reported).
- **Agent runtime** — the agents call the model, grounded in their existing manifest identities and manifest-scoped memory, and produce validated structured output.
- **ToolRegistry** — permission-gated, audited **local-only** tools.

## 2. Reused vs. new vs. deferred

### Reused (existing, unchanged unless noted)

| Component | Path | Reused for |
|---|---|---|
| `MemoryService` | `core/memory.py` | scoped reads (`list_profile`, `get_private`, `read_private`), proposals (`propose`/`approve`/`reject`/`revoke`/`expire_proposals`), audit (`audit_history`) |
| `TaskService` | `core/tasks.py` | task lifecycle, retry/cancel/idempotency, policy enforcement, `task_events` |
| `EpisodeService` | `core/episodes.py` | checkpointing, recovery, cancellation, `episode_events` |
| `DelegationService` | `core/delegation.py` | cross-agent delegation with permission intersection and audit |
| `MessageBus` | `core/messagebus.py` | tenant-scoped inter-agent messages |
| Workspace/Project/Goal/Assignment/Deliverable | `core/workspace.py` | deliverable creation + versioning + immutable approvals |
| `PolicyEngine` / `PolicyEnforcer` | `core/policy.py`, `core/policy_enforcer.py` | default-deny authorization on dispatch, memory, tools |
| Auth, rate limiting, tracing, metrics, backup | `core/auth.py`, `core/ratelimit.py`, `core/tracing.py`, `core/metrics.py`, `core/backup.py` | unchanged |
| `AgentRegistry` | `agents/registry.py` | manifest load + schema validation (7 keys) |
| Six agents + manifests | `agents/*/agent.py`, `agents/*/manifest.json` | identities, capabilities, model, memory scope, tools, permissions, delegation |
| `LLMClient` (Ollama path) | `core/llm_client.py` | the actual Ollama HTTP call (wrapped by ModelRouter) |
| DB (`Database`) | `storage/database.py` | tenant-aware persistence |

### New (to be implemented in M8)

| Component | Path (new) | Purpose |
|---|---|---|
| `ModelRouter` | `core/model_router.py` | provider-agnostic model selection/execution; Ollama only; timeout/retry; processing-location reporting |
| `AgentRuntime` (runner) | `core/agent_runtime.py` | shared execution logic: prompt assembly, memory grounding, tool dispatch, output validation |
| `ToolRegistry` + `Tool` base | `core/tools.py` | register/dispatch local tools; permission + audit |
| Local tools | `core/tools/local/*.py` | deterministic, offline tools (see Phase C) |
| Output validators | `agents/schemas.py` | structured-output schemas per agent (Pydantic; already a dependency) |
| `tool_executions` table | additive migration | audit trail for tool calls |

### Deferred (explicitly out of M8)

- **Cloud providers (OpenAI/Anthropic):** interface designed for, **not implemented**.
- **External/network tools:** `web_search`, `email`, `calendar` — require explicit opt-in + credentials in a future milestone.
- Multi-user SaaS auth changes, Postgres production promotion, Redis.

## 3. Architecture

```
                    ┌────────────────────────────────────────────┐
                    │              Orchestrator                  │
                    │  policy check → registry → AgentRuntime    │
                    └───────────────┬────────────────────────────┘
                                    │ dispatch(agent, task, context)
   ┌───────────────┬───────────────┼───────────────┬──────────────────┐
   ▼               ▼               ▼               ▼                  ▼
MemoryService   AgentRuntime   ModelRouter     ToolRegistry      Task/Episode
(manifest-        (prompt,     (Ollama)         (local tools)     (lifecycle)
 scoped read/       validate)                                      audit)
 propose)
   │               │               │
   └───────────────┴───────────────────────────► produces structured result
                                                    → Deliverable → approval
```

Key principle: **the Orchestrator and TaskService stay the same shape** — `dispatch()` only changes what it injects into the agent (a real `MemoryService`, `ModelRouter`, and `ToolRegistry` instead of `None`/nothing). No service is duplicated.

## 4. Component responsibilities

### 4.1 ModelRouter (`core/model_router.py`)

- Interface `complete(agent_id, prompt, system="", context=None) -> ModelResult`, where `ModelResult` carries the text **and** `location` (e.g. `"local:ollama:llama3.1"`).
- Resolves each agent's `model` block from its manifest (`{"provider":"ollama","model":"llama3.1"}`).
- **Only `ollama` is registered.** Unknown/cloud providers raise a loud, explicit error (no silent fallback, no cloud routing).
- Timeout and bounded retry on transient failures. Retries are within the *same* local provider only — never upgrade to cloud.
- Emits a tracing span and records `location` (processing location) on every call.
- Designed so an `openai`/`anthropic` adapter can be added later behind the same interface; those adapters are **not** created in M8.

### 4.2 Agent runtime (`core/agent_runtime.py`) + `agents/base.py`

- `BaseAgent` gains typed deps: `memory: MemoryService`, `router: ModelRouter`, `tools: ToolRegistry` (constructor-injected by the Orchestrator).
- `AgentRuntime` is shared logic each agent delegates to:
  1. Load manifest identity/capabilities.
  2. Read **manifest-scoped** memory.
  3. Build the system prompt (role + personality + capabilities + memory context).
  4. Call `ModelRouter.complete(...)`.
  5. Optionally invoke permitted local tools (Phase C).
  6. Validate structured output against the agent's schema (`agents/schemas.py`).
  7. Propose (not commit) memory updates when permitted.
- The six agent classes become thin: they declare their `name` + an output schema + any agent-specific prompt instructions; the heavy lifting is in `AgentRuntime`. Existing `run()` signatures are preserved.

### 4.3 Memory-scope mapping (Phase B)

Manifest `memory` uses categories like `profile`/`goals`/`notes`; `MemoryService` stores `profile` and agent-private memory. M8 documents and enforces an explicit mapping:

| Manifest `memory.read`/`write` | Backing call |
|---|---|
| `profile` | `MemoryService.list_profile(user_id)` |
| `notes` | `MemoryService.get_private(agent_id, user_id)` |
| `goals` | workspace goals (read-only) via existing GoalService |

- `approval_required: true` (all current manifests) → agents only ever call `propose(...)`; the user approves via the existing proposal workflow. **No automatic promotion.**
- Cross-agent private memory requires `read_private(..., permission=True)`; otherwise `PermissionError` (existing behavior preserved).

### 4.4 ToolRegistry (`core/tools.py`)

- `register(name, tool)`, `invoke(agent, name, args, context)`.
- Every invocation: policy check (`policy.allow(agent, "tool", name)`), tenant/user scoping, and an audit row in `tool_executions`.
- Tools are **local and deterministic**; the set for M8 is small and safe (Phase C). A tool declared in a manifest but not registered → explicit error, never silent no-op.

## 5. Execution lifecycle

1. User creates/assigns work via existing `TaskService`/workspace services (unchanged).
2. `TaskService.run()` executes the task (policy already enforced at task level). Inside `executor`:
3. `Orchestrator.dispatch(agent, task, context)`:
   - policy check on dispatch (existing),
   - resolve manifest via `AgentRegistry`,
   - instantiate the agent with `memory`, `router`, `tools`.
4. `AgentRuntime` reads scoped memory → builds prompt → `ModelRouter.complete` (Ollama) → optional local tool call → validates output → proposes memory.
5. Result is returned as a structured dict; the task marks `done` (or `failed` on error) with an event.
6. If the work maps to a deliverable, the result is attached to the existing Deliverable service and flows through approval.

**Failure isolation:** each task already runs inside its own `try/except` in `TaskService.run()`; M8 keeps this. One agent/model/tool failure marks only that task `failed` and never propagates to other tasks.

## 6. Security model

- **Tenant/user isolation** enforced on every memory read, tool call, and model result storage (all existing calls already scope by `tenant_id`/`user_id`).
- **Default-deny policy** applied to dispatch (existing), and extended to tool invocation. Missing/invalid policy denies (existing `PolicyEngine` behavior).
- **No automatic memory promotion** — agents only `propose`; sensitive/temporary/low-confidence content is already rejected by `MemoryService.propose`.
- **No silent cloud routing** — only Ollama is reachable; anything else fails loudly and reports `location="error"`.
- **Human approval** for consequential actions preserved (deliverable approvals, memory approvals).
- Secrets are never placed in prompts, tool parameters, logs, or metrics (existing secret-key filtering in `TaskService`/`EpisodeService` reused for tool parameters).

## 7. Migration strategy

- **Additive only.** The single new artifact is the `tool_executions` table:
  - `id, tenant_id, user_id, agent_id, task_id (nullable), tool, params_hash, status, error (nullable), location, created_at`.
  - Indexed on `(tenant_id, created_at)` and `(agent_id)`.
  - A reversible down-migration (`DROP TABLE tool_executions`) is documented; it is a leaf table with no foreign keys from existing tables.
- No change to existing tables, columns, or constraints. SQLite remains the default.

## 8. Implementation sequence

Each phase is independently verifiable and shippable; later phases do not break earlier ones.

### Phase A — ModelRouter + LLM wiring
- Implement `core/model_router.py` (Ollama adapter only) and `ModelResult.location`.
- Wire `BaseAgent`/`AgentRuntime` to call the model and wrap `LLMClient.complete`.
- **Acceptance:** routing from manifest works; `location` is reported on every call; timeout/retry covered; requesting a non-Ollama provider raises loudly.
- **Verify:** mocked-LLM unit tests for routing/timeout/retry/location; existing 86 backend + 19 Vitest + 7 Playwright still pass.

### Phase B — Memory-grounded agents
- Implement the manifest→`MemoryService` scope mapping; agents read scoped memory and build persona-grounded prompts; propose (not commit) memory.
- **Acceptance:** each agent returns a real model-grounded structured result; memory reads honor scope and tenant/user; cross-agent private reads denied; proposals created with `approval_required`, never auto-promoted.
- **Verify:** mocked-LLM tests asserting memory was included in the prompt and proposals surfaced to the approval queue.

### Phase C — ToolRegistry + local tools
- Implement `ToolRegistry`, `Tool` base, and a minimal set of safe local tools (e.g. a deterministic calculator + local datetime). Add the `tool_executions` migration.
- **Acceptance:** permitted tools execute and audit; unpermitted/unknown tools denied; no network I/O anywhere.
- **Verify:** tool authorization tests, audit-row assertions, tenant-isolation tests, and a no-network assertion.

### Phase D — End-to-end orchestration + comprehensive tests
- Wire the full path `task → agent → model → memory → tool → deliverable`, with per-task failure isolation.
- **Acceptance:** a full mocked end-to-end run produces a validated, deliverable-bound result; a failing agent marks only its own task failed.
- **Verify:** end-to-end integration tests + Ollama smoke tests (skipped automatically when Ollama is unavailable).

## 9. Acceptance criteria (top-level)

1. All six agents operational with their existing identities/manifests.
2. Local-first: Ollama is the only active provider; no silent cloud fallback; `location` reported for every execution.
3. Memory is manifest-scoped, proposal-gated, tenant/user-isolated; no automatic promotion.
4. Tools are local-only, permission-gated, audited.
5. Structured outputs are validated per agent.
6. One agent's failure does not affect unrelated tasks.
7. **All existing 86 backend + 19 Vitest + 7 Playwright tests keep passing.**

## 10. Test matrix

| Concern | Test type | Phase covered |
|---|---|---|
| Provider selection / routing | unit (mocked model) | A |
| Timeout / retry | unit (mocked model) | A |
| Processing-location reporting | unit + integration | A |
| Structured-output validation | unit | B |
| Persona grounding (prompt includes identity + memory) | unit (mocked model) | B |
| Memory permission scoping | unit | B |
| Cross-tenant / cross-user memory denial | integration | B |
| Propose-never-auto-commit | unit | B |
| Tool authorization (allow/deny) | unit | C |
| Tool audit records | unit | C |
| Tool tenant isolation | integration | C |
| Failure isolation between tasks | unit | D |
| End-to-end task→agent→deliverable | integration (mocked model) | D |
| Ollama live smoke | integration, **skippable** | D |
| Regression (86 + 19 + 7) | full suites | all |

## 11. Rollback and preservation procedures

- Each phase lands as its own commit; `git revert <phase-commit>` is the rollback unit.
- The only schema change (Phase C) is an additive leaf table; rollback is `DROP TABLE tool_executions` with no effect on prior data.
- The M6 preservation point (`ed8a5bcf…`, tag `m6-complete`) and M7 are **not** modified; M8 commits land on top.
- Original Social Media Manager (`/Users/kiarricafavors/AI Agent`) is untouched.
- No new mandatory dependencies: Ollama uses the existing `urllib` path; output validation reuses Pydantic (already in `requirements.txt`).

## 12. Risks / notes

- Prompt/Memory leakage: prompts must never embed raw secret-bearing memory; `MemoryService` already filters sensitive proposal content, and tool params reuse secret-key filtering.
- Deterministic testing depends on a mockable `ModelRouter` boundary — this is required before Phase B.
- The manifest `tools` arrays currently list deferred external tools (`web_search`/`email`/`calendar`); these remain inert/deferred and are handled as "unknown tool → denied" until future opt-in.
