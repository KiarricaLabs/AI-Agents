"""Approved-assignment execution (M10 Phase D4.1).

Human-triggered execution tracking of an *approved* assignment. The human
explicitly starts tracking, the system independently verifies:

- the assignment is owned by the requesting tenant/user,
- it is genuinely linked to an APPROVED proposal (result_id == assignment id),
- the executing agent is valid and equals the assignment's assigned agent,
- the requester is a human (not the agent itself),

then creates or reuses the correct Episode via the existing D2 lifecycle.

This is lifecycle tracking ONLY. It never runs a worker, scheduler, background
dispatch, or autonomous executor. The human performs/oversees the work and
supplies or confirms evidence through the existing D2/D3 endpoints.
"""
from __future__ import annotations

from typing import Any, Dict

from core.work_proposals import AGENT_SLUGS
from core.episodes import EpisodeService


class AssignmentNotFound(ValueError):
    pass


class AssignmentNotApproved(ValueError):
    pass


class InvalidAgent(ValueError):
    pass


class AgentMismatch(ValueError):
    pass


class SelfExecution(ValueError):
    pass


class ApprovedExecutionService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def _approved_proposal_for_work(self, work_type: str, work_id: str,
                                    expected_subject: str):
        """Return the approved proposal id for a work record only if the approved
        proposal names ``expected_subject`` as its agent (``subject_id``). The
        approved proposal's intended agent must match the current assignment's
        agent; a proposal is never an independent proof of agent authority."""
        rows = self.db.query(
            "SELECT id, subject_id FROM work_proposals WHERE tenant_id=? AND user_id=? "
            "AND work_type=? AND result_id=? AND status='approved'",
            (self.tenant_id, self.user_id, work_type, work_id))
        if not rows:
            return None
        p = rows[0]
        if p.get("subject_id") != expected_subject:
            return None
        return p["id"]

    def execute_approved_assignment(self, assignment_id: str, approver_user_id: str,
                                    requested_agent: str) -> Dict[str, Any]:
        """Validate approval/ownership and start (or reuse) the execution Episode
        for an approved assignment. Idempotent for an active Episode."""
        rows = self.db.query(
            "SELECT * FROM assignments WHERE id=? AND tenant_id=? AND user_id=?",
            (assignment_id, self.tenant_id, self.user_id))
        if not rows:
            raise AssignmentNotFound("assignment not found")
        a = rows[0]

        agent = (requested_agent or "").strip() or (a.get("agent_id") or "")
        if agent not in AGENT_SLUGS:
            raise InvalidAgent("invalid agent")
        if agent != a["agent_id"]:
            raise AgentMismatch("agent does not match the assignment")
        if approver_user_id == agent:
            raise SelfExecution("an agent cannot start its own execution")
        if not self._approved_proposal_for_work("assignment", assignment_id, a["agent_id"]):
            raise AssignmentNotApproved("assignment is not approved for execution")

        es = EpisodeService(db=self.db, tenant_id=self.tenant_id, user_id=self.user_id)
        result = es.start_for_work("assignment", assignment_id, agent)
        return {**result, "assignment_id": assignment_id, "agent_id": agent}
