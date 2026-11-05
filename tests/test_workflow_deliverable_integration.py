"""T2-C-7 Phase 3 — deliverable HTTP integration (G1/G2/security).

Drives the coordination deliverable endpoints over the real FastAPI app
(TestClient) against the isolated shared test DB, verifying both HTTP responses
AND persisted database state.

The workflow up to an authorized plan + initiated execution runs through the
real HTTP API (authorize, initiate). Because the post-execution artifacts
(accepted step outputs, aggregated deliverable, pending version) are normally
created only after dispatching an agent step, they are seeded here with test-only
SQL — respecting the T2-C-4/T2-C-5 schema (ownership columns, step provenance,
UNIQUE constraints). NO dispatcher/agent/Ollama/live model is ever invoked.

Covers:
- G1  deliverable versions listed + detail after aggregation (v1, pending, content).
- G2a accept -> approved version, completed execution (persisted) + idempotency.
- G2b reject -> rejected version + execution (persisted).
- G2c revision (valid rework steps) -> revision_requested version, running
      execution, step-output + downstream invalidation (persisted).
- Security: foreign user/tenant -> 404 on version reads and deliverable review;
      non-human role -> 403 on deliverable review.
"""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402  (registers routers + auth middleware)
from config.settings import DB_PATH
from core.auth import issue_token
from core.team_goal import TeamGoalService
from core.workspace import WorkspaceService, ProjectService, GoalService
from storage.database import Database

# Review decisions sent over HTTP to the deliverable endpoint.
DECISION_REVISION = "revision_requested"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _propose_approved(db, tenant, user):
    """Valid TeamGoal (workspace_architect -> strategist), proposed + approved."""
    ws = WorkspaceService(db, tenant, user).create("W")
    pid = ProjectService(db, tenant, user).create(ws, "P")
    gid = GoalService(db, tenant, user).create(pid, "G", 0)
    svc = TeamGoalService(db, tenant, user)
    tg = svc.propose(
        "Launch", "workspace_architect", goal_id=gid,
        steps=[{"seq": 1, "agent_id": "strategist",
                "responsibility": "Strategy for the launch"}])["team_goal_id"]
    svc.approve(tg, user)
    return tg


class DeliverableIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.tenant = "fwd_" + uuid.uuid4().hex[:10]
        self.user = "fu_" + uuid.uuid4().hex[:8]
        self.db = Database(path=DB_PATH, tenant_id=self.tenant)

    def _h(self, user=None, tenant=None, role="user"):
        return {"x-token": issue_token(user or self.user, tenant or self.tenant, role)}

    def _authorize_and_initiate(self):
        """Drive propose->approve->authorize->initiate over services + HTTP.
        Returns (plan_id, execution_id, steps, owner header)."""
        tg = _propose_approved(self.db, self.tenant, self.user)
        h = self._h()
        plan = self.client.post(
            f"/team/goals/{tg}/coordination-plan/authorize", headers=h).json()
        plan_id = plan["plan_id"]
        steps = plan["steps"]  # frozen snapshot step list (seq, agent_id, ...)
        run = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/initiate", headers=h).json()
        exec_id = run["execution_id"]
        return tg, plan_id, exec_id, steps, h

    def _seed_aggregated(self, plan_id, exec_id, steps):
        """Seed post-aggregation artifacts for every plan step (accepted outputs),
        the deliverable row, and version 1 (pending). Returns (deliverable_id,
        version_id, content)."""
        now = _now()
        tenant, user = self.tenant, self.user
        for s in steps:
            seq = int(s["seq"])
            self.db.execute(
                "INSERT INTO coordination_step_outputs "
                "(id,tenant_id,user_id,execution_id,plan_id,seq,agent_id,episode_id,"
                "output_json,evidence_json,status,error,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"so-{seq}-{uuid.uuid4().hex[:8]}", tenant, user, exec_id, plan_id,
                 seq, s["agent_id"], None,
                 json.dumps({"step": seq, "reply": f"output {seq}"}),
                 json.dumps({"summary": f"ev {seq}"}), "accepted", None, now, now))
        content = {"expected_deliverable": "Delivery",
                   "steps": [{"seq": int(s["seq"])} for s in steps]}
        did = "did-" + uuid.uuid4().hex[:10]
        self.db.execute(
            "INSERT INTO coordination_deliverables "
            "(id,tenant_id,user_id,execution_id,plan_id,title,content_json,status,"
            "review_note,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (did, tenant, user, exec_id, plan_id, "Delivery",
             json.dumps(content), "pending", None, now, now))
        vid = "vid-" + uuid.uuid4().hex[:10]
        self.db.execute(
            "INSERT INTO coordination_deliverable_versions "
            "(id,tenant_id,user_id,execution_id,deliverable_id,version,content_json,"
            "status,review_note,revision_of,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, tenant, user, exec_id, did, 1, json.dumps(content), "pending",
             None, None, now, now))
        return did, vid, content

    # ------------------------------------------------------------------ G1
    def test_deliverable_versions_listed_and_detail_after_aggregation(self):
        _, plan_id, exec_id, steps, h = self._authorize_and_initiate()
        did, vid, content = self._seed_aggregated(plan_id, exec_id, steps)

        r = self.client.get(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/versions",
            headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        versions = r.json()["versions"]
        self.assertEqual(len(versions), 1)
        v = versions[0]
        self.assertEqual(v["version"], 1)
        self.assertEqual(v["status"], "pending")
        self.assertEqual(v["version_id"], vid)
        self.assertEqual(v["deliverable_id"], did)
        self.assertEqual(v["content"], content)

        # detail endpoint returns persisted content + the approval shape (empty).
        r = self.client.get(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/versions/{vid}",
            headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        vd = r.json()
        self.assertEqual(vd["version"], 1)
        self.assertEqual(vd["status"], "pending")
        self.assertEqual(vd["content"], content)
        self.assertIn("approvals", vd)
        self.assertEqual(vd["approvals"], [])

    # ------------------------------------------------------------------ G2a
    def test_accept_transitions_to_completed_idempotent_conflict_rejected(self):
        _, plan_id, exec_id, steps, h = self._authorize_and_initiate()
        did, vid, content = self._seed_aggregated(plan_id, exec_id, steps)

        r = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/review",
            json={"decision": "accepted"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["run_status"], "completed")
        self.assertEqual(r.json()["version"], 1)

        # persisted state
        self.assertEqual(self._version_status(vid), "approved")
        self.assertEqual(self.db.query(
            "SELECT status FROM coordination_deliverables WHERE id=? "
            "AND tenant_id=? AND user_id=?", (did, self.tenant, self.user))[0]["status"],
            "accepted")
        self.assertEqual(self.db.query(
            "SELECT status FROM coordination_executions WHERE id=? "
            "AND tenant_id=? AND user_id=?", (exec_id, self.tenant, self.user))[0]["status"],
            "completed")
        self.assertEqual(self._approval_count(vid), 1)

        # identical decision is idempotent (existing contract): no new approval row
        r2 = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/review",
            json={"decision": "accepted"}, headers=h)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(self._approval_count(vid), 1)
        self.assertEqual(self._version_status(vid), "approved")

        # Conflicting decision is rejected with an intentional 409 Conflict, and
        # the transaction rolls back: the original decision, approval count,
        # deliverable status, and execution status are all unchanged.
        r3 = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/review",
            json={"decision": "rejected"}, headers=h)
        self.assertEqual(r3.status_code, 409, r3.text)
        self.assertEqual(self._version_status(vid), "approved")
        self.assertEqual(self._approval_count(vid), 1)
        self.assertEqual(self.db.query(
            "SELECT status FROM coordination_deliverables WHERE id=? "
            "AND tenant_id=? AND user_id=?", (did, self.tenant, self.user))[0]["status"],
            "accepted")
        self.assertEqual(self.db.query(
            "SELECT status FROM coordination_executions WHERE id=? "
            "AND tenant_id=? AND user_id=?", (exec_id, self.tenant, self.user))[0]["status"],
            "completed")

    # ------------------------------------------------------------------ G2b
    def test_reject_transitions_to_rejected(self):
        _, plan_id, exec_id, steps, h = self._authorize_and_initiate()
        did, vid, content = self._seed_aggregated(plan_id, exec_id, steps)

        r = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/review",
            json={"decision": "rejected"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["run_status"], "rejected")

        self.assertEqual(self._version_status(vid), "rejected")
        self.assertEqual(self.db.query(
            "SELECT status FROM coordination_deliverables WHERE id=? "
            "AND tenant_id=? AND user_id=?", (did, self.tenant, self.user))[0]["status"],
            "rejected")
        self.assertEqual(self.db.query(
            "SELECT status FROM coordination_executions WHERE id=? "
            "AND tenant_id=? AND user_id=?", (exec_id, self.tenant, self.user))[0]["status"],
            "rejected")
        self.assertEqual(self._approval_count(vid), 1)

    # ------------------------------------------------------------------ G2c
    def test_revision_returns_to_running_and_invalidates_steps(self):
        _, plan_id, exec_id, steps, h = self._authorize_and_initiate()
        did, vid, content = self._seed_aggregated(plan_id, exec_id, steps)
        seqs = [int(s["seq"]) for s in steps]

        r = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/review",
            json={"decision": DECISION_REVISION, "rework_steps": seqs}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["run_status"], "running")
        self.assertEqual(sorted(r.json()["steps"]), sorted(seqs))

        # persisted state: version revision_requested, deliverable revision_requested,
        # run back to running, and each reworked step output invalidated.
        self.assertEqual(self._version_status(vid), DECISION_REVISION)
        self.assertEqual(self.db.query(
            "SELECT status FROM coordination_deliverables WHERE id=? "
            "AND tenant_id=? AND user_id=?", (did, self.tenant, self.user))[0]["status"],
            DECISION_REVISION)
        self.assertEqual(self.db.query(
            "SELECT status FROM coordination_executions WHERE id=? "
            "AND tenant_id=? AND user_id=?", (exec_id, self.tenant, self.user))[0]["status"],
            "running")
        for seq in seqs:
            row = self.db.query(
                "SELECT status, output_json FROM coordination_step_outputs "
                "WHERE execution_id=? AND seq=? AND tenant_id=? AND user_id=?",
                (exec_id, seq, self.tenant, self.user))[0]
            self.assertEqual(row["status"], DECISION_REVISION)
            self.assertIsNone(row["output_json"])

        # version history stays intact (still one immutable-ish pending-turned-
        # revision_requested version with preserved content).
        r = self.client.get(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/versions",
            headers=h)
        versions = r.json()["versions"]
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["status"], DECISION_REVISION)
        self.assertEqual(versions[0]["content"], content)

    # ------------------------------------------------------------------ security
    def test_deliverable_resources_foreign_404(self):
        _, plan_id, exec_id, steps, _ = self._authorize_and_initiate()
        did, vid, content = self._seed_aggregated(plan_id, exec_id, steps)
        base = f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable"

        foreign_user = "fuX_" + uuid.uuid4().hex[:8]
        hu = self._h(user=foreign_user, tenant=self.tenant)          # same tenant, other user
        alien_tenant = "fwt_" + uuid.uuid4().hex[:10]
        ht = self._h(user="fu_alien", tenant=alien_tenant)           # other tenant

        for h_ in (hu, ht):
            for url in (
                f"{base}/versions",
                f"{base}/versions/{vid}",
            ):
                self.assertEqual(self.client.get(url, headers=h_).status_code, 404, url)
            r = self.client.post(
                f"{base}/review", json={"decision": "accepted"}, headers=h_)
            self.assertEqual(r.status_code, 404, r.text)

    def test_deliverable_review_requires_human(self):
        _, plan_id, exec_id, steps, _ = self._authorize_and_initiate()
        did, vid, content = self._seed_aggregated(plan_id, exec_id, steps)
        ha = self._h(role="agent")  # authenticated, but not a human role
        r = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/review",
            json={"decision": "accepted"}, headers=ha)
        self.assertEqual(r.status_code, 403, r.text)

    # ------------------------------------------------------------- read helpers
    def _version_status(self, vid):
        return self.db.query(
            "SELECT status FROM coordination_deliverable_versions WHERE id=? "
            "AND tenant_id=? AND user_id=?",
            (vid, self.tenant, self.user))[0]["status"]

    def _approval_count(self, vid):
        return self.db.query(
            "SELECT COUNT(*) AS n FROM coordination_deliverable_approvals "
            "WHERE version_id=? AND tenant_id=? AND user_id=?",
            (vid, self.tenant, self.user))[0]["n"]


if __name__ == "__main__":
    unittest.main()
