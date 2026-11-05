"""TeamGoalService — T2-C-1 foundational coordination object.

Turns a user goal into a reviewable *Team Goal*: a coordinator plus an ordered
set of per-agent contribution steps with dependency links and an aggregated
status, leading to a consolidated deliverable for human review.

Design notes
------------
- Single reviewable object (``team_goals``) + ordered steps (``team_goal_steps``)
  + a human review gate (``team_goal_approvals``). Additive tables only.
- ``propose`` records intent (status=proposed). ``approve`` (human) creates the
  coordination records atomically. **Approving NEVER starts an episode or agent
  execution** — execution is a later, still-human-triggered phase.
- Lifecycle: proposed -> approved -> in_progress -> ready_for_review
            -> revision_requested -> completed  |  rejected
- Reuses the app's existing status vocabulary and tenant/user-scoped ownership
  conventions. It does NOT duplicate WorkProposalService / DelegationService /
  EpisodeService — it composes a coordination record on top of them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Stable set of the six permanent agent slugs.
AGENT_SLUGS = {
    "tutor", "strategist", "executive_assistant",
    "communications", "soundboard", "workspace_architect",
}

# Valid lifecycle transitions (user-facing status).
_VALID_TRANSITIONS = {
    "proposed": {"approved", "rejected"},
    "approved": {"in_progress", "rejected", "revision_requested"},
    "in_progress": {"ready_for_review", "revision_requested", "rejected"},
    "ready_for_review": {"completed", "revision_requested", "rejected"},
    "revision_requested": {"in_progress", "rejected"},
    "completed": set(),
    "rejected": set(),
}

_STEP_VALID = {
    "planned": {"in_progress", "cancelled"},
    "in_progress": {"awaiting_review", "cancelled"},
    "awaiting_review": {"accepted", "revision_requested", "cancelled"},
    "accepted": set(),
    "revision_requested": {"awaiting_review", "cancelled"},
    "cancelled": set(),
}

_TERMINAL = {"completed", "rejected"}


def _now():
    return datetime.now(timezone.utc).isoformat()


class TeamGoalNotFound(ValueError):
    pass


class TeamGoalInvalidTransition(ValueError):
    pass


class TeamGoalAlreadyDecided(ValueError):
    pass


class TeamGoalApprovalNotPermitted(PermissionError):
    pass


class TeamGoalService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ---------------------------------------------------------------- owners
    def _owned(self, table: str, rid: str) -> bool:
        rows = self.db.query(
            f"SELECT id FROM {table} WHERE id=? AND tenant_id=? AND user_id=?",
            (rid, self.tenant_id, self.user_id))
        return bool(rows)

    def _need(self, value, what: str) -> str:
        if not value:
            raise ValueError(f"{what} is required")
        return value

    # ---------------------------------------------------------------- lifecycle
    def _set_status(self, team_goal_id: str, status: str, approver: str) -> None:
        self._assert_transition(team_goal_id, status)
        now = _now()
        self.db.execute(
            "UPDATE team_goals SET status=?, decided_by=?, decided_at=?, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (status, approver, now, now, team_goal_id, self.tenant_id, self.user_id))

    def _assert_transition(self, team_goal_id: str, status: str) -> str:
        """Validate that ``status`` is a legal transition for the owner-scoped
        goal and that the goal is not terminal. Returns the current status."""
        rows = self.db.query(
            "SELECT id, status FROM team_goals WHERE id=? AND tenant_id=? AND user_id=?",
            (team_goal_id, self.tenant_id, self.user_id))
        if not rows:
            raise TeamGoalNotFound("team goal not found")
        current = rows[0]["status"]
        if status not in _VALID_TRANSITIONS.get(current, set()):
            raise TeamGoalInvalidTransition(
                f"invalid transition {current} -> {status}")
        if current in _TERMINAL:
            raise TeamGoalAlreadyDecided("team goal already decided")
        return current

    # ---------------------------------------------------------------- propose
    def propose(self, title: str, coordinator_agent: str, *,
                goal_id: Optional[str] = None,
                thread_id: Optional[str] = None,
                summary: Optional[str] = None,
                expected_deliverable: Optional[str] = None,
                steps: Optional[List[Dict[str, Any]]] = None,
                idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Propose a Team Goal (intent only; nothing consequential created).

        ``steps`` is an ordered list of per-agent contributions:
          [{seq, agent_id, responsibility, depends_on_seq}]
        Validates coordinator + step agents are recognized, step ordering is a
        contiguous sequence, and dependencies reference earlier steps. The goal,
        if provided, must be owned by the tenant/user.
        """
        title = str(title or "").strip()
        coordinator = str(coordinator_agent or "").strip().lower()
        if not title:
            raise ValueError("team goal title is required")
        if coordinator not in AGENT_SLUGS:
            raise ValueError(f"unknown coordinator agent: {coordinator}")

        if goal_id:
            self._owned_check("goals", goal_id)

        # idempotency: same tenant + explicit key (used as the id) returns the goal
        if idempotency_key:
            existing = self.db.query(
                "SELECT id, status FROM team_goals WHERE tenant_id=? AND user_id=? AND id=?",
                (self.tenant_id, self.user_id, idempotency_key))
            if existing:
                return {"team_goal_id": existing[0]["id"],
                        "status": existing[0]["status"], "reused": True}

        norm_steps = self._normalize_steps(steps)

        goal_id_str = self._need(goal_id, "goal_id") if goal_id is not None else None
        tg_id = idempotency_key or str(uuid.uuid4())
        now = _now()
        self.db.execute(
            "INSERT INTO team_goals "
            "(id, tenant_id, user_id, goal_id, thread_id, title, coordinator_agent, "
            " summary, status, expected_deliverable, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (tg_id, self.tenant_id, self.user_id, goal_id_str, thread_id,
             title, coordinator, summary, "proposed",
             str(expected_deliverable or "").strip() or None, now, now))
        for st in norm_steps:
            sid = str(uuid.uuid4())
            self.db.execute(
                "INSERT INTO team_goal_steps "
                "(id, tenant_id, user_id, team_goal_id, seq, agent_id, responsibility, "
                " depends_on_seq, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, self.tenant_id, self.user_id, tg_id, st["seq"], st["agent_id"],
                 st["responsibility"], st["depends_on_seq"], "planned", now, now))
        return {"team_goal_id": tg_id, "status": "proposed", "reused": False}

    def _normalize_steps(self, steps: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if not steps:
            return []
        if not isinstance(steps, list):
            raise ValueError("team goal steps must be a list")
        norm = []
        seqs = [int(s.get("seq") or i) for i, s in enumerate(steps)]
        if seqs and sorted(seqs) != list(range(1, len(seqs) + 1)):
            raise ValueError("step sequences must be contiguous 1..n")
        for s in steps:
            if not isinstance(s, dict):
                raise ValueError("each step must be an object")
            seq = int(s.get("seq"))
            agent = str(s.get("agent_id") or "").strip().lower()
            if agent not in AGENT_SLUGS:
                raise ValueError(f"step {seq} references unknown agent: {agent}")
            depended = s.get("depends_on_seq")
            if depended is not None:
                depended = int(depended)
                if not (1 <= depended < seq):
                    raise ValueError(
                        f"step {seq} depends_on_seq must reference an earlier step (1..{seq-1})")
            norm.append({
                "seq": seq,
                "agent_id": agent,
                "responsibility": str(s.get("responsibility") or "").strip() or None,
                "depends_on_seq": depended,
            })
        return norm

    def _owned_check(self, table: str, rid: str) -> None:
        if not self._owned(table, rid):
            raise ValueError(f"ownership: no {table} with id {rid} in this tenant/user scope")

    # ---------------------------------------------------------------- approve
    def approve(self, team_goal_id: str, approver_user_id: str) -> Dict[str, Any]:
        """Human-controlled approval: transitions the goal to 'approved'.

        This is the authorization gate. It creates the coordination records'
        authorized status (already created at propose) and advances to 'approved'.
        It does NOT start any episode/agent execution. Idempotent: re-approving an
        already-approved goal returns its current state.
        """
        if approver_user_id != self.user_id:
            raise TeamGoalApprovalNotPermitted("only the goal owner may approve")
        rows = self.db.query(
            "SELECT * FROM team_goals WHERE id=? AND tenant_id=? AND user_id=?",
            (team_goal_id, self.tenant_id, self.user_id))
        if not rows:
            raise TeamGoalNotFound("team goal not found")
        tg = rows[0]
        if tg["status"] == "approved":
            return {"team_goal_id": team_goal_id, "status": "approved", "reused": True}
        if tg["status"] not in ("proposed",):
            raise TeamGoalAlreadyDecided(
                "team goal is not in a proposed state that can be approved")
        self._set_status(team_goal_id, "approved", approver_user_id)
        return {"team_goal_id": team_goal_id, "status": "approved", "reused": False}

    # ---------------------------------------------------------------- reads
    def get(self, team_goal_id: str, include_steps: bool = True) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM team_goals WHERE id=? AND tenant_id=? AND user_id=?",
            (team_goal_id, self.tenant_id, self.user_id))
        if not rows:
            return None
        out = dict(rows[0])
        if include_steps:
            out["steps"] = self._steps(team_goal_id)
            out["approvals"] = self._approvals(team_goal_id)
        return out

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status:
            rows = self.db.query(
                "SELECT * FROM team_goals WHERE tenant_id=? AND user_id=? AND status=? "
                "ORDER BY created_at DESC",
                (self.tenant_id, self.user_id, status))
        else:
            rows = self.db.query(
                "SELECT * FROM team_goals WHERE tenant_id=? AND user_id=? "
                "ORDER BY created_at DESC",
                (self.tenant_id, self.user_id))
        return [dict(r) for r in rows]

    def steps(self, team_goal_id: str) -> List[Dict[str, Any]]:
        """Public accessor for a goal's ordered steps (owner-scoped)."""
        if not self._owned("team_goals", team_goal_id):
            raise TeamGoalNotFound("team goal not found")
        return self._steps(team_goal_id)

    def _steps(self, team_goal_id: str) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM team_goal_steps WHERE tenant_id=? AND user_id=? AND team_goal_id=? "
            "ORDER BY seq ASC",
            (self.tenant_id, self.user_id, team_goal_id))

    def _approvals(self, team_goal_id: str) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM team_goal_approvals WHERE tenant_id=? AND user_id=? AND team_goal_id=? "
            "ORDER BY created_at ASC",
            (self.tenant_id, self.user_id, team_goal_id))

    # ---------------------------------------------------------------- lifecycle
    def reject(self, team_goal_id: str, user_id: str, reason: Optional[str] = None):
        if user_id != self.user_id:
            raise TeamGoalApprovalNotPermitted("only the owner may reject")
        # Validate the transition is legal BEFORE opening the transaction, then
        # make the status change + approval-record insert atomic.
        self._assert_transition(team_goal_id, "rejected")
        now = _now()
        with self.db.transaction() as c:
            c.execute(
                "UPDATE team_goals SET status=?, decided_by=?, decided_at=?, updated_at=? "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                ("rejected", user_id, now, now, team_goal_id,
                 self.tenant_id, self.user_id))
            c.execute(
                "INSERT INTO team_goal_approvals "
                "(id, tenant_id, user_id, team_goal_id, decision, note, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, self.user_id, team_goal_id,
                 "rejected", (reason or "").strip()[:400] or None, now))
        return True

    def mark_in_progress(self, team_goal_id: str, user_id: str):
        if user_id != self.user_id:
            raise TeamGoalApprovalNotPermitted("only the owner may advance this team goal")
        self._set_status(team_goal_id, "in_progress", user_id)
        return True

    def mark_ready_for_review(self, team_goal_id: str, user_id: str):
        if user_id != self.user_id:
            raise TeamGoalApprovalNotPermitted("only the owner may advance this team goal")
        self._set_status(team_goal_id, "ready_for_review", user_id)
        return True

    def record_approval(self, team_goal_id: str, user_id: str, decision: str,
                        note: Optional[str] = None, to_status: Optional[str] = None):
        """Record a human decision on the consolidated deliverable and advance
        the team goal status accordingly. ``to_status`` is validated as a legal
        transition from the current status. Atomic: the status change and the
        approval record are written in one transaction (both roll back on error)."""
        if user_id != self.user_id:
            raise TeamGoalApprovalNotPermitted("only the owner may decide")
        if decision not in ("approved", "requested_changes", "rejected"):
            raise ValueError(f"unknown decision: {decision}")
        # Resolve the target status.
        if to_status:
            status = to_status
        else:
            status = {
                "approved": "completed",
                "requested_changes": "revision_requested",
                "rejected": "rejected",
            }[decision]
        # Validate the transition is legal BEFORE opening the transaction.
        self._assert_transition(team_goal_id, status)
        now = _now()
        with self.db.transaction() as c:
            c.execute(
                "UPDATE team_goals SET status=?, decided_by=?, decided_at=?, updated_at=? "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (status, user_id, now, now, team_goal_id,
                 self.tenant_id, self.user_id))
            c.execute(
                "INSERT INTO team_goal_approvals "
                "(id, tenant_id, user_id, team_goal_id, decision, note, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, self.user_id, team_goal_id,
                 decision, (note or "").strip()[:400] or None, now))
        return {"team_goal_id": team_goal_id, "status": status}
