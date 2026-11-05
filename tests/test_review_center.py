"""Phase 7 §13 — Review & Action Center tests.

Read-only aggregation of every owner-scoped pending decision over real HTTP
(TestClient) against the isolated shared test DB. Verifies:
- all five item types are aggregated with correct counts;
- foreign user/tenant isolation (they see only their own / empty lists);
- the endpoint is strictly READ-ONLY (a GET changes no proposals, plans,
  executions, or deliverables).
"""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from config.settings import DB_PATH
from core.auth import issue_token
from core.coordination_execution import CoordinationExecutionService
from core.coordination_plan import CoordinationPlanService
from core.team_goal import TeamGoalService
from core.workspace import WorkspaceService, ProjectService, GoalService
from storage.database import Database


def _now():
    return datetime.now(timezone.utc).isoformat()


def _scaffold(db, tenant, user):
    ws = WorkspaceService(db, tenant, user).create("W")
    pid = ProjectService(db, tenant, user).create(ws, "P")
    return GoalService(db, tenant, user).create(pid, "G", 0)


def _propose(db, tenant, user, title="Goal"):
    svc = TeamGoalService(db, tenant, user)
    gid = _scaffold(db, tenant, user)
    return svc.propose(
        title, "workspace_architect", goal_id=gid,
        steps=[{"seq": 1, "agent_id": "strategist",
                "responsibility": "Strategy for the launch"}])["team_goal_id"]


def _approved(db, tenant, user, title="Approved"):
    tg = _propose(db, tenant, user, title=title)
    TeamGoalService(db, tenant, user).approve(tg, user)
    return tg


def _plan_and_exec(db, tenant, user):
    """Approve + authorize + initiate; returns (team_goal_id, plan_id, exec_id)."""
    tg = _approved(db, tenant, user, title="Runnable")
    plan = CoordinationPlanService(db, tenant, user).authorize(tg, user)
    plan_id = plan["plan_id"]
    run = CoordinationExecutionService(db, tenant, user).initiate(plan_id, user)
    return tg, plan_id, run["execution_id"]


class ReviewCenterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _ctx(self):
        tenant = "frv_" + uuid.uuid4().hex[:10]
        user = "fu_" + uuid.uuid4().hex[:8]
        db = Database(path=DB_PATH, tenant_id=tenant)
        return tenant, user, db

    def _h(self, user, tenant):
        return {"x-token": issue_token(user, tenant, "user")}

    def test_review_aggregates_all_five_types(self):
        t, u, db = self._ctx()
        h = self._h(u, t)
        proposed = _propose(db, t, u, title="Needs Approval")           # goal_approval
        no_plan = _approved(db, t, u, title="Authorize Me")             # plan_authorization
        _, plan_id, exec_id = _plan_and_exec(db, t, u)                  # authorized goal
        now = _now()
        db.execute(
            "INSERT INTO coordination_step_outputs (id,tenant_id,user_id,execution_id,"
            "plan_id,seq,agent_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"so-a-{uuid.uuid4().hex[:6]}", t, u, exec_id, plan_id, 1, "strategist",
             "awaiting_review", now, now))
        db.execute(
            "INSERT INTO coordination_step_outputs (id,tenant_id,user_id,execution_id,"
            "plan_id,seq,agent_id,status,error,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"so-f-{uuid.uuid4().hex[:6]}", t, u, exec_id, plan_id, 2, "strategist",
             "failed", "model unavailable", now, now))
        db.execute(
            "INSERT INTO coordination_deliverables (id,tenant_id,user_id,execution_id,"
            "plan_id,title,content_json,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"did-{uuid.uuid4().hex[:6]}", t, u, exec_id, plan_id, "D", "{}",
             "pending", now, now))

        r = self.client.get("/team/review", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        types = {x["type"] for x in body["items"]}
        for expected in ("goal_approval", "plan_authorization", "step_review",
                         "deliverable_review", "blocked_step"):
            self.assertIn(expected, types)
        counts = body["counts"]
        self.assertGreaterEqual(counts["goal_approval"], 1)
        self.assertGreaterEqual(counts["plan_authorization"], 1)
        self.assertEqual(counts["step_review"], 1)
        self.assertEqual(counts["deliverable_review"], 1)
        self.assertEqual(counts["blocked_step"], 1)
        # items carry the ids needed to act/deep-link
        goal_item = next(x for x in body["items"] if x["type"] == "goal_approval")
        self.assertEqual(goal_item["goal_id"], proposed)
        self.assertIn("title", goal_item)
        step_item = next(x for x in body["items"] if x["type"] == "step_review")
        self.assertEqual(step_item["execution_id"], exec_id)
        self.assertIn("goal_title", step_item)

    def test_empty_review(self):
        t, u, db = self._ctx()  # noqa: F841  (db unused, only client hit)
        r = self.client.get("/team/review", headers=self._h(u, t))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["items"], [])
        self.assertEqual(sum(body["counts"].values()), 0)

    def test_foreign_user_sees_only_own_items(self):
        t, u, db = self._ctx()
        _propose(db, t, u, title="Owner's Goal")
        other = "fu2_" + uuid.uuid4().hex[:8]
        r = self.client.get("/team/review", headers=self._h(other, t))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["items"], [])
        self.assertEqual(sum(body["counts"].values()), 0)

    def test_foreign_tenant_sees_only_own_items(self):
        t, u, db = self._ctx()
        _propose(db, t, u, title="Tenant A's Goal")
        alien = "ft_" + uuid.uuid4().hex[:10]
        r = self.client.get("/team/review", headers=self._h("fu_x", alien))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["items"], [])

    def test_review_is_strictly_read_only(self):
        t, u, db = self._ctx()
        h = self._h(u, t)
        proposed = _propose(db, t, u, title="Stay Proposed")
        _, plan_id, exec_id = _plan_and_exec(db, t, u)
        now = _now()
        did = f"did-{uuid.uuid4().hex[:6]}"
        db.execute(
            "INSERT INTO coordination_deliverables (id,tenant_id,user_id,execution_id,"
            "plan_id,title,content_json,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (did, t, u, exec_id, plan_id, "D", "{}", "pending", now, now))

        r = self.client.get("/team/review", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["counts"]["goal_approval"], 1)

        # GET must not approve / authorize / execute anything.
        self.assertEqual(db.query(
            "SELECT status FROM team_goals WHERE id=? AND tenant_id=? AND user_id=? ",
            (proposed, t, u))[0]["status"], "proposed")
        self.assertEqual(db.query(
            "SELECT COUNT(*) AS n FROM coordination_plans WHERE team_goal_id=? "
            "AND tenant_id=? AND user_id=?",
            (proposed, t, u))[0]["n"], 0)
        self.assertEqual(db.query(
            "SELECT COUNT(*) AS n FROM coordination_executions WHERE team_goal_id=? "
            "AND tenant_id=? AND user_id=?",
            (proposed, t, u))[0]["n"], 0)
        self.assertEqual(db.query(
            "SELECT status FROM coordination_deliverables WHERE id=? "
            "AND tenant_id=? AND user_id=?", (did, t, u))[0]["status"], "pending")

    # ---------------------------------------------------------- dismissals
    def test_dismiss_hides_item_but_preserves_evidence(self):
        t, u, db = self._ctx()
        h = self._h(u, t)
        tg = _propose(db, t, u, title="Dismiss Me")

        body = self.client.get("/team/review", headers=h).json()
        item = next(x for x in body["items"]
                    if x["type"] == "goal_approval" and x.get("goal_id") == tg)
        self.assertTrue(item["key"].startswith("goal:"))

        # Dismiss is idempotent.
        for _ in range(2):
            r = self.client.post("/team/review/dismiss",
                                 json={"type": "goal_approval", "key": item["key"]},
                                 headers=h)
            self.assertEqual(r.status_code, 200, r.text)

        body2 = self.client.get("/team/review", headers=h).json()
        self.assertFalse(any(x["type"] == "goal_approval" and x.get("goal_id") == tg
                            for x in body2["items"]))
        # Underlying evidence is untouched.
        rows = db.query(
            "SELECT status FROM team_goals WHERE id=? AND tenant_id=? AND user_id=?",
            (tg, t, u))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "proposed")

    def test_undismiss_restores_item(self):
        t, u, db = self._ctx()
        h = self._h(u, t)
        tg = _propose(db, t, u, title="Restore Me")
        body = self.client.get("/team/review", headers=h).json()
        item = next(x for x in body["items"]
                    if x["type"] == "goal_approval" and x.get("goal_id") == tg)
        self.client.post("/team/review/dismiss",
                         json={"type": "goal_approval", "key": item["key"]}, headers=h)
        r = self.client.delete("/team/review/dismiss",
                               params={"type": "goal_approval", "key": item["key"]},
                               headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        body2 = self.client.get("/team/review", headers=h).json()
        self.assertTrue(any(x["type"] == "goal_approval" and x.get("goal_id") == tg
                            for x in body2["items"]))

    def test_dismiss_non_human_403(self):
        t, u, db = self._ctx()
        h = {"x-token": issue_token(u, t, "agent")}
        r = self.client.post("/team/review/dismiss",
                             json={"type": "goal_approval", "key": "goal:x"}, headers=h)
        self.assertEqual(r.status_code, 403)

    def test_dismiss_invalid_type_422(self):
        t, u, db = self._ctx()
        h = self._h(u, t)
        r = self.client.post("/team/review/dismiss",
                             json={"type": "nope", "key": "goal:x"}, headers=h)
        self.assertEqual(r.status_code, 422)

    def test_dismiss_isolation_across_users(self):
        t, u1, db = self._ctx()
        u2 = "fu_" + uuid.uuid4().hex[:8]
        tg = _propose(db, t, u1, title="Isolated")
        body = self.client.get("/team/review", headers=self._h(u1, t)).json()
        item = next(x for x in body["items"]
                    if x["type"] == "goal_approval" and x.get("goal_id") == tg)
        self.client.post("/team/review/dismiss",
                         json={"type": "goal_approval", "key": item["key"]}, headers=self._h(u1, t))
        # A second user proposing the same key independently still sees their own goal.
        tg2 = _propose(db, t, u2, title="Other")
        body2 = self.client.get("/team/review", headers=self._h(u2, t)).json()
        self.assertTrue(any(x["type"] == "goal_approval" and x.get("goal_id") == tg2
                            for x in body2["items"]))


if __name__ == "__main__":
    unittest.main()
