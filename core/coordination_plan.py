"""T2-C-3 — CoordinationPlanService: human-authorized, persisted plan snapshot.

Turns a *validated* coordination plan (from CoordinationPlanBuilder) into a
persisted, authoritative snapshot that a later execution phase (T2-C-4) can read
as its single source of truth. All reads/writes are tenant/user-scoped.

Security model
--------------
- ``review`` returns the transient, validated plan (never persists).
- ``authorize`` persists ONLY after every validation passes, including a
  hard delegation guard that re-derives effective permissions for every step:
  a step whose delegation grants an EMPTY permission intersection is refused
  (fail-closed). This closes the latent gap in ``DelegationService.can_delegate``
  (which returns ``True`` even when the effective intersection is empty) WITHOUT
  modifying ``core/delegation.py``.
- Capability relevance is never treated as delegation authorization; they stay
  separate checks.

Approval / execution boundaries
-------------------------------
- ``authorize`` is a separate human decision from TeamGoal approval.
- Authorizing a plan NEVER starts an episode, dispatches an agent, executes a
  tool, writes a delegation execution log, or starts background work. It only
  writes the frozen plan snapshot + steps.
- The TeamGoal status is NEVER mutated by authorization.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.team_goal import TeamGoalService
from core.coordination import CoordinationPlanBuilder, CoordinationInvalidPlan
from core.delegation import DelegationService


def _now():
    return datetime.now(timezone.utc).isoformat()


class CoordinationPlanNotFound(ValueError):
    pass


class CoordinationPlanInvalid(ValueError):
    pass


class CoordinationPlanPermissionError(PermissionError):
    pass


class CoordinationPlanService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.goal_svc = TeamGoalService(db, tenant_id, user_id)
        self.builder = CoordinationPlanBuilder(db, tenant_id, user_id)
        # Re-derive delegation authorization for the permission guard using the
        # same manifests the builder sees (capability != delegation).
        registry = self.builder.registry
        manifests = {slug: registry.get(slug) or {} for slug in registry.list()}
        self.delegation = DelegationService(db, tenant_id, manifests)

    # ------------------------------------------------------------------ reads
    def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_plans WHERE id=? AND tenant_id=? AND user_id=?",
            (plan_id, self.tenant_id, self.user_id))
        if not rows:
            return None
        return self._hydrate(rows[0])

    def list_authorized(self, team_goal_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_plans WHERE tenant_id=? AND user_id=? AND team_goal_id=? "
            "AND status='authorized' ORDER BY created_at DESC",
            (self.tenant_id, self.user_id, team_goal_id))
        return [self._hydrate(r) for r in rows]

    def _existing_authorized(self, team_goal_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_plans WHERE tenant_id=? AND user_id=? AND team_goal_id=? "
            "AND status='authorized' ORDER BY created_at DESC LIMIT 1",
            (self.tenant_id, self.user_id, team_goal_id))
        return rows[0] if rows else None

    def _steps_for_plan(self, plan_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_plan_steps WHERE tenant_id=? AND user_id=? AND plan_id=? "
            "ORDER BY seq ASC",
            (self.tenant_id, self.user_id, plan_id))
        return [self._decode_step(r) for r in rows]

    @staticmethod
    def _decode_step(r: Dict[str, Any]) -> Dict[str, Any]:
        out = {
            "id": r["id"],
            "plan_id": r["plan_id"],
            "seq": r["seq"],
            "agent_id": r["agent_id"],
            "responsibility": r["responsibility"],
            "depends_on_seq": r["depends_on_seq"],
            "capability_ok": bool(r["capability_ok"]),
            "delegation_ok": bool(r["delegation_ok"]),
            "valid": bool(r["valid"]),
            "error": r["error"],
            "status": r["status"],
        }
        try:
            out["effective_permissions"] = json.loads(r["effective_permissions"] or "[]")
        except (TypeError, ValueError):
            out["effective_permissions"] = []
        return out

    def _hydrate(self, p: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "plan_id": p["id"],
            "team_goal_id": p["team_goal_id"],
            "goal_id": p["goal_id"],
            "coordinator": p["coordinator_agent"],
            "expected_deliverable": p["expected_deliverable"],
            "status": p["status"],
            "version": p["version"],
            "approved_by": p["approved_by"],
            "approved_at": p["approved_at"],
            "created_at": p["created_at"],
            "updated_at": p["updated_at"],
            "steps": self._steps_for_plan(p["id"]),
        }

    # ---------------------------------------------------------------- review
    def review(self, team_goal_id: str) -> Dict[str, Any]:
        """Return the transient validated plan for review. Never persists.

        Raises CoordinationPlanNotFound / CoordinationPlanInvalid per the goal's
        eligibility (proxies CoordinationInvalidPlan from the builder)."""
        tg = self.goal_svc.get(team_goal_id)
        if not tg:
            raise CoordinationPlanNotFound("team goal not found")
        try:
            return self.builder.build(team_goal_id)
        except CoordinationInvalidPlan as e:
            raise CoordinationPlanInvalid(str(e)) from None

    # --------------------------------------------------------------- authorize
    def authorize(self, team_goal_id: str, approver_user_id: str) -> Dict[str, Any]:
        """Human-authorized persistence of a validated coordination plan.

        Persists the frozen plan + steps ONLY after: owner authorization,
        goal eligibility, complete builder validation, and the fail-closed
        permission-intersection guard all pass. Atomic and idempotent. Never
        mutates the TeamGoal status and never starts execution.
        """
        if approver_user_id != self.user_id:
            raise CoordinationPlanPermissionError(
                "only the goal owner may authorize a coordination plan")

        tg = self.goal_svc.get(team_goal_id)
        if not tg:
            raise CoordinationPlanNotFound("team goal not found")
        if tg.get("status") != "approved":
            raise CoordinationPlanInvalid(
                f"team goal is not approved for coordination (status={tg.get('status')})")

        # Idempotency: an already-authorized plan is returned unchanged.
        existing = self._existing_authorized(team_goal_id)
        if existing:
            return {**self._hydrate(existing), "reused": True}

        # Build the transient, validated plan (never persists).
        try:
            plan = self.builder.build(team_goal_id)
        except CoordinationInvalidPlan as e:
            raise CoordinationPlanInvalid(str(e)) from None
        if not plan["plan_valid"]:
            raise CoordinationPlanInvalid(
                "; ".join(plan["errors"]) or "plan is invalid")

        coordinator = plan["coordinator"]
        # CRITICAL GUARD: re-derive effective permissions for every step and
        # require a NON-EMPTY intersection. Capability is not authorization.
        errors: List[str] = []
        step_effective: Dict[int, List[str]] = {}
        for s in plan["steps"]:
            agent = s["agent_id"]
            try:
                ok, info = self.delegation.can_delegate(coordinator, agent)
            except Exception as e:  # pragma: no cover
                ok, info = False, f"delegation re-check failed: {e}"
            if not ok:
                errors.append(
                    f"step {s['seq']}: delegation from '{coordinator}' to "
                    f"'{agent}' is not authorized ({info})")
                step_effective[s["seq"]] = []
                continue
            perms = info if isinstance(info, (set, list, tuple)) else []
            perms = sorted(str(p) for p in perms)
            if not perms:
                errors.append(
                    f"step {s['seq']}: delegation from '{coordinator}' to "
                    f"'{agent}' grants zero effective permissions")
            step_effective[s["seq"]] = perms
        if errors:
            raise CoordinationPlanInvalid("; ".join(errors))

        # Persist plan + steps atomically. Concurrency-safe: use INSERT OR
        # IGNORE so a concurrent duplicate for the same TeamGoal cannot raise;
        # the existing authorized row (verified for tenant/user/goal/status) is
        # then re-fetched and returned as an idempotent reuse. Plan steps are
        # inserted ONLY when a new plan row was actually created.
        plan_id = str(uuid.uuid4())
        now = _now()
        reused_plan_id: Optional[str] = None
        try:
            with self.db.transaction() as c:
                cur = c.execute(
                    "INSERT OR IGNORE INTO coordination_plans "
                    "(id, tenant_id, user_id, team_goal_id, goal_id, coordinator_agent, "
                    " expected_deliverable, status, version, approved_by, approved_at, "
                    " created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (plan_id, self.tenant_id, self.user_id, team_goal_id,
                     tg.get("goal_id"), coordinator, tg.get("expected_deliverable"),
                     "authorized", 1, approver_user_id, now, now, now))
                if cur.rowcount == 1:
                    # New plan inserted -> write its frozen steps.
                    for s in plan["steps"]:
                        c.execute(
                            "INSERT INTO coordination_plan_steps "
                            "(id, tenant_id, user_id, plan_id, seq, agent_id, responsibility, "
                            " depends_on_seq, capability_ok, delegation_ok, effective_permissions, "
                            " valid, error, status, created_at, updated_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()), self.tenant_id, self.user_id, plan_id,
                             s["seq"], s["agent_id"], s.get("responsibility"),
                             s.get("depends_on_seq"),
                             1 if s.get("capability_ok") else 0,
                             1 if s.get("delegation_ok") else 0,
                             json.dumps(step_effective[s["seq"]]),
                             1 if s.get("valid") else 0,
                             s.get("error"), "planned", now, now))
                else:
                    # Insert was ignored (unique constraint). Only treat it as a
                    # successful reuse after proving the existing record matches
                    # the expected tenant/user/TeamGoal with authorized status.
                    rows = c.execute(
                        "SELECT id FROM coordination_plans WHERE tenant_id=? AND user_id=? "
                        "AND team_goal_id=? AND status='authorized'",
                        (self.tenant_id, self.user_id, team_goal_id)).fetchall()
                    if not rows:
                        # Not a legitimate duplicate reuse: an unrelated constraint
                        # failure, so surface it rather than silently succeeding.
                        raise CoordinationPlanInvalid(
                            "plan insert ignored but no matching authorized plan "
                            "exists for this tenant/user/goal")
                    reused_plan_id = rows[0][0]  # cursor rows are tuples (no row_factory)
        except CoordinationPlanInvalid:
            raise
        except Exception:
            raise  # transaction rolled back; nothing partial persisted

        if reused_plan_id is not None:
            # Existing authorized snapshot returned unchanged (never rebuilt or
            # overwritten) with no steps inserted on this retry.
            existing = self.get_plan(reused_plan_id)
            if not existing:  # pragma: no cover
                raise CoordinationPlanInvalid(
                    "authorized plan vanished after insert")
            return {**existing, "reused": True}

        saved = self.get_plan(plan_id)
        if not saved:  # pragma: no cover
            raise CoordinationPlanInvalid("plan could not be persisted")
        return {**saved, "reused": False}
