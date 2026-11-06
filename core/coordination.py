"""CoordinationPlanBuilder — T2-C-2 Coordination Plan Builder.

Turns an *approved* TeamGoal into a normalized, ordered, reviewable coordination
plan. Deterministic and side-effect-free: it validates and assembles a transient
plan for later human review. It NEVER writes database records, starts episodes,
dispatches agents, executes tools, or writes delegation logs.

Security model (fail-closed)
----------------------------
- Capability matching and delegation authorization are SEPARATE checks.
- A step's agent must (a) be a recognized team member, (b) have a relevant
  capability for its responsibility, AND (c) be an authorized delegation target
  from the coordinator, as declared by the agent manifests and enforced by
  ``DelegationService`` (permission intersection + depth limits).
- Agent membership or capability is NEVER treated as authorization to delegate.
  An undeclared / unauthorized delegation is reported as an invalid step.

Approval boundary
-----------------
- Plans are built ONLY from TeamGoals in ``approved`` status. proposed/rejected/
  terminal goals are refused. Building never approves a goal and never persists
  or executes the produced plan.

Reused existing interfaces (no duplication)
-------------------------------------------
- ``TeamGoalService`` (reads the goal + steps; owner-scoped).
- ``DelegationService.can_delegate`` (manifest-declared delegation authorization).
- ``TeamRouter._CAPABILITY_KEYWORDS`` (deterministic capability relevance).
- Agent manifests via ``core.runtime.load_registry``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.team_goal import TeamGoalService
from core.delegation import DelegationService
from core.team_router import _CAPABILITY_KEYWORDS
from core.runtime import load_registry


# Stable set of the six permanent agent slugs (kept in sync with manifests).
AGENT_SLUGS = {
    "tutor", "strategist", "executive_assistant",
    "communications", "soundboard", "workspace_architect",
}

# TeamGoal statuses from which a coordination plan MAY be built.
_ELIGIBLE_STATUS = {"approved"}


class CoordinationInvalidPlan(ValueError):
    """A TeamGoal is ineligible or its steps cannot form a safe plan."""


class CoordinationPlanBuilder:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.goal_svc = TeamGoalService(db, tenant_id, user_id)
        self.registry = load_registry()
        manifests = {slug: self.registry.get(slug) or {} for slug in self.registry.list()}
        self.delegation = DelegationService(db, tenant_id, manifests)

    # ----------------------------------------------------------------- reads
    def _agent_capabilities(self, agent: str) -> set:
        manifest = self.registry.get(agent) or {}
        caps = manifest.get("capabilities", []) or []
        tokens: set = set()
        for c in caps:
            tokens.update(_CAPABILITY_KEYWORDS.get(c, [c]))
        return tokens

    def _responsibility_tokens(self, responsibility: str) -> List[str]:
        import re
        text = " ".join(str(responsibility or "").lower().split())
        words = re.findall(r"[a-z0-9]+", text)
        return words or ["".join(str(responsibility or "").split())]

    def _has_relevant_capability(self, agent: str, responsibility: str) -> bool:
        """Separate capability check: the agent declares a capability whose
        keyword set overlaps the responsibility text."""
        caps = self._agent_capabilities(agent)
        resp_tokens = self._responsibility_tokens(responsibility)
        if not resp_tokens:
            return bool(caps)  # no responsibility text -> require any capability
        for tok in resp_tokens:
            if tok in caps:
                return True
        return False

    def _delegable(self, coordinator: str, agent: str) -> bool:
        try:
            ok, _ = self.delegation.can_delegate(coordinator, agent)
            return bool(ok)
        except Exception:  # pragma: no cover
            return False

    def validate_draft(self, coordinator: str,
                       steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Non-persistent capability/delegation validation of a plan DRAFT.

        Mirrors the exact rules the builder applies at authorize time, so the UI
        can warn / auto-reassign BEFORE proposing (closing the T2-C-8 gap where
        wrong responsibilities or undeclared delegation only fail at authorize).
        For every invalid step it also lists ``valid_agent_ids`` (agents that are
        delegable from the coordinator AND have a capability for the
        responsibility) plus a deterministic ``suggested_agent_id``.
        """
        coordinator = (coordinator or "").strip().lower()
        if coordinator not in AGENT_SLUGS:
            raise CoordinationInvalidPlan(f"unknown coordinator: {coordinator}")
        try:
            self._validate_sequence(steps)
        except CoordinationInvalidPlan:
            raise

        plan_steps: List[Dict[str, Any]] = []
        errors: List[str] = []
        for s in steps:
            agent = (s.get("agent_id") or "").strip().lower()
            responsibility = s.get("responsibility") or ""
            seq = int(s.get("seq"))
            if agent not in AGENT_SLUGS:
                errors.append(f"step {seq}: unknown agent '{agent}'")
                plan_steps.append({
                    **s, "agent_id": agent, "valid": False,
                    "capability_ok": False, "delegation_ok": False,
                    "error": f"unknown agent '{agent}'",
                    "valid_agent_ids": [], "suggested_agent_id": None,
                })
                continue

            capability_ok = self._has_relevant_capability(agent, responsibility)
            delegation_ok = self._delegable(coordinator, agent)

            candidates = [
                a for a in AGENT_SLUGS
                if self._delegable(coordinator, a)
                and self._has_relevant_capability(a, responsibility)
            ]
            valid = capability_ok and delegation_ok
            err = None
            if not capability_ok:
                err = (f"step {seq}: agent '{agent}' lacks a relevant capability "
                       f"for the responsibility")
            elif not delegation_ok:
                err = (f"step {seq}: delegation from coordinator '{coordinator}' "
                       f"to '{agent}' is not authorized (not declared)")
            if err:
                errors.append(err)
            suggested = None
            if not valid and candidates:
                suggested = candidates[0] if candidates[0] != agent else (candidates[1] if len(candidates) > 1 else candidates[0])
            plan_steps.append({
                **s,
                "agent_id": agent,
                "capability_ok": capability_ok,
                "delegation_ok": delegation_ok,
                "valid": valid,
                "error": err,
                "valid_agent_ids": candidates,
                "suggested_agent_id": suggested,
            })
        return {"coordinator": coordinator, "steps": plan_steps,
                "plan_valid": not errors, "errors": errors}

    # ----------------------------------------------------------------- build
    def build(self, team_goal_id: str) -> Dict[str, Any]:
        """Build a reviewable coordination plan from an approved TeamGoal.

        Returns a transient plan dict. Raises CoordinationInvalidPlan when the
        goal is absent/ineligible or its steps are structurally invalid (never
        silently repairs). Never writes or executes.
        """
        tg = self.goal_svc.get(team_goal_id)
        if not tg:
            raise CoordinationInvalidPlan("team goal not found")
        if tg.get("status") not in _ELIGIBLE_STATUS:
            raise CoordinationInvalidPlan(
                f"team goal is not approved for coordination (status={tg.get('status')})")

        coordinator = tg.get("coordinator_agent") or ""
        if coordinator not in AGENT_SLUGS:
            raise CoordinationInvalidPlan(f"unknown coordinator: {coordinator}")

        steps = [dict(s) for s in (tg.get("steps") or [])]
        # Structural validation first: contiguous seq + acyclic dependencies.
        self._validate_sequence(steps)

        plan_steps: List[Dict[str, Any]] = []
        errors: List[str] = []
        warnings: List[str] = []
        for s in steps:
            agent = (s.get("agent_id") or "").strip().lower()
            responsibility = s.get("responsibility") or ""
            seq = int(s.get("seq"))
            if agent not in AGENT_SLUGS:
                errors.append(f"step {seq}: unknown agent '{agent}'")
                plan_steps.append({**s, "valid": False,
                                   "capability_ok": False, "delegation_ok": False,
                                   "error": f"unknown agent '{agent}'"})
                continue

            capability_ok = self._has_relevant_capability(agent, responsibility)
            # SEPARATE fail-closed delegation check.
            delegation_ok = False
            delegation_reason = None
            try:
                ok, info = self.delegation.can_delegate(coordinator, agent)
                delegation_ok = bool(ok)
                if not ok:
                    delegation_reason = str(info)
            except Exception as e:  # pragma: no cover
                delegation_ok = False
                delegation_reason = f"delegation check failed: {e}"

            step_valid = capability_ok and delegation_ok
            err = None
            if not capability_ok:
                err = f"step {seq}: agent '{agent}' lacks a relevant capability for the responsibility"
            elif not delegation_ok:
                err = (f"step {seq}: delegation from coordinator '{coordinator}' to "
                       f"'{agent}' is not authorized ({delegation_reason})")
            if err:
                errors.append(err)
            plan_steps.append({
                **s,
                "agent_id": agent,
                "capability_ok": capability_ok,
                "delegation_ok": delegation_ok,
                "valid": step_valid,
                "error": err,
            })

        # Coordinator is preserved regardless; the plan is reviewable.
        return {
            "team_goal_id": team_goal_id,
            "coordinator": coordinator,
            "goal_id": tg.get("goal_id"),
            "expected_deliverable": tg.get("expected_deliverable"),
            "steps": plan_steps,
            "plan_valid": len(errors) == 0 and bool(plan_steps),
            "errors": errors,
            "warnings": warnings,
            "transient": True,  # review-only; nothing persisted or executed
        }

    def _validate_sequence(self, steps: List[Dict[str, Any]]) -> None:
        """Validate contiguous sequence + acyclic dependency ordering.

        Raises CoordinationInvalidPlan with a precise reason. Mirrors the
        TeamGoal propose-time rules so build never repairs an invalid plan.
        """
        if not steps:
            return  # empty steps handled by caller (valid empty plan)
        seqs = [int(s.get("seq")) for s in steps]
        if sorted(seqs) != list(range(1, len(seqs) + 1)):
            raise CoordinationInvalidPlan("step sequences must be contiguous 1..n")
        seen = set()
        for s in steps:
            seq = int(s.get("seq"))
            if seq in seen:
                raise CoordinationInvalidPlan(f"duplicate step seq: {seq}")
            seen.add(seq)
            depended = s.get("depends_on_seq")
            if depended is not None:
                depended = int(depended)
                if not (1 <= depended < seq):
                    raise CoordinationInvalidPlan(
                        f"step {seq} depends_on_seq must reference an earlier step (1..{seq-1})")
        # Topological check: every step appears after all its dependencies.
        position = {seq: i for i, seq in enumerate(seqs)}
        for s in steps:
            depended = s.get("depends_on_seq")
            if depended is not None and position.get(int(depended), -1) > position[int(s.get("seq"))]:
                raise CoordinationInvalidPlan("circular or unsorted dependency detected")
