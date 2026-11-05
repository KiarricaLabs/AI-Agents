"""T2-E / Review & Action Center — read-only aggregation of every human decision.

Phase 7 §13 of the Conversational Command Center plan: give the human ONE
owner-scoped list of everything that needs their attention across all of their
TeamGoals, coordination plans, executions, steps, and deliverables — instead of
inspecting each goal one at a time.

This service is READ-ONLY and never mutates anything. Each returned item carries
the ids needed to act on it through the existing, human-only, tenant-scoped
endpoints. It does NOT start, authorize, approve, or execute anything, and it
adds no new permissions: identity/ownership is always scoped to the tenant/user
passed in (derived from request.state by the router).

Item types delivered:
- ``goal_approval``        — a TeamGoal in 'proposed' state awaiting your approval.
- ``plan_authorization``   — an approved TeamGoal with NO authorized plan yet.
- ``step_review``          — a coordination step output in 'awaiting_review'.
- ``deliverable_review``   — a coordination deliverable in 'pending' state.
- ``blocked_step``         — a coordination step that failed (retry opportunity).

Counts are provided alongside for a compact overview.
"""
from __future__ import annotations

from typing import Any, Dict, List


class ReviewCenterService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def _q(self, sql: str, params=()) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.query(sql, params)]

    # ------------------------------------------------------------------ items
    def pending_goal_approvals(self) -> List[Dict[str, Any]]:
        return self._q(
            "SELECT id AS goal_id, title, coordinator_agent, summary "
            "FROM team_goals WHERE tenant_id=? AND user_id=? AND status='proposed' "
            "ORDER BY created_at ASC",
            (self.tenant_id, self.user_id))

    def plans_awaiting_authorization(self) -> List[Dict[str, Any]]:
        return self._q(
            "SELECT g.id AS goal_id, g.title, g.coordinator_agent "
            "FROM team_goals g "
            "WHERE g.tenant_id=? AND g.user_id=? AND g.status='approved' "
            "AND NOT EXISTS (SELECT 1 FROM coordination_plans p "
            "  WHERE p.team_goal_id=g.id AND p.tenant_id=g.tenant_id "
            "  AND p.user_id=g.user_id) "
            "ORDER BY g.created_at ASC",
            (self.tenant_id, self.user_id))

    def steps_awaiting_review(self) -> List[Dict[str, Any]]:
        return self._q(
            "SELECT s.execution_id, s.plan_id, s.seq, s.agent_id, "
            "       p.team_goal_id AS goal_id, g.title AS goal_title "
            "FROM coordination_step_outputs s "
            "JOIN coordination_plans p ON p.id=s.plan_id "
            "      AND p.tenant_id=s.tenant_id AND p.user_id=s.user_id "
            "JOIN team_goals g ON g.id=p.team_goal_id "
            "      AND g.tenant_id=s.tenant_id AND g.user_id=s.user_id "
            "WHERE s.tenant_id=? AND s.user_id=? AND s.status='awaiting_review' "
            "ORDER BY s.updated_at ASC",
            (self.tenant_id, self.user_id))

    def deliverables_awaiting_review(self) -> List[Dict[str, Any]]:
        return self._q(
            "SELECT d.execution_id, d.plan_id, p.team_goal_id AS goal_id, "
            "       g.title AS goal_title, g.coordinator_agent "
            "FROM coordination_deliverables d "
            "JOIN coordination_plans p ON p.id=d.plan_id "
            "      AND p.tenant_id=d.tenant_id AND p.user_id=d.user_id "
            "JOIN team_goals g ON g.id=p.team_goal_id "
            "      AND g.tenant_id=d.tenant_id AND g.user_id=d.user_id "
            "WHERE d.tenant_id=? AND d.user_id=? AND d.status='pending' "
            "ORDER BY d.updated_at ASC",
            (self.tenant_id, self.user_id))

    def blocked_steps(self) -> List[Dict[str, Any]]:
        return self._q(
            "SELECT s.execution_id, s.plan_id, s.seq, s.agent_id, s.error, "
            "       p.team_goal_id AS goal_id, g.title AS goal_title "
            "FROM coordination_step_outputs s "
            "JOIN coordination_plans p ON p.id=s.plan_id "
            "      AND p.tenant_id=s.tenant_id AND p.user_id=s.user_id "
            "JOIN team_goals g ON g.id=p.team_goal_id "
            "      AND g.tenant_id=s.tenant_id AND g.user_id=s.user_id "
            "WHERE s.tenant_id=? AND s.user_id=? AND s.status='failed' "
            "ORDER BY s.updated_at ASC",
            (self.tenant_id, self.user_id))

    # ------------------------------------------------------------------ review
    def review(self) -> Dict[str, Any]:
        """Return all owner-scoped action items, categorized, with counts."""
        items: List[Dict[str, Any]] = []
        for item in self.pending_goal_approvals():
            items.append({"type": "goal_approval", **item})
        for item in self.plans_awaiting_authorization():
            items.append({"type": "plan_authorization", **item})
        for item in self.steps_awaiting_review():
            items.append({"type": "step_review", **item})
        for item in self.deliverables_awaiting_review():
            items.append({"type": "deliverable_review", **item})
        for item in self.blocked_steps():
            items.append({"type": "blocked_step", **item})

        counts = {
            "goal_approval": len(self.pending_goal_approvals()),
            "plan_authorization": len(self.plans_awaiting_authorization()),
            "step_review": len(self.steps_awaiting_review()),
            "deliverable_review": len(self.deliverables_awaiting_review()),
            "blocked_step": len(self.blocked_steps()),
        }
        return {"items": items, "counts": counts}
