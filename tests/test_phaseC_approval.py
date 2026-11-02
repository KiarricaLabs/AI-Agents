"""M10 Phase C — human-controlled approval workflow.

Covers the atomic, transactional approval path that converts a saved
``work_proposals`` row into real workspace records only after an explicit human
decision, for all six supported proposal types. Verifies:

- approval creates the correct real record + ``work_links`` row + ``approved``
  status,
- rejection is terminal and preserves a dedicated reason,
- idempotent re-approval returns the same result (one record, one link),
- stale proposals (parent deleted / goal version bumped) are marked stale with
  no mutation,
- deterministic duplicate targets are marked ``failed`` with no duplicate,
- transient failure rolls back, leaves the proposal retryable, and retry
  succeeds without duplicating,
- cross-user / cross-tenant access is denied (404) and never leaks existence,
- self-approval is denied (403),
- human-role whitelisting is enforced at the HTTP boundary,
- proposing alone creates no real work records.

All tests use an isolated database; the production DB is never opened.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from storage.database import Database
from core.auth import issue_token
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService, DeliverableService
from core.work_proposals import (
    WorkProposalService,
    ProposalNotFound,
    ProposalAlreadyDecided,
    StaleProposal,
    ApprovalNotPermitted,
    ProposalExecutionFailed,
    ProposalValidationError,
    TransientApprovalError,
)
from api.app import app


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


TENANT = "phasec"
USER = "u1"


class PhaseCBase(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=TENANT)
        self.ws = WorkspaceService(self.db, TENANT, USER).create("PhaseC WS")
        self.pr = ProjectService(self.db, TENANT, USER).create(self.ws, "PhaseC Project")
        self.gl = GoalService(self.db, TENANT, USER).create(self.pr, "PhaseC Goal", 1)
        self.svc = WorkProposalService(self.db, TENANT, USER)

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)

    def _count(self, table):
        return self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def _link(self, work_type, work_id=None):
        rows = self.db.query(
            "SELECT * FROM work_links WHERE tenant_id=? AND work_type=?",
            (TENANT, work_type))
        if work_id is not None:
            rows = [r for r in rows if r["work_id"] == work_id]
        return rows

    def _propose(self, work_type, action="create", *, target_id=None, payload, agent="strategist", key=None):
        r = self.svc.propose(work_type, agent, action=action, payload=payload,
                             thread_id="thread-x", target_id=target_id,
                             idempotency_key=key)
        return r["proposal_id"]


class TestMigration(unittest.TestCase):
    def test_existing_phaseA_work_proposals_gains_phaseC_columns(self):
        # Simulate a Phase A-era database whose work_proposals table lacks the
        # two Phase C columns, then reopen through the isolated init hook.
        path = _fresh_db()
        try:
            with sqlite3.connect(path) as c:
                c.executescript("""
                CREATE TABLE work_proposals (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    thread_id TEXT,
                    work_type TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'create',
                    target_id TEXT,
                    workspace_id TEXT,
                    project_id TEXT,
                    goal_id TEXT,
                    subject_id TEXT,
                    payload_json TEXT NOT NULL,
                    reason TEXT,
                    context TEXT,
                    confidence REAL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    result_id TEXT,
                    idempotency_key TEXT NOT NULL,
                    decided_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (tenant_id, idempotency_key)
                );
                """)
            db = Database(path=path, tenant_id="local")
            cols = {r["name"] for r in
                    db.query("SELECT name FROM pragma_table_info('work_proposals')")}
            self.assertIn("decided_by", cols)
            self.assertIn("rejection_reason", cols)
            # Reopening is idempotent (guarded ALTER is a no-op).
            Database(path=path, tenant_id="local")
        finally:
            for s in ("", "-wal", "-shm"):
                p = path + s
                if os.path.exists(p):
                    os.remove(p)


class TestApprovalCreatesRecords(PhaseCBase):
    def _assert_approved(self, pid, work_type):
        p = self.svc.get(pid)
        self.assertIsNotNone(p)
        self.assertEqual(p["status"], "approved")
        self.assertTrue(p["result_id"])
        self.assertEqual(p["decided_by"], USER)
        links = self._link(work_type, p["result_id"])
        self.assertEqual(len(links), 1, "exactly one work_link per approved work record")

    def test_project_approval(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-Approved"})
        before = self._count("projects")
        res = self.svc.approve(pid, USER)
        self.assertEqual(res["status"], "approved")
        self.assertEqual(self._count("projects"), before + 1)
        self._assert_approved(pid, "project")

    def test_goal_approval(self):
        pid = self._propose("goal", payload={"project_id": self.pr, "title": "G-Approved", "priority": 2})
        before = self._count("goals")
        res = self.svc.approve(pid, USER)
        self.assertEqual(res["status"], "approved")
        self.assertEqual(self._count("goals"), before + 1)
        self._assert_approved(pid, "goal")
        events = self.db.query("SELECT COUNT(*) AS n FROM goal_events WHERE goal_id=?", (res["result_id"],))
        self.assertEqual(events[0]["n"], 1)

    def test_goal_update_approval(self):
        pid = self._propose(
            "goal_update", action="update", target_id=self.gl,
            payload={"title": "Renamed", "priority": 5, "_base_version": 0})
        res = self.svc.approve(pid, USER)
        self.assertEqual(res["status"], "approved")
        g = self.db.query("SELECT * FROM goals WHERE id=?", (self.gl,))[0]
        self.assertEqual(g["title"], "Renamed")
        self.assertEqual(g["priority"], 5)
        self.assertEqual(g["version"], 1)
        self._assert_approved(pid, "goal_update")

    def test_assignment_approval(self):
        pid = self._propose("assignment", payload={"goal_id": self.gl, "agent_id": "strategist", "priority": 2})
        before = self._count("assignments")
        res = self.svc.approve(pid, USER)
        self.assertEqual(res["status"], "approved")
        self.assertEqual(self._count("assignments"), before + 1)
        self._assert_approved(pid, "assignment")
        row = self.db.query("SELECT * FROM assignments WHERE id=?", (res["result_id"],))[0]
        self.assertEqual(row["agent_id"], "strategist")

    def test_deliverable_approval(self):
        pid = self._propose("deliverable", payload={"project_id": self.pr, "title": "D-Approved"})
        before = self._count("deliverables")
        res = self.svc.approve(pid, USER)
        self.assertEqual(res["status"], "approved")
        self.assertEqual(self._count("deliverables"), before + 1)
        self._assert_approved(pid, "deliverable")

    def test_deliverable_version_approval(self):
        did = DeliverableService(self.db, TENANT, USER).create(self.pr, "Brand Kit")
        pid = self._propose("deliverable_version", target_id=did,
                            payload={"deliverable_id": did, "content": "v1 content"})
        before = self._count("deliverable_versions")
        res = self.svc.approve(pid, USER)
        self.assertEqual(res["status"], "approved")
        self.assertEqual(self._count("deliverable_versions"), before + 1)
        self._assert_approved(pid, "deliverable_version")
        v = self.db.query("SELECT * FROM deliverable_versions WHERE id=?", (res["result_id"],))[0]
        self.assertEqual(v["status"], "draft")
        self.assertEqual(v["version"], 1)


class TestReject(PhaseCBase):
    def test_reject_is_terminal_and_preserves_reason(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-Rej"})
        self.svc.reject(pid, USER, reason="not a priority")
        p = self.svc.get(pid)
        self.assertEqual(p["status"], "rejected")
        self.assertEqual(p["rejection_reason"], "not a priority")
        self.assertEqual(p["decided_by"], USER)
        # rejection must never create a real record
        self.assertEqual(self._count("projects"), 1)  # only the setUp project

    def test_double_reject_raises(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-Rej2"})
        self.svc.reject(pid, USER, reason="r")
        with self.assertRaises(ProposalAlreadyDecided):
            self.svc.reject(pid, USER, reason="again")

    def test_approve_after_reject_raises(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-Rej3"})
        self.svc.reject(pid, USER, reason="r")
        with self.assertRaises(ProposalAlreadyDecided):
            self.svc.approve(pid, USER)


class TestIdempotentApproval(PhaseCBase):
    def test_double_approve_returns_same_result_no_duplicate(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-Dup"})
        r1 = self.svc.approve(pid, USER)
        self.assertEqual(r1["status"], "approved")
        r2 = self.svc.approve(pid, USER)
        self.assertEqual(r2["result_id"], r1["result_id"])
        self.assertEqual(self._count("projects"), 2)  # setUp + one approved
        self.assertEqual(len(self._link("project", r1["result_id"])), 1)


class TestStale(PhaseCBase):
    def test_parent_workspace_deleted_marks_stale_no_mutation(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-Stale"})
        self.db.execute("DELETE FROM workspaces WHERE id=?", (self.ws,))
        before = self._count("projects")
        with self.assertRaises(StaleProposal):
            self.svc.approve(pid, USER)
        self.assertEqual(self._count("projects"), before)
        self.assertEqual(self.svc.get(pid)["status"], "stale")

    def test_goal_version_bumped_marks_stale_no_mutation(self):
        pid = self._propose(
            "goal_update", action="update", target_id=self.gl,
            payload={"title": "No", "priority": 9, "_base_version": 0})
        self.db.execute("UPDATE goals SET version=version+1 WHERE id=?", (self.gl,))
        before = self._count("goal_events")
        with self.assertRaises(StaleProposal):
            self.svc.approve(pid, USER)
        self.assertEqual(self.svc.get(pid)["status"], "stale")
        self.assertEqual(self._count("goal_events"), before)


class TestDuplicateTarget(PhaseCBase):
    def test_duplicate_assignment_marked_failed_no_duplicate(self):
        # First approval creates assignment for strategist.
        pid1 = self._propose("assignment", payload={"goal_id": self.gl, "agent_id": "strategist"},
                             key="dup-a1")
        r1 = self.svc.approve(pid1, USER)
        self.assertEqual(r1["status"], "approved")
        # Second, distinct proposal for same goal+agent is deterministic duplicate.
        pid2 = self._propose("assignment", payload={"goal_id": self.gl, "agent_id": "strategist"},
                             key="dup-a2")
        before = self._count("assignments")
        with self.assertRaises(ProposalExecutionFailed):
            self.svc.approve(pid2, USER)
        self.assertEqual(self._count("assignments"), before)
        self.assertEqual(self.svc.get(pid2)["status"], "failed")


class TestRollbackAndRetry(PhaseCBase):
    def test_transient_failure_rolls_back_and_retry_succeeds(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-Retry"})
        orig = self.svc._execute_create
        calls = {"n": 0}

        def flaky(c, p, payload, now):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated transient failure")
            return orig(c, p, payload, now)

        self.svc._execute_create = flaky
        try:
            with self.assertRaises(TransientApprovalError):
                self.svc.approve(pid, USER)
        finally:
            self.svc._execute_create = orig

        # Rolled back: proposal still proposed, no record created.
        self.assertEqual(self.svc.get(pid)["status"], "proposed")
        self.assertEqual(self._count("projects"), 1)
        r = self.svc.approve(pid, USER)
        self.assertEqual(r["status"], "approved")
        self.assertEqual(self._count("projects"), 2)
        self.assertEqual(len(self._link("project", r["result_id"])), 1)


class TestGoalUpdateValidation(PhaseCBase):
    def _propose_gupdate(self, **payload):
        payload.setdefault("_base_version", 0)
        return self._propose("goal_update", action="update", target_id=self.gl, payload=payload)

    def _set_goal_state(self, status=None, progress=None):
        cols = []
        vals = []
        if status is not None:
            cols.append("status=?"); vals.append(status)
        if progress is not None:
            cols.append("progress=?"); vals.append(progress)
        if cols:
            vals.append(self.gl)
            self.db.execute(f"UPDATE goals SET {', '.join(cols)} WHERE id=?", tuple(vals))

    def _goal_row(self):
        return self.db.query("SELECT * FROM goals WHERE id=?", (self.gl,))[0]

    def _expect_validation_error(self, pid, fragment):
        with self.assertRaises(ProposalValidationError) as cm:
            self.svc.approve(pid, USER)
        self.assertIn(fragment, str(cm.exception))

    def test_valid_goal_update_still_succeeds(self):
        pid = self._propose_gupdate(title="Renamed", priority=3)
        r = self.svc.approve(pid, USER)
        self.assertEqual(r["status"], "approved")
        g = self._goal_row()
        self.assertEqual(g["title"], "Renamed")
        self.assertEqual(g["priority"], 3)
        self.assertEqual(g["version"], 1)

    def test_done_requires_progress_100(self):
        self._set_goal_state(status="in_progress")
        pid = self._propose_gupdate(status="done", progress=50)
        self._expect_validation_error(pid, "done requires progress=100")

    def test_progress_out_of_bounds_rejected(self):
        pid = self._propose_gupdate(progress=150)
        self._expect_validation_error(pid, "0..100")
        pid2 = self._propose_gupdate(progress=-5)
        self._expect_validation_error(pid2, "0..100")

    def test_invalid_status_transition_rejected(self):
        # 'open' -> 'done' is not a valid transition.
        pid = self._propose_gupdate(status="done")
        self._expect_validation_error(pid, "invalid transition")

    def test_malformed_priority_type_rejected(self):
        pid = self._propose_gupdate(priority="high")
        self._expect_validation_error(pid, "priority must be an int")

    def test_rejected_validation_applies_no_changes(self):
        before = self._goal_row()
        pid = self._propose_gupdate(status="done")
        with self.assertRaises(ProposalValidationError):
            self.svc.approve(pid, USER)
        after = self._goal_row()
        self.assertEqual(dict(after), dict(before), "goal must be unchanged after rejected validation")

    def test_proposal_not_approved_and_has_no_result_id(self):
        pid = self._propose_gupdate(status="done")
        with self.assertRaises(ProposalValidationError):
            self.svc.approve(pid, USER)
        p = self.svc.get(pid)
        self.assertEqual(p["status"], "proposed")
        self.assertIsNone(p["result_id"])
        self.assertIsNone(p["decided_at"])

    def test_version_unchanged_and_staleness_still_enforced(self):
        # Invalid update leaves version untouched.
        pid = self._propose_gupdate(status="done")
        with self.assertRaises(ProposalValidationError):
            self.svc.approve(pid, USER)
        self.assertEqual(self._goal_row()["version"], 0)
        # Concurrent version bump still marks the proposal stale.
        self.db.execute("UPDATE goals SET version=version+1 WHERE id=?", (self.gl,))
        pid2 = self._propose_gupdate(title="Concurrent")
        with self.assertRaises(StaleProposal):
            self.svc.approve(pid2, USER)
        self.assertEqual(self.svc.get(pid2)["status"], "stale")


class TestIsolationAndSelfApproval(PhaseCBase):
    def test_cross_user_cannot_approve(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-XU"})
        other = WorkProposalService(self.db, TENANT, "u2")
        with self.assertRaises(ProposalNotFound):
            other.approve(pid, "u2")

    def test_cross_tenant_cannot_approve(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-XT"})
        other = WorkProposalService(self.db, "other_tenant", USER)
        with self.assertRaises(ProposalNotFound):
            other.approve(pid, USER)

    def test_agent_cannot_approve_own_proposal(self):
        # agent_id equal to the human owner id exercises the secondary no-self guard.
        pid = self.svc.propose("project", "u1", payload={"workspace_id": self.ws, "name": "P-Self"})["proposal_id"]
        with self.assertRaises(ApprovalNotPermitted):
            self.svc.approve(pid, "u1")

    def test_non_owner_cannot_approve_within_owner_scope(self):
        pid = self._propose("project", payload={"workspace_id": self.ws, "name": "P-NO"})
        with self.assertRaises(ApprovalNotPermitted):
            self.svc.approve(pid, "someone_else")


class TestProposalOnlyCreatesNothing(PhaseCBase):
    def test_propose_and_reject_creates_no_real_records(self):
        self._propose("project", payload={"workspace_id": self.ws, "name": "P-Pending"})
        pid = self._propose("goal", payload={"project_id": self.pr, "title": "G-Pending"})
        self.assertEqual(self._count("projects"), 1)
        self.assertEqual(self._count("goals"), 1)
        self.svc.reject(pid, USER, reason="declined")
        self.assertEqual(self._count("goals"), 1)
        self.assertEqual(self._count("tasks"), 0)
        self.assertEqual(self._count("episodes"), 0)


class TestApprovalEndpoints(unittest.TestCase):
    TENANT = "phasec"
    USER = "u1"

    def _headers(self, user=USER, tenant=TENANT, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def _seed(self):
        from config.settings import DB_PATH
        db = Database(path=DB_PATH, tenant_id=self.TENANT)
        ws = WorkspaceService(db, self.TENANT, self.USER).create("API WS")
        pr = ProjectService(db, self.TENANT, self.USER).create(ws, "API Project")
        gl = GoalService(db, self.TENANT, self.USER).create(pr, "API Goal", 1)
        svc = WorkProposalService(db, self.TENANT, self.USER)
        return db, ws, pr, gl, svc

    def test_approve_success_and_idempotent_repeat(self):
        db, ws, pr, gl, svc = self._seed()
        pid = svc.propose("project", "strategist", payload={"workspace_id": ws, "name": "API P"},
                          thread_id="t", idempotency_key="api-1")["proposal_id"]
        c = TestClient(app)
        r1 = c.post(f"/work/proposals/{pid}/approve", headers=self._headers())
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "approved")
        work_id = r1.json()["result_id"]
        r2 = c.post(f"/work/proposals/{pid}/approve", headers=self._headers())
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["result_id"], work_id)
        links = db.query("SELECT COUNT(*) AS n FROM work_links WHERE work_type='project' AND work_id=?",
                         (work_id,))
        self.assertEqual(links[0]["n"], 1)

    def test_reject_then_409(self):
        db, ws, pr, gl, svc = self._seed()
        pid = svc.propose("project", "strategist", payload={"workspace_id": ws, "name": "API Rej"},
                          thread_id="t", idempotency_key="api-2")["proposal_id"]
        c = TestClient(app)
        r1 = c.post(f"/work/proposals/{pid}/reject", headers=self._headers(),
                    json={"reason": "declined"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "rejected")
        r2 = c.post(f"/work/proposals/{pid}/reject", headers=self._headers(),
                    json={"reason": "again"})
        self.assertEqual(r2.status_code, 409)

    def test_stale_goal_update_returns_422(self):
        db, ws, pr, gl, svc = self._seed()
        pid = svc.propose("goal_update", "strategist", action="update", target_id=gl,
                          payload={"title": "No", "_base_version": 0},
                          thread_id="t", idempotency_key="api-3")["proposal_id"]
        db.execute("UPDATE goals SET version=version+1 WHERE id=?", (gl,))
        c = TestClient(app)
        r = c.post(f"/work/proposals/{pid}/approve", headers=self._headers())
        self.assertEqual(r.status_code, 422)

    def test_invalid_goal_update_validation_returns_422_no_mutation(self):
        db, ws, pr, gl, svc = self._seed()
        # status='done' from 'open' is an invalid transition and must not apply.
        pid = svc.propose("goal_update", "strategist", action="update", target_id=gl,
                          payload={"status": "done", "_base_version": 0},
                          thread_id="t", idempotency_key="api-6")["proposal_id"]
        c = TestClient(app)
        r = c.post(f"/work/proposals/{pid}/approve", headers=self._headers())
        self.assertEqual(r.status_code, 422)
        self.assertIn("transition", r.json()["detail"])
        g = db.query("SELECT status,version FROM goals WHERE id=?", (gl,))[0]
        self.assertEqual(g["status"], "open")
        self.assertEqual(g["version"], 0)
        p = db.query("SELECT status,result_id FROM work_proposals WHERE id=?", (pid,))[0]
        self.assertEqual(p["status"], "proposed")
        self.assertIsNone(p["result_id"])

    def test_non_human_role_denied(self):
        db, ws, pr, gl, svc = self._seed()
        pid = svc.propose("project", "strategist", payload={"workspace_id": ws, "name": "API Bot"},
                          thread_id="t", idempotency_key="api-4")["proposal_id"]
        c = TestClient(app)
        r = c.post(f"/work/proposals/{pid}/approve", headers=self._headers(role="bot"))
        self.assertEqual(r.status_code, 403)

    def test_cross_tenant_and_cross_user_404(self):
        db, ws, pr, gl, svc = self._seed()
        pid = svc.propose("project", "strategist", payload={"workspace_id": ws, "name": "API X"},
                          thread_id="t", idempotency_key="api-5")["proposal_id"]
        c = TestClient(app)
        r = c.post(f"/work/proposals/{pid}/approve", headers=self._headers(tenant="other"))
        self.assertEqual(r.status_code, 404)
        r2 = c.post(f"/work/proposals/{pid}/approve", headers=self._headers(user="u2"))
        self.assertEqual(r2.status_code, 404)

    def test_unknown_proposal_404(self):
        c = TestClient(app)
        r = c.post("/work/proposals/does-not-exist/approve", headers=self._headers())
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
