# Conversational Memory — Proposed Plan (pending approval)

**Status:** Proposal — documentation only. No code, schema, or dependency changes until explicitly approved and implemented.

## 1. Problem

The M8 Interactive Runtime is intentionally single-shot: each "Run Agent" request is a
stateless turn. It does **not** persist or re-inject conversation history, so:

- The model cannot "remember" the prior turn (there is no prior turn in its context).
- The model then **hallucinates** a memory capability ("yes, I save conversations")
  because the system prompt never tells it that it is stateless.

Two related but distinct capabilities are conflated in the observed behavior:

| Expectation | Capability | Current state |
|---|---|---|
| "Remember what we just said" | **Conversation history** grounded into each turn | Not wired (stateless) |
| "Know my brand long-term" | **Approved profile memory** (proposal → human approval) | Not wired (no auto-memory, by design) |

## 2. Root cause (verified)

- `POST /agents/{name}/run` sends only `{"task": ...}`.
- `Orchestrator.dispatch` → `BaseAgent.run` → `_ground` builds a system prompt from
  persona + `KNOWN FACTS` (profile/goals/notes only) and sends the task as the prompt.
  **Conversation history is never retrieved and never included.**
- `conversation_memory` table and `add_conversation` / `list_conversation` exist, and
  `POST /memory/conversation` / `GET /memory/conversation` endpoints exist, but the
  interactive run path **never calls them**.
- The model's "I remember / I save conversations" answers are confabulation: it has no
  access to actual system state.

## 3. What already exists (reused — no rebuild)

- `conversation_memory` table: `id, tenant_id, user_id, thread_id, role, content, created_at`.
- `core/memory.py` → `MemoryService.add_conversation(...)` and `list_conversation(...)`
  (already tenant + user scoped).
- `api/routers/memory.py` → `POST /memory/conversation`, `GET /memory/conversation`.
- `Orchestrator.dispatch(agent, task, context=None)` already accepts a `context` dict.
- `agents/base.py` → `_generate(..., context, ...)` and `_system_prompt(facts)` already
  thread `context` and build the system prompt.

## 4. Design

### 4.1 API change (additive)

`POST /agents/{name}/run` request body:

```jsonc
{ "task": "…", "thread_id": "optional-opaque-id" }
```

Response gains:

```jsonc
{
  "agent": "…", "reply": "…", "location": "…", "facts": [...],
  "thread_id": "…",            // server returns/echoes the thread id
  "turn_count": 3              // messages now in this thread (informational)
}
```

### 4.2 Thread identity & ownership

- `thread_id` is an **opaque key** only. Identity (tenant + user) always comes from
  `request.state` via the existing `_identity(request)`, never from the client.
- On first turn (no `thread_id`), the server generates one (`uuid4`) and returns it;
  the frontend carries it forward for subsequent turns.
- All reads/writes are scoped by `tenant_id + user_id` (already enforced in
  `list_conversation` / `add_conversation`). A client passing someone else's thread id
  cannot read or write their history — the resolved identity decides ownership.

### 4.3 Persistence

After a **successful** reply, log both turns to `conversation_memory`:

- `(role="user", content=task)` and `(role="assistant", content=reply)`, same `thread_id`.

Failed runs (model error, policy denial, validation failure) are **not** persisted as
successful replies, avoiding poisoned history.

### 4.4 Grounding (prompt injection)

- `list_conversation(user_id, thread_id)` is fetched server-side (needs a small additive
  `ORDER BY created_at` — currently unordered), bounded to the last **N messages**
  (default 12, configurable).
- History is passed through `context` into `_system_prompt` as a `RECENT CONVERSATION`
  section (role-tagged, chronological), in addition to existing `KNOWN FACTS`.

### 4.5 Anti-hallucination prompt

Add a short, fixed clause to the system prompt so the model no longer invents a memory:

> "You are stateless. You may only reference the current task, the RECENT CONVERSATION,
> and the KNOWN FACTS provided below. Do not claim to remember anything outside these."

### 4.6 Durable memory boundary (unchanged / explicitly deferred)

Conversational history is **ephemeral grounding**, not durable knowledge. Brand/profile
facts continue to require the existing `memory:propose` → **human approval** flow.
This milestone does **not** auto-create, auto-approve, or auto-promote memory.

## 5. Files to change (additive only)

- `api/routers/agents.py` — accept `thread_id`, resolve/generate it, load history,
  persist turns, return `thread_id` (and `turn_count`).
- `core/memory.py` — add `ORDER BY created_at ASC` to `list_conversation` (micro-change).
- `core/orchestrator.py` and/or `agents/base.py` — thread `context["conversation"]` into
  `_system_prompt`; add the stateless/anti-hallucination clause.
- `frontend/src/App.tsx` — carry a per-agent `thread_id`, pass it on `runAgent`, show a
  small "context turns" indicator + "New conversation" reset.
- Tests: `tests/test_conversation_memory.py` (new), `frontend/src/App.test.tsx`,
  `frontend/e2e/conversation.spec.ts` (new).

## 6. Non-goals

- No automatic tool calling, no automatic memory/goal proposals, no automatic approvals.
- No schema migration (table already exists).
- No model change; `llama3.1` remains default; Ollama-only.
- No new dependencies.

## 7. Acceptance criteria

1. Two consecutive `run` requests with the same `thread_id` produce a second reply whose
   context includes the first exchange (verified via mocked-LLM assertion on the system
   prompt, and via a live two-turn smoke test).
2. Omitting `thread_id` starts a fresh conversation with no prior history; the response
   returns a new `thread_id`.
3. Cross-user and cross-tenant `thread_id` reuse is rejected / returns empty history.
4. The model no longer claims to remember non-context facts (anti-hallucination clause present).
5. All existing tests still pass (backend, Vitest, Playwright).

## 8. Test matrix

| Area | Test | Type |
|---|---|---|
| Persistence | user+assistant turns written on success | backend (mocked LLM) |
| Grounding | history injected into 2nd-turn system prompt | backend (mocked LLM) |
| New thread | no history when thread omitted; thread id returned | backend |
| Isolation | cross-user / cross-tenant thread blocked | backend (HTTP) |
| Failure | failed run not persisted | backend (mocked failure) |
| Frontend | thread id carried forward; "New conversation" resets | Vitest |
| E2E | two-turn journey + context indicator | Playwright |
| Regression | full backend / Vitest / Playwright suites | — |

## 9. Rollback / preservation

- Additive only; no migration. Rolling back = reverting the changed files (no data loss
  beyond the newly written `conversation_memory` rows).
- Recovery checkpoint `m8-interactive-runtime` and prior milestones remain untouched.
- Original Social Media Manager remains untouched.

## 10. Open decisions (need your input)

1. History window size (default **12 messages** ok?).
2. Should the UI show a lightweight "context" disclosure of the injected history/system
   prompt now (transparency you asked about earlier), or defer that to a follow-up?
