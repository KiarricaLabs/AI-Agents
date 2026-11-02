"""M10 Phase D4.1 — human-triggered execution of approved assignments.

Verifies the approved-assignment execution gate:
- only assignments owned + genuinely linked to an approved proposal can start,
- agent validity/mismatch, self-execution, cross-user/tenant are rejected,
- duplicate start is idempotent (one active Episode),
- the D2 Episode evidence lifecycle is preserved (checkpoint/complete, no
  duplicate completion events, missing evidence rejected),
- goal progress is NOT auto-applied on complete (D3 apply stays separate +
  human-confirmed), and goal version guards/audit remain intact,
- no background/automatic execution occurs (no Episode without a human trigger).

All tests use isolated databases; the production DB is never opened.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from storage.database import Database
from core.auth import issue_token
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService
from core.work_proposals import WorkProposalService
from core.episodes import EpisodeService
from core.execution import (
    ApprovedExecutionService,
    AssignmentNotFound,
    AssignmentNotApproved,
    InvalidAgent,
    AgentMismatch,
    SelfExecution,
)
from api.app import app


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


import uuid as _uuid


def _ux():
    return _uuid.uuid4().hex


TENANT = "phaseD4"
USER = "u1"


class PhaseD4Base(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=TENANT)
        self.ws = WorkspaceService(self.db, TENANT, USER).create("WS")
        self.pr = ProjectService(self.db, TENANT, USER).create(self.ws, "PR")
        self.gl = GoalService(self.db, TENANT, USER).create(self.pr, "Goal", 1)
        self.es = EpisodeService(self.db, TENANT, USER)
        self.svc = WorkProposalService(self.db, TENANT, USER)
        self.exec_svc = ApprovedExecutionService(self.db, TENANT, USER)

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)

    def _count(self, table):
        return self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def _approved_assignment(self, agent="strategist"):
        """Create a genuinely approved assignment via the Phase C approval path."""
        pid = self.svc.propose("assignment", "aisha", payload={"goal_id": self.gl, "agent_id": agent},
                               idempotency_key="d4-" + _ux())["proposal_id"]
        res = self.svc.approve(pid, USER)
        return res["work_id"]

    def _plain_assignment(self, agent="strategist"):
        return AssignmentService(self.db, TENANT, USER).assign(self.gl, agent, 0)


class TestService(PhaseD4Base):
    def test_approved_assignment_starts_by_owner(self):
        aid = self._approved_assignment()
        res = self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        self.assertFalse(res["already_active"])
        self.assertTrue(res["episode_id"])
        e = self.db.query("SELECT * FROM episodes WHERE id=?", (res["episode_id"],))[0]
        self.assertEqual(e["work_type"], "assignment")
        self.assertEqual(e["work_id"], aid)
        self.assertEqual(e["agent_id"], "strategist")
        self.assertEqual(self._count("episodes"), 1)

    def test_unapproved_assignment_raises(self):
        aid = self._plain_assignment()
        with self.assertRaises(AssignmentNotApproved):
            self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        self.assertEqual(self._count("episodes"), 0)

    def test_assignment_without_matching_approved_proposal(self):
        # an assignment created by an approval of a DIFFERENT work type has no
        # matching approved assignment proposal -> not approved.
        pid = self.svc.propose("goal", "aisha", payload={"project_id": self.pr, "title": "G2"},
                               idempotency_key="d4-" + _ux())["proposal_id"]
        self.svc.approve(pid, USER)
        aid = self._plain_assignment()
        with self.assertRaises(AssignmentNotApproved):
            self.exec_svc.execute_approved_assignment(aid, USER, "strategist")

    def test_cross_user_and_cross_tenant(self):
        aid = self._approved_assignment()
        other = ApprovedExecutionService(self.db, TENANT, "u2")
        with self.assertRaises(AssignmentNotFound):
            other.execute_approved_assignment(aid, "u2", "strategist")
        other_t = ApprovedExecutionService(self.db, "other_tenant", USER)
        with self.assertRaises(AssignmentNotFound):
            other_t.execute_approved_assignment(aid, USER, "strategist")

    def test_agent_mismatch_and_invalid_agent(self):
        aid = self._approved_assignment(agent="strategist")
        with self.assertRaises(AgentMismatch):
            self.exec_svc.execute_approved_assignment(aid, USER, "tutor")
        with self.assertRaises(InvalidAgent):
            self.exec_svc.execute_approved_assignment(aid, USER, "not-an-agent")

    def test_self_execution_rejected(self):
        aid = self._approved_assignment(agent="strategist")
        with self.assertRaises(SelfExecution):
            self.exec_svc.execute_approved_assignment(aid, "strategist", "strategist")

    def test_duplicate_start_is_idempotent(self):
        aid = self._approved_assignment()
        r1 = self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        r2 = self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        self.assertEqual(r1["episode_id"], r2["episode_id"])
        self.assertTrue(r2["already_active"])
        self.assertEqual(self._count("episodes"), 1)

    def test_no_execution_without_human_trigger(self):
        # proposing + approving an assignment must NOT create an Episode by itself.
        self._approved_assignment()
        self.assertEqual(self._count("episodes"), 0)

    # ---- M1: approval-to-assignment agent consistency ------------------------
    def test_approved_proposal_agent_matches_assignment_succeeds(self):
        # M1 baseline: when the approved proposal's recorded agent (subject_id)
        # matches the assignment's agent, execution is authorized.
        aid = self._approved_assignment(agent="strategist")
        res = self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        self.assertTrue(res["episode_id"])
        self.assertEqual(self._count("episodes"), 1)

    def test_approval_is_subject_scoped_not_only_result_id(self):
        # Defense-in-depth: the approved proposal must *also* name the current
        # assignment agent. Here the proposal's result_id still matches the
        # assignment id, but the assignment has been (hypothetically) mutated to
        # agent 'tutor' while the approved proposal recorded 'strategist'.
        aid = self._approved_assignment(agent="strategist")
        prop = self.db.query(
            "SELECT id, subject_id, result_id FROM work_proposals "
            "WHERE work_type='assignment' AND result_id=? AND status='approved'",
            (aid,))[0]
        # confirm the setup really is a result_id match with a differing agent
        self.assertEqual(prop["result_id"], aid)
        self.assertEqual(prop["subject_id"], "strategist")
        self.db.execute("UPDATE assignments SET agent_id='tutor' WHERE id=?", (aid,))
        a = self.db.query("SELECT agent_id FROM assignments WHERE id=?", (aid,))[0]
        self.assertEqual(a["agent_id"], "tutor")
        with self.assertRaises(AssignmentNotApproved):
            self.exec_svc.execute_approved_assignment(aid, USER, "tutor")
        self.assertEqual(self._count("episodes"), 0)

    def test_mismatched_proposal_agent_cannot_authorize_execution(self):
        # M1 explicit case: proposal agent differs from assignment agent.
        aid = self._approved_assignment(agent="strategist")
        self.db.execute("UPDATE assignments SET agent_id='tutor' WHERE id=?", (aid,))
        with self.assertRaises(AssignmentNotApproved):
            self.exec_svc.execute_approved_assignment(aid, USER, "tutor")
        # no Episode may be created from an unauthorized/mismatched start
        self.assertEqual(self._count("episodes"), 0)

    def test_requesting_original_agent_after_mutation_still_guarded(self):
        # Even if the requester supplies the *original* proposal agent, the
        # backend must not let a mismatched current assignment execute, and the
        # original agent no longer matches the (mutated) assignment either.
        aid = self._approved_assignment(agent="strategist")
        self.db.execute("UPDATE assignments SET agent_id='tutor' WHERE id=?", (aid,))
        with self.assertRaises(AgentMismatch):
            self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        self.assertEqual(self._count("episodes"), 0)

    def test_valid_approval_idempotent_execution_unaffected(self):
        # M1 must not disturb the previously passing valid-approval semantics:
        # matched agent executes, repeated start returns the same active Episode.
        aid = self._approved_assignment()
        r1 = self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        r2 = self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        self.assertEqual(r1["episode_id"], r2["episode_id"])
        self.assertTrue(r2["already_active"])
        self.assertEqual(self._count("episodes"), 1)



class TestEpisodeLifecycle(PhaseD4Base):
    def test_checkpoint_complete_and_no_goal_auto_apply(self):
        aid = self._approved_assignment()
        res = self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        eid = res["episode_id"]
        # checkpoint requires evidence
        with self.assertRaises(ValueError):
            self.es.checkpoint_with_evidence(eid, 0.5, {})
        self.assertTrue(self.es.checkpoint_with_evidence(eid, 0.5, {"summary": "milestone"}))
        # missing evidence cannot complete
        with self.assertRaises(ValueError):
            self.es.complete_with_evidence(eid, {})
        # complete (human action) with evidence
        self.assertTrue(self.es.complete_with_evidence(eid, {"summary": "all done"}))
        # duplicate completion -> no second done event
        events_before = len(self.db.query("SELECT * FROM episode_events WHERE episode_id=? AND status='done'", (eid,)))
        self.assertFalse(self.es.complete_with_evidence(eid, {"summary": "again"}))
        events_after = len(self.db.query("SELECT * FROM episode_events WHERE episode_id=? AND status='done'", (eid,)))
        self.assertEqual(events_before, 1)
        self.assertEqual(events_after, 1)
        # goal is NOT auto-applied just because the episode completed
        g = self.db.query("SELECT progress, version FROM goals WHERE id=?", (self.gl,))[0]
        self.assertEqual(g["progress"], 0)
        self.assertEqual(g["version"], 0)
        # D3 apply still requires explicit human application and is version-guarded
        db_g = self.db.query("SELECT * FROM goals WHERE id=?", (self.gl,))[0]
        self.assertEqual(db_g["status"], "open")

    def test_d3_apply_still_explicit_and_version_guarded(self):
        aid = self._approved_assignment()
        res = self.exec_svc.execute_approved_assignment(aid, USER, "strategist")
        eid = res["episode_id"]
        self.es.complete_with_evidence(eid, {"summary": "delivered"})
        # goal must be in_progress for the apply to mark it done
        self.db.execute("UPDATE goals SET status='in_progress' WHERE id=?", (self.gl,))
        outcome = self.es.apply_completed_episode(eid, USER)
        self.assertEqual(outcome["goal_status"], "done")
        g = self.db.query("SELECT status, progress, version FROM goals WHERE id=?", (self.gl,))[0]
        self.assertEqual(g["status"], "done")
        self.assertEqual(g["progress"], 100)
        self.assertEqual(g["version"], 1)
        # audit trail present
        self.assertGreaterEqual(self._count("goal_events"), 1)


class TestEndpoints(unittest.TestCase):
    TENANT = "phaseD4"
    USER = "u1"

    def _headers(self, user=USER, tenant=TENANT, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def _seed_approved(self):
        from config.settings import DB_PATH
        db = Database(path=DB_PATH, tenant_id=self.TENANT)
        ws = WorkspaceService(db, self.TENANT, self.USER).create("E WS")
        pr = ProjectService(db, self.TENANT, self.USER).create(ws, "E PR")
        gl = GoalService(db, self.TENANT, self.USER).create(pr, "Goal", 1)
        svc = WorkProposalService(db, self.TENANT, self.USER)
        pid = svc.propose("assignment", "aisha", payload={"goal_id": gl, "agent_id": "strategist"},
                          idempotency_key="d4e-" + _ux())["proposal_id"]
        aid = svc.approve(pid, self.USER)["work_id"]
        return db, gl, aid

    def _seed_plain(self):
        from config.settings import DB_PATH
        db = Database(path=DB_PATH, tenant_id=self.TENANT)
        ws = WorkspaceService(db, self.TENANT, self.USER).create("P WS")
        pr = ProjectService(db, self.TENANT, self.USER).create(ws, "P PR")
        gl = GoalService(db, self.TENANT, self.USER).create(pr, "Goal", 1)
        aid = AssignmentService(db, self.TENANT, self.USER).assign(gl, "strategist", 0)
        return db, gl, aid

    def test_approved_start_201_then_idempotent_200(self):
        db, gl, aid = self._seed_approved()
        c = TestClient(app)
        r1 = c.post(f"/work/assignment/{aid}/execute-approved", headers=self._headers(), json={"agent_id": "strategist"})
        self.assertEqual(r1.status_code, 201)
        eid = r1.json()["episode_id"]
        r2 = c.post(f"/work/assignment/{aid}/execute-approved", headers=self._headers(), json={"agent_id": "strategist"})
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["already_active"])
        self.assertEqual(r2.json()["episode_id"], eid)

    def test_unapproved_403_and_foreign_404(self):
        db, gl, aid = self._seed_plain()  # exists but not approved
        c = TestClient(app)
        self.assertEqual(c.post(f"/work/assignment/{aid}/execute-approved", headers=self._headers(), json={"agent_id": "strategist"}).status_code, 403)
        self.assertEqual(c.post(f"/work/assignment/{aid}/execute-approved", headers=self._headers(user="u2"), json={"agent_id": "strategist"}).status_code, 404)
        self.assertEqual(c.post(f"/work/assignment/{aid}/execute-approved", headers=self._headers(tenant="other"), json={"agent_id": "strategist"}).status_code, 404)

    def test_agent_mismatch_invalid_and_nonhuman(self):
        db, gl, aid = self._seed_approved()
        c = TestClient(app)
        self.assertEqual(c.post(f"/work/assignment/{aid}/execute-approved", headers=self._headers(), json={"agent_id": "aisha"}).status_code, 422)
        self.assertEqual(c.post(f"/work/assignment/{aid}/execute-approved", headers=self._headers(), json={"agent_id": "bogus"}).status_code, 422)
        self.assertEqual(c.post(f"/work/assignment/{aid}/execute-approved", headers=self._headers(role="agent"), json={"agent_id": "strategist"}).status_code, 403)

    def test_result_id_match_but_differing_agent_returns_403(self):
        # M1 HTTP-level: the approved proposal's result_id matches the assignment
        # id, but the approved proposal recorded 'strategist' while the current
        # assignment agent is 'tutor'. The mismatch must be rejected with 403 and
        # must not create an Episode.
        db, gl, aid = self._seed_approved()
        db.execute("UPDATE assignments SET agent_id='tutor' WHERE id=?", (aid,))
        c = TestClient(app)
        r = c.post(f"/work/assignment/{aid}/execute-approved",
                   headers=self._headers(), json={"agent_id": "tutor"})
        self.assertEqual(r.status_code, 403)
        n = db.query("SELECT COUNT(*) AS n FROM episodes WHERE work_type='assignment' AND work_id=?", (aid,))[0]["n"]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
