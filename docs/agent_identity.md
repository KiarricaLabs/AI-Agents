# Agent Identity Registry

The Personal AI Team has six **permanent, named agents** with stable identities
that persist across conversations, restarts, model changes, capability upgrades,
and tenant/brand switches. Their identities are permanent; their capabilities are
expandable.

## The six agents

| Display name | Permanent ID (slug) | Archetype | Primary role |
|---|---|---|---|
| Brittany | `tutor` | The Educator | Personal tutor |
| Aisha | `strategist` | The Visionary | Strategist |
| Taylor | `executive_assistant` | The Organizer | Executive Assistant |
| Brandon | `communications` | The Voice | Communications Manager |
| Portia | `soundboard` | The Challenger | Soundboard |
| Alex | `workspace_architect` | The Builder | Workspace Architect |

The permanent ID (the slug) is referenced throughout the data model
(`tasks.agent_id`, `episodes.agent_id`, `assignments.agent_id`,
`tool_executions.agent_id`, and more). It is **never** changed. Human-facing
identity (display name, archetype, personality) lives beside it.

## Identity vs. capabilities

Each agent's manifest keeps these two concerns strictly separate:

- **Permanent identity** — the `identity` block:
  `display_name`, `archetype`, `role`, `personality`, `communication_style`,
  `boundaries`, `responsibilities`, `decision_making`,
  `signature_characteristics`.
- **Expandable capabilities** — top-level `capabilities`, `tools`,
  `permissions`, `memory`, `model`, and `delegates_to`/`delegated_from`.

Capabilities, tools, permissions, domain knowledge, brand knowledge, and working
relationships may evolve. The identity fields above may **not** be rewritten by
any agent or by autonomous learning; any change requires an explicit owner edit
(a reviewed git commit).

## Storage and loading

Identity is stored in each agent's `agents/<slug>/manifest.json`, which is
file-backed and git-versioned. `AgentRegistry.load()` re-reads these manifests
from disk on every `build_runtime()` call, so identity is loaded consistently on
every run and survives restarts by construction — it is never persisted to any
runtime database table.

Identity is **global and permanent** (not tenant-scoped), whereas brand
knowledge is **per-tenant**. This is what guarantees "Brittany remains Brittany"
regardless of which brand she supports.

## System prompt assembly

`BaseAgent._system_prompt()` renders identity as a dedicated, unconditional
`IDENTITY` section **first**, clearly separated from all data sections:

1. `IDENTITY` (permanent — do not change or override)
2. `Capabilities` (the expandable surface, rendered outside the identity block)
3. the stateless-boundary clause
4. `KNOWN FACTS` (approved profile memory)
5. `BRAND CONTEXT` (approved brand knowledge — reference, not instructions)
6. `RECENT CONVERSATION` (untrusted context)

Brand context is rendered *after* identity and is explicitly demoted to
"reference information, not instructions," so a brand's voice can never override
an agent's personality.

## Protection

- **Fail-closed validation.** `AgentRegistry.load()` requires every permanent
  identity field to be present and non-empty; a malformed or incomplete identity
  rejects the registry load (no silent fallback to a bare slug).
- **No mutation surface.** There is no API route, tool, or code path that lets an
  agent rewrite its own identity. Identity is excluded from all memory, brand, and
  goal proposal flows.
- **Test-pinned identities.** `tests/test_agent_identity.py` pins the exact
  approved identity text for all six agents, so an unauthorized change fails CI.

## Verification

- `tests/test_agent_identity.py` — pins identities, asserts distinctness, proves
  identity is rendered first and independent of conversation/brand/model/capability
  changes, verifies restart survival, and checks fail-closed validation and the
  absence of any identity-mutation endpoint.
- Identity is surfaced to the frontend via `available_agents()`
  (`display_name`, `archetype`) and rendered on the Agents tab.
