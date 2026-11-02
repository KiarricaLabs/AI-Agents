"""WorkProposalService — M10 Agent-to-Workspace integration, Phase A.

Structured, approval-gated *work proposals* for creating/updating workspace work
(workspace / project / goal / goal_update / assignment / deliverable /
deliverable_version). Phase A strictly:

- records proposal *intent* only (never creates/mutates actual work records),
- validates dependencies (parents must exist and be tenant/user-owned) up front,
- preserves the distinction between suggestions, proposals, approved changes,
  and completed work (via the ``status`` lifecycle),
- never lets agents directly persist deliverable drafts/versions (draft content
  stays proposal-only until the later approval implementation),
- never creates Tasks or Episodes, and never auto-creates work from ordinary
  conversations.

Approval execution (running the real service operation, writing work_links,
idempotent retry) is a later phase — this module only stores and lists proposals.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.workspace import GoalService, GOAL_PATCH_KEYS


def _now():
    return datetime.now(timezone.utc).isoformat()


# work_type -> allowed actions.
ALLOWED = {
    "workspace": {"create", "update"},
    "project": {"create", "update"},
    "goal": {"create"},
    "goal_update": {"update"},
    "assignment": {"create", "update"},
    "deliverable": {"create", "update"},
    "deliverable_version": {"create"},
}

_TERMINAL = {"rejected", "failed"}
_PENDING = {"proposed"}

# Stable set of the six permanent agent slugs (used for approval validation).
AGENT_SLUGS = {
    "tutor", "strategist", "executive_assistant",
    "communications", "soundboard", "workspace_architect",
}


class ProposalNotFound(ValueError):
    pass


class ProposalAlreadyDecided(ValueError):
    pass


class StaleProposal(ValueError):
    pass


class ApprovalNotPermitted(PermissionError):
    pass


class DuplicateProposalTarget(Exception):
    pass


class ProposalExecutionFailed(Exception):
    pass


class TransientApprovalError(Exception):
    pass


class ProposalValidationError(ValueError):
    """Approval-time validation failure (e.g. invalid goal status transition
    or progress value). The value change is never applied and the proposal is
    preserved for correction or rejection."""
    pass


class WorkProposalService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ------------------------------------------------------------------ owners
    def _owned(self, table: str, rid: str) -> bool:
        rows = self.db.query(
            f"SELECT id FROM {table} WHERE id=? AND tenant_id=? AND user_id=?",
            (rid, self.tenant_id, self.user_id))
        return bool(rows)

    def _need(self, value: Optional[str], what: str) -> str:
        if not value:
            raise ValueError(f"{what} is required to create/update this work record")
        return value

    def _belongs(self, child_table: str, child_id: str, parent_col: str, parent_id: str):
        rows = self.db.query(
            f"SELECT id FROM {child_table} WHERE id=? AND tenant_id=? AND {parent_col}=?",
            (child_id, self.tenant_id, parent_id))
        if not rows:
            raise ValueError(
                f"relationship integrity: {child_table} {child_id} does not belong to "
                f"{parent_col}={parent_id}")

    # ------------------------------------------------- validate + resolve deps
    def _validate_and_resolve(self, work_type: str, action: str, payload: Dict[str, Any],
                              target_id: Optional[str]):
        """Validate ownership/dependencies and resolve normalized parent IDs.

        Returns (workspace_id, project_id, goal_id, subject_id). Raises
        ValueError with a meaningful message on any missing/invalid dependency,
        never silently inventing a parent record.
        """
        workspace_id = payload.get("workspace_id") or None
        project_id = payload.get("project_id") or None
        goal_id = payload.get("goal_id") or None
        subject_id = payload.get("agent_id") or None
        tid = target_id or payload.get("target_id") or None

        if work_type == "workspace":
            if action == "update":
                workspace_id = self._need(tid, "target_id (workspace)")
                self._owned_check("workspaces", workspace_id)
        elif work_type == "project":
            workspace_id = self._need(workspace_id, "workspace_id")
            self._owned_check("workspaces", workspace_id)
            if action == "update":
                project_id = self._need(tid, "target_id (project)")
                self._owned_check("projects", project_id)
                self._belongs("projects", project_id, "workspace_id", workspace_id)
        elif work_type == "goal":
            if action != "create":
                raise ValueError("goal supports only create; use goal_update for updates")
            project_id = self._need(project_id, "project_id")
            self._owned_check("projects", project_id)
        elif work_type == "goal_update":
            if action != "update":
                raise ValueError("goal_update supports only update")
            goal_id = self._need(tid, "target_id (goal)")
            self._owned_check("goals", goal_id)
            # optional parent cross-check when supplied
            if project_id:
                self._owned_check("projects", project_id)
                self._belongs("goals", goal_id, "project_id", project_id)
        elif work_type == "assignment":
            if action == "create":
                goal_id = self._need(goal_id, "goal_id")
                self._owned_check("goals", goal_id)
                subject_id = self._need(subject_id, "agent_id (subject)")
            else:  # update
                aid = self._need(tid, "target_id (assignment)")
                self._owned_check("assignments", aid)
                if goal_id:
                    self._owned_check("goals", goal_id)
        elif work_type == "deliverable":
            if action == "create":
                project_id = self._need(project_id, "project_id")
                self._owned_check("projects", project_id)
            else:  # update
                self._need(tid, "target_id (deliverable)")
                self._owned_check("deliverables", tid)
        elif work_type == "deliverable_version":
            if action != "create":
                raise ValueError("deliverable_version supports only create (draft proposal)")
            did = self._need(tid, "target_id (deliverable)")
            self._owned_check("deliverables", did)
            payload.setdefault("deliverable_id", did)
        else:
            raise ValueError(f"unsupported work_type: {work_type}")

        return workspace_id, project_id, goal_id, subject_id

    def _owned_check(self, table: str, rid: str):
        if not self._owned(table, rid):
            raise ValueError(f"ownership: no {table} with id {rid} in this tenant/user scope")

    # ------------------------------------------------------------------- core
    def propose(
        self,
        work_type: str,
        agent_id: str,
        *,
        action: str = "create",
        payload: Optional[Dict[str, Any]] = None,
        thread_id: Optional[str] = None,
        reason: Optional[str] = None,
        context: Optional[str] = None,
        confidence: float = 0.5,
        idempotency_key: Optional[str] = None,
        target_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        work_type = (work_type or "").strip()
        action = (action or "create").strip()
        if work_type not in ALLOWED or action not in ALLOWED[work_type]:
            raise ValueError(f"unsupported work_type/action: {work_type}/{action}")
        if not (agent_id or "").strip():
            raise ValueError("agent_id is required")
        payload = dict(payload or {})

        # Idempotency: same tenant + explicit key returns the existing proposal.
        key = (idempotency_key or "").strip() or str(uuid.uuid4())
        existing = self.db.query(
            "SELECT * FROM work_proposals WHERE tenant_id=? AND idempotency_key=?",
            (self.tenant_id, key))
        if existing:
            return {"proposal_id": existing[0]["id"], "reused": True,
                    "status": existing[0]["status"]}

        ws, pr, gl, subj = self._validate_and_resolve(work_type, action, payload, target_id)

        proposal_id = str(uuid.uuid4())
        now = _now()
        self.db.execute(
            "INSERT INTO work_proposals "
            "(id, tenant_id, user_id, agent_id, thread_id, work_type, action, "
            " target_id, workspace_id, project_id, goal_id, subject_id, payload_json, "
            " reason, context, confidence, status, idempotency_key, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (proposal_id, self.tenant_id, self.user_id, agent_id, thread_id,
             work_type, action, target_id or payload.get("target_id"), ws, pr, gl, subj,
             json.dumps(payload), reason, context, float(confidence),
             "proposed", key, now))
        return {"proposal_id": proposal_id, "status": "proposed", "reused": False}

    # ------------------------------------------------------------------ reads
    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status:
            return self.db.query(
                "SELECT * FROM work_proposals WHERE tenant_id=? AND user_id=? AND status=? "
                "ORDER BY created_at DESC", (self.tenant_id, self.user_id, status))
        return self.db.query(
            "SELECT * FROM work_proposals WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC",
            (self.tenant_id, self.user_id))

    def get(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM work_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (proposal_id, self.tenant_id, self.user_id))
        if not rows:
            return None
        p = rows[0]
        try:
            payload = json.loads(p.get("payload_json") or "{}")
        except Exception:
            payload = {}
        return {
            **p,
            "payload": payload,
            "proposed_change": f"{p['action']} {p['work_type']}",
            "expected_result": self._expected_result(p),
            "source_thread_id": p.get("thread_id"),
            "parent": {
                "workspace_id": p.get("workspace_id"),
                "project_id": p.get("project_id"),
                "goal_id": p.get("goal_id"),
            },
            "affected_records": p.get("target_id"),
        }

    @staticmethod
    def _expected_result(p: Dict[str, Any]) -> str:
        wt, act, tid = p.get("work_type", ""), p.get("action", ""), p.get("target_id")
        if act == "create":
            return f"Creates a new {wt}"
        return f"Updates {wt} {tid or ''} on approval"

    # ------------------------------------------------------------- lifecycle
    def _set_status(self, proposal_id: str, status: str, user_id: str) -> bool:
        rows = self.db.query(
            "SELECT status FROM work_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (proposal_id, self.tenant_id, self.user_id))
        if not rows:
            raise ValueError("proposal not found")
        if rows[0]["status"] != "proposed":
            raise ValueError("proposal already decided")
        now = _now()
        self.db.execute(
            "UPDATE work_proposals SET status=?, decided_at=? WHERE id=? "
            "AND tenant_id=? AND user_id=? AND status='proposed'",
            (status, now, proposal_id, self.tenant_id, self.user_id))
        return True

    def reject(self, proposal_id: str, user_id: str, reason: Optional[str] = None):
        """Human rejection. Terminal; writes a dedicated rejection_reason so the
        reason is never lost or conflated with the proposal context."""
        rows = self.db.query(
            "SELECT * FROM work_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (proposal_id, self.tenant_id, self.user_id))
        if not rows:
            raise ProposalNotFound("proposal not found")
        if rows[0]["status"] != "proposed":
            raise ProposalAlreadyDecided("proposal already decided")
        now = _now()
        detail = (reason or "").strip()[:400]
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE work_proposals SET status='rejected', decided_at=?, decided_by=?, "
                "rejection_reason=? WHERE id=? AND tenant_id=? AND user_id=? AND status='proposed'",
                (now, user_id, detail or None, proposal_id, self.tenant_id, self.user_id))
            if cur.rowcount == 0:
                raise ProposalAlreadyDecided("proposal already decided")
        return True

    def mark_failed(self, proposal_id: str, error: Optional[str] = None) -> bool:
        """Preserve the proposal on a real failure so it can be retried safely."""
        self._set_status(proposal_id, "failed", self.user_id)
        return True

    def expire_stale(self) -> int:
        rows = self.db.query(
            "SELECT id FROM work_proposals WHERE tenant_id=? AND user_id=? AND status='proposed'",
            (self.tenant_id, self.user_id))
        count = 0
        for r in rows:
            self.db.execute(
                "UPDATE work_proposals SET status='stale', decided_at=? WHERE id=? "
                "AND tenant_id=? AND user_id=? AND status='proposed'",
                (_now(), r["id"], self.tenant_id, self.user_id))
            count += 1
        return count

    # ------------------------------------------------------- Phase C approval
    def approve(self, proposal_id: str, approver_user_id: str) -> Dict[str, Any]:
        """Human-controlled approval. Atomic: one transaction performs the guarded
        status update, the real workspace mutation, the work_links insert, and the
        result metadata update. Any failure rolls back leaving the proposal
        retryable (proposed) unless a deterministic duplicate is marked failed.
        Idempotent: a repeat of an already-approved proposal returns its result.
        """
        rows = self.db.query(
            "SELECT * FROM work_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (proposal_id, self.tenant_id, self.user_id))
        if not rows:
            raise ProposalNotFound("proposal not found")
        p = rows[0]
        if approver_user_id != self.user_id:
            raise ApprovalNotPermitted("only the proposal owner may approve")
        if approver_user_id == p["agent_id"]:
            raise ApprovalNotPermitted("an agent cannot approve its own proposal")
        if p["status"] != "proposed":
            if p["status"] == "approved" and p["result_id"]:
                return {"status": "approved", "proposal_id": proposal_id,
                        "work_type": p["work_type"], "work_id": p["result_id"],
                        "result_id": p["result_id"]}
            raise ProposalAlreadyDecided("proposal already decided")

        payload = json.loads(p["payload_json"] or "{}")
        try:
            self._revalidate(p, payload)
        except StaleProposal as e:
            self._mark_stale(proposal_id)
            raise StaleProposal(str(e)) from None

        now = _now()
        work_id = None
        try:
            with self.db.transaction() as c:
                c.row_factory = sqlite3.Row
                cur = c.execute(
                    "UPDATE work_proposals SET status='approved' WHERE id=? "
                    "AND tenant_id=? AND user_id=? AND status='proposed'",
                    (proposal_id, self.tenant_id, self.user_id))
                if cur.rowcount == 0:
                    raise ProposalAlreadyDecided("proposal already decided")
                work_id = self._execute_create(c, p, payload, now)
                c.execute(
                    "INSERT INTO work_links "
                    "(id,tenant_id,user_id,agent_id,work_type,work_id,thread_id,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), self.tenant_id, self.user_id, p["agent_id"],
                     p["work_type"], work_id, p.get("thread_id"), now))
                c.execute(
                    "UPDATE work_proposals SET result_id=?, decided_by=?, decided_at=? "
                    "WHERE id=?",
                    (work_id, approver_user_id, now, proposal_id))
        except StaleProposal as e:
            self._mark_stale(proposal_id)
            raise StaleProposal(str(e)) from None
        except DuplicateProposalTarget as e:
            self._mark_failed(proposal_id, approver_user_id, "duplicate target")
            raise ProposalExecutionFailed(str(e)) from None
        except ProposalAlreadyDecided:
            raise
        except ProposalValidationError:
            raise
        except Exception as e:
            # Transient: the transaction rolled back, so the proposal stays
            # 'proposed' and is retryable.
            raise TransientApprovalError(str(e)) from None
        return {"status": "approved", "proposal_id": proposal_id,
                "work_type": p["work_type"], "work_id": work_id, "result_id": work_id}

    def _revalidate(self, p: Dict[str, Any], payload: Dict[str, Any]):
        """Read-only approval-time dependency and ownership revalidation,
        all tenant/user-scoped from server-stored ids."""
        wt, act = p["work_type"], p["action"]

        def owned(table, rid):
            return bool(rid) and bool(self.db.query(
                f"SELECT id FROM {table} WHERE id=? AND tenant_id=? AND user_id=?",
                (rid, self.tenant_id, self.user_id)))

        if wt == "project" and act == "create":
            if not owned("workspaces", payload.get("workspace_id")):
                raise StaleProposal("workspace no longer available or owned")
        elif wt == "goal" and act == "create":
            if not owned("projects", payload.get("project_id")):
                raise StaleProposal("project no longer available or owned")
        elif wt == "goal_update":
            gid = p.get("target_id") or payload.get("target_id")
            rows = self.db.query(
                "SELECT version FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
                (gid, self.tenant_id, self.user_id))
            if not rows:
                raise StaleProposal("goal no longer available or owned")
            base = payload.get("_base_version")
            if base is not None and int(rows[0]["version"]) != int(base):
                raise StaleProposal("goal changed since the proposal was made")
        elif wt == "assignment":
            if not owned("goals", payload.get("goal_id")):
                raise StaleProposal("goal no longer available or owned")
            if payload.get("agent_id") not in AGENT_SLUGS:
                raise StaleProposal("proposed agent is not a recognized team member")
        elif wt == "deliverable":
            if not owned("projects", payload.get("project_id")):
                raise StaleProposal("project no longer available or owned")
        elif wt == "deliverable_version":
            if not owned("deliverables", p.get("target_id") or payload.get("deliverable_id")):
                raise StaleProposal("deliverable no longer available or owned")
        else:
            raise StaleProposal("unsupported work type for approval")

    def _execute_create(self, c, p: Dict[str, Any], payload: Dict[str, Any], now: str) -> str:
        """Execute the real workspace mutation on the transaction cursor. Raises
        StaleProposal / DuplicateProposalTarget for deterministic failures (the
        transaction then rolls back)."""
        wt, act = p["work_type"], p["action"]
        tid = p.get("target_id") or payload.get("target_id")
        uid = str(uuid.uuid4())

        if wt == "project":
            pid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO projects (id,tenant_id,workspace_id,user_id,name,status,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (pid, self.tenant_id, payload["workspace_id"], self.user_id,
                 payload["name"], "active", now))
            return pid
        if wt == "goal":
            gid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO goals "
                "(id,tenant_id,project_id,user_id,title,priority,status,progress,updated_at,version,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (gid, self.tenant_id, payload["project_id"], self.user_id,
                 payload["title"], int(payload.get("priority", 0)), "open", 0, now, 0, now))
            c.execute(
                "INSERT INTO goal_events (id,tenant_id,goal_id,status,detail,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, gid, "created",
                 f"title={payload.get('title', '')}", now))
            return gid
        if wt == "goal_update":
            gid = tid
            row = c.execute(
                "SELECT title,priority,status,progress,version FROM goals "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (gid, self.tenant_id, self.user_id)).fetchone()
            if not row:
                raise StaleProposal("goal no longer available or owned")
            base = payload.get("_base_version")
            if base is not None and int(row["version"]) != int(base):
                raise StaleProposal("goal changed since the proposal was made")
            # Validation parity with GoalService.approve_update / _compute_update.
            # Strip non-patch keys (e.g. the internal _base_version) and reproduce
            # the exact goal patch/state rules; never apply an invalid update.
            patch = {k: payload[k] for k in GOAL_PATCH_KEYS if k in payload}
            try:
                validated = GoalService._validate_patch(None, patch)
                new_title, new_priority, new_status, new_progress = \
                    GoalService._compute_update(None, row, validated)
            except ValueError as e:
                raise ProposalValidationError(str(e)) from None
            up = c.execute(
                "UPDATE goals SET title=?, priority=?, status=?, progress=?, updated_at=?, "
                "version=version+1 WHERE id=? AND tenant_id=? AND version=?",
                (new_title, new_priority, new_status, new_progress, now, gid,
                 self.tenant_id, int(row["version"])))
            if up.rowcount == 0:
                raise StaleProposal("goal changed concurrently")
            c.execute(
                "INSERT INTO goal_events (id,tenant_id,goal_id,status,detail,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, gid, "updated",
                 f"title={new_title} status={new_status} progress={new_progress}", now))
            return gid
        if wt == "assignment":
            agent = payload.get("agent_id") or p.get("subject_id")
            dup = c.execute(
                "SELECT id FROM assignments WHERE tenant_id=? AND goal_id=? AND agent_id=?",
                (self.tenant_id, payload["goal_id"], agent)).fetchone()
            if dup:
                raise DuplicateProposalTarget("assignment already exists for this goal/agent")
            aid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO assignments (id,tenant_id,goal_id,user_id,agent_id,priority,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (aid, self.tenant_id, payload["goal_id"], self.user_id, agent,
                 int(payload.get("priority", 0)), now))
            return aid
        if wt == "deliverable":
            did = str(uuid.uuid4())
            c.execute(
                "INSERT INTO deliverables (id,tenant_id,project_id,user_id,title,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (did, self.tenant_id, payload["project_id"], self.user_id,
                 payload["title"], now))
            return did
        if wt == "deliverable_version":
            did = tid or payload.get("deliverable_id")
            mvrow = c.execute(
                "SELECT COALESCE(MAX(version),0) FROM deliverable_versions "
                "WHERE tenant_id=? AND deliverable_id=?",
                (self.tenant_id, did)).fetchone()
            mv = int(mvrow[0]) + 1
            vid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO deliverable_versions "
                "(id,tenant_id,deliverable_id,version,content,status,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (vid, self.tenant_id, did, mv, payload.get("content", ""), "draft", now))
            return vid
        raise StaleProposal("unsupported work type for approval")

    def _mark_stale(self, proposal_id: str):
        with self.db.transaction() as c:
            c.execute(
                "UPDATE work_proposals SET status='stale', decided_at=? WHERE id=? "
                "AND tenant_id=? AND user_id=? AND status='proposed'",
                (_now(), proposal_id, self.tenant_id, self.user_id))

    def _mark_failed(self, proposal_id: str, approver: str, reason: Optional[str] = None):
        with self.db.transaction() as c:
            c.execute(
                "UPDATE work_proposals SET status='failed', decided_at=?, decided_by=?, "
                "rejection_reason=? WHERE id=? AND tenant_id=? AND user_id=? "
                "AND status='proposed'",
                (_now(), approver, (reason or "")[:400] or None, proposal_id,
                 self.tenant_id, self.user_id))
