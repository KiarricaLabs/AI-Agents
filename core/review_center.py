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

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.agent_comm import AgentCommService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewCenterService:
    # Allowed item types for the (non-destructive) dismissal ledger.
    ITEM_TYPES = {
        "goal_approval", "plan_authorization", "step_review",
        "deliverable_review", "blocked_step", "blocked_communication",
    }

    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ------------------------------------------------------------------ dismissals

    def dismissed(self) -> set:
        """Set of (item_type, item_key) the owner has hidden from their list."""
        rows = self._q(
            "SELECT item_type, item_key FROM review_dismissals "
            "WHERE tenant_id=? AND user_id=?", (self.tenant_id, self.user_id))
        return {(r["item_type"], r["item_key"]) for r in rows}

    def dismiss(self, item_type: str, item_key: str) -> dict:
        """Hide one review item for this owner. Never touches evidence."""
        if item_type not in self.ITEM_TYPES:
            raise ValueError("unknown item_type")
        item_key = (item_key or "").strip()
        if not item_key:
            raise ValueError("item_key is required")
        self.db.execute(
            "INSERT OR IGNORE INTO review_dismissals "
            "(id, tenant_id, user_id, item_type, item_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, self.tenant_id, self.user_id,
             item_type, item_key, _now()))
        return {"dismissed": True, "item_type": item_type, "item_key": item_key}

    def undismiss(self, item_type: str, item_key: str) -> dict:
        """Restore a previously dismissed review item."""
        if item_type not in self.ITEM_TYPES:
            raise ValueError("unknown item_type")
        self.db.execute(
            "DELETE FROM review_dismissals WHERE tenant_id=? AND user_id=? "
            "AND item_type=? AND item_key=?",
            (self.tenant_id, self.user_id, item_type, item_key))
        return {"dismissed": False, "item_type": item_type, "item_key": item_key}

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
    def blocked_communications(self) -> List[Dict[str, Any]]:
        return AgentCommService(self.db, self.tenant_id, self.user_id).blocked()

    @staticmethod
    def _key_for(item_type: str, item: Dict[str, Any]) -> str:
        """Stable, unique per-owner key used by the non-destructive dismissal."""
        if item_type in ("goal_approval", "plan_authorization"):
            return "goal:" + str(item.get("goal_id") or "")
        if item_type in ("step_review", "blocked_step"):
            return "step:%s:%s" % (item.get("plan_id"), item.get("seq"))
        if item_type == "deliverable_review":
            return "deliv:" + str(item.get("plan_id") or "")
        if item_type == "blocked_communication":
            return "comm:" + str(item.get("id") or "")
        return ""

    def review(self) -> Dict[str, Any]:
        """Return all owner-scoped action items, categorized, with counts.

        Dismissed items (from the non-destructive ledger) are excluded from both
        the list and the counts. Nothing is deleted; evidence stays intact.
        """
        raw: List[Dict[str, Any]] = [
            {"type": "goal_approval", **item}
            for item in self.pending_goal_approvals()
        ] + [
            {"type": "plan_authorization", **item}
            for item in self.plans_awaiting_authorization()
        ] + [
            {"type": "step_review", **item}
            for item in self.steps_awaiting_review()
        ] + [
            {"type": "deliverable_review", **item}
            for item in self.deliverables_awaiting_review()
        ] + [
            {"type": "blocked_step", **item}
            for item in self.blocked_steps()
        ] + [
            {"type": "blocked_communication", **item}
            for item in self.blocked_communications()
        ]

        for it in raw:
            it["key"] = self._key_for(it["type"], it)

        dismissed = self.dismissed()
        items = [it for it in raw if (it["type"], it["key"]) not in dismissed]
        counts: Dict[str, int] = {}
        for it in items:
            counts[it["type"]] = counts.get(it["type"], 0) + 1
        return {"items": items, "counts": counts}
