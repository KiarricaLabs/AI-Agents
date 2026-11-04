"""TeamRouter — AI Team 2.0 hybrid relevance routing (T2-A).

Deterministic, capability-first relevance routing for the shared AI team chat.

Routing is HYBRID, exactly as approved:
  1. CAPABILITY PASS (hard filter): drop any agent whose manifest does not
     declare a capability matching the message intent. This is the SAME
     source the PlanService owner-suggestion uses, so it can never route work
     to an agent that lacks the capability (owner suggestions never become
     authorization).
  2. CONTEXT PASS (rank): rank the remaining agents by conversation/project
     context so the most relevant responders are dispatched first and we stay
     within a responder cap (avoids N model calls per message).

Dispatch is SEQUENTIAL (one at a time) to the relevant shortlist via
``Orchestrator.dispatch``, preserving each agent's manifest/memory/policy/brand.
Non-relevant agents stay silent. Aggregate responses into a shared plan draft
when the message is a plan request, otherwise a set of bubbles.

Coordination honesty: multi-agent responses are only labeled "coordinated by the
team" when multiple agents truly contributed. A single-coordinator result is
labeled as such. This service never claims autonomous collaboration it does not
perform.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

# Deterministic intent keyword -> capability tokens, keyed by the *capability*
# names the six manifests declare. Matching is deliberately conservative:
# we only route to an agent whose manifest capability keyword collides with the
# message/context tokens.
_CAPABILITY_KEYWORDS: Dict[str, List[str]] = {
    "plan": ["plan", "strategy", "objective", "milestone", "roadmap", "goal", "prioritize"],
    "prioritize": ["priority", "prioritize", "risk", "tradeoff", "focus"],
    "explain": ["explain", "teach", "learn", "concept", "understand", "clarify"],
    "quiz": ["quiz", "test", "exercise", "practice"],
    "summarize": ["summarize", "summary", "recap", "digest", "synthesize"],
    "listen": ["listen", "think", "deliberate", "soundboard", "feedback", "reflect"],
    "reflect": ["reflect", "perspective", "consider", "weigh"],
    "draft": ["draft", "write", "communication", "message", "announce", "post", "content"],
    "reply": ["reply", "respond", "email", "engagement"],
    "schedule": ["schedule", "organize", "appointment", "deadline", "calendar", "remind"],
    "remind": ["remind", "follow up", "follow-up", "reminder", "next steps"],
    "organize": ["organize", "structure", "workspace", "project", "architecture", "assign"],
    "design": ["design", "layout", "template", "blueprint", "setup"],
}

# Default coordinator when a message asks to build a plan. Configurable via the
# constructor so it is not hard-coded to Aisha forever.
DEFAULT_PLAN_COORDINATOR = "strategist"

# Maximum responders per message (avoids N model calls per shared message).
DEFAULT_MAX_RESPONDERS = 3

logger = logging.getLogger("core.team_router")


class TeamRouter:
    def __init__(self, registry, orch, tenant_id: str, user_id: str,
                 coordinator: str = DEFAULT_PLAN_COORDINATOR,
                 max_responders: int = DEFAULT_MAX_RESPONDERS):
        self.registry = registry
        self.orch = orch
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.coordinator = coordinator
        self.max_responders = max_responders

    # ------------------------------------------------------------------ routing
    def _capability_tokens(self, manifest: Dict[str, Any]) -> set:
        caps = manifest.get("capabilities", []) or []
        tokens: set = set()
        for c in caps:
            tokens.update(_CAPABILITY_KEYWORDS.get(c, [c]))
        return tokens

    def _score(self, manifest: Dict[str, Any], text: str) -> int:
        """Context-pass raw score: how many capability keywords appear in text."""
        low = " ".join(str(t).lower() for t in ([text] + self._context_terms(text)))
        tokens = self._capability_tokens(manifest)
        return sum(1 for kw in tokens if kw.lower() in low)

    def _context_terms(self, text: str) -> List[str]:
        """Context terms derived from the message itself (extendable to project
        context later). Kept local/deterministic now."""
        return [text]

    def relevant(self, message: str) -> List[str]:
        """Return the deterministic, capability-filtered + context-ranked list of
        agent slugs that should respond, up to max_responders. Empty if none."""
        if not (message or "").strip():
            return []
        scored: List[tuple] = []
        for slug in self.registry.list():
            manifest = self.registry.get(slug)
            if not manifest:
                continue
            cap_ok = any(k in message.lower() for c in manifest.get("capabilities", [])
                         for k in _CAPABILITY_KEYWORDS.get(c, [c]))
            if not cap_ok:
                # Capability pass: absent capability -> never routed. (Hard filter.)
                continue
            score = self._score(manifest, message)
            if score <= 0:
                continue
            scored.append((score, slug))
        # Deterministic: highest score first, then stable slug ordering.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [slug for _score, slug in scored][: self.max_responders]

    # ------------------------------------------------------------------ dispatch
    def dispatch_team(self, message: str, context: Optional[Dict[str, Any]] = None,
                      persist=None) -> Dict[str, Any]:
        """Sequentially dispatch a team message to the relevant shortlist.

        ``persist`` is an optional callable (thread_id, agent_id, role, content)
        used by the API layer to write conversation bubbles. Returns an aggregate
        with per-agent responses and an honest coordination flag.
        """
        ctx = context or {}
        shortlist = self.relevant(message)
        responses: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for slug in shortlist:
            try:
                result = self.orch.dispatch(slug, message, ctx)
                text = result.get("reply", "") if isinstance(result, dict) else str(result)
                if persist:
                    persist(ctx.get("thread_id"), slug, "assistant", text)
                responses.append({"agent": slug, "reply": text,
                                  "model": result.get("model") if isinstance(result, dict) else None})
            except PermissionError as e:
                errors.append({"agent": slug, "code": "permission_denied", "detail": str(e)})
            except RuntimeError as e:
                errors.append({"agent": slug, "code": "model_unavailable", "detail": str(e)})
            except ValueError as e:
                errors.append({"agent": slug, "code": "invalid_output", "detail": str(e)})
            except Exception as e:
                errors.append({"agent": slug, "code": "unexpected", "detail": str(e)})

        is_plan = _is_plan_request(message)
        coordinated = len(responses) > 1
        return {
            "message": message,
            "routed_to": shortlist,
            "responses": responses,
            "errors": errors,
            "coordinated_team_response": coordinated,
            "coordination": "multi-agent" if coordinated
                            else ("single-coordinator" if responses else "none"),
            "plan_intent": is_plan,
            "coordinator_agent": self.coordinator if is_plan else None,
            "max_responders": self.max_responders,
        }


def _is_plan_request(message: str) -> bool:
    low = (message or "").lower()
    return any(k in low for k in ("plan", "roadmap", "organize", "structure",
                                  "project", "objective", "break down", "milestone"))


def route_team(registry, orch, message: str, tenant_id: str, user_id: str,
               context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """Convenience wrapper for constructing a TeamRouter and dispatching."""
    return TeamRouter(registry, orch, tenant_id, user_id, **kwargs).dispatch_team(message, context)
