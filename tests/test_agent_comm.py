"""Phase 3 §5-6 — durable agent-to-agent coordination ledger tests.

Covers the service layer + real HTTP endpoints:
- send records an agent-to-agent request with provenance (thread_id), open status;
- respond validates the responder identity and closes the parent;
- loop/depth guard: a chain exceeding MAX_DEPTH is blocked (not executed);
- unknown agents / empty content -> 422; foreign responder -> 422;
- tenant/user isolation: owners only see their own ledger; foreign -> empty;
- non-human role -> 403 on writes;
- ledger operations never approve/authorize/execute anything.
"""
from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from config.settings import DB_PATH
from core.agent_comm import AgentCommService, MAX_DEPTH
from core.auth import issue_token
from storage.database import Database


class AgentCommServiceTest(unittest.TestCase):
    def setUp(self):
        self.tenant = "fcm_" + uuid.uuid4().hex[:10]
        self.user = "fu_" + uuid.uuid4().hex[:8]
        self.db = Database(path=DB_PATH, tenant_id=self.tenant)
        self.svc = AgentCommService(self.db, self.tenant, self.user)

    def test_send_records_request_with_provenance(self):
        r = self.svc.send("workspace_architect", "strategist", "research the market",
                          thread_id="thr-1")
        self.assertEqual(r["status"], "open")
        rows = self.svc.list("thr-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["from_agent"], "workspace_architect")
        self.assertEqual(rows[0]["to_agent"], "strategist")
        self.assertEqual(rows[0]["thread_id"], "thr-1")

    def test_respond_validates_identity_and_closes_parent(self):
        req = self.svc.send("workspace_architect", "strategist", "task", thread_id="thr-2")
        # wrong responder
        with self.assertRaises(ValueError):
            self.svc.respond(req["id"], "tutor", "nope")
        res = self.svc.respond(req["id"], "strategist", "done")
        self.assertEqual(res["parent_id"], req["id"])
        entries = self.svc.list("thr-2")
        self.assertEqual(entries[0]["status"], "responded")

    def test_loop_guard_blocks_beyond_max_depth(self):
        node = None
        last_status = "open"
        for _ in range(MAX_DEPTH + 2):
            res = self.svc.send("strategist", "tutor", "msg", thread_id="thr-3",
                                parent_id=node)
            node = res["id"]
            last_status = res["status"]
        self.assertEqual(last_status, "blocked")
        self.assertIn("depth limit", res.get("message", ""))
        blocked = self.svc.blocked()
        self.assertTrue(any(b["status"] == "blocked" for b in blocked))

    def test_respond_chain_blocks_at_depth(self):
        req = self.svc.send("workspace_architect", "strategist", "start", thread_id="thr-r")
        node = req["id"]
        # current node's responder is its to_agent; alternate each hop
        status = "open"
        for _ in range(MAX_DEPTH + 3):
            row = next(x for x in self.svc.list("thr-r") if x["id"] == node)
            if row["status"] != "open":
                status = row["status"]
                break
            next_row = self.svc.respond(node, row["to_agent"], "reply")
            node = next_row["id"]
            status = next_row["status"]
            if status == "blocked":
                break
        self.assertEqual(status, "blocked")

    def test_unknown_agents_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.send("not_an_agent", "strategist", "x")
        with self.assertRaises(ValueError):
            self.svc.send("strategist", "nope", "x")

    def test_isolation_between_users(self):
        self.svc.send("strategist", "tutor", "hi", thread_id="thr-i")
        other = AgentCommService(self.db, self.tenant, "fu_other")
        self.assertEqual(other.list(), [])


class AgentCommAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _ctx(self):
        tenant = "fca_" + uuid.uuid4().hex[:10]
        user = "fu_" + uuid.uuid4().hex[:8]
        return tenant, user

    def _h(self, user, tenant, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def test_send_and_list_over_http(self):
        t, u = self._ctx()
        h = self._h(u, t)
        r = self.client.post("/team/comm",
                             json={"from_agent": "workspace_architect",
                                   "to_agent": "strategist", "content": "task",
                                   "thread_id": "thr-a"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        cid = r.json()["id"]
        lst = self.client.get("/team/comm?thread_id=thr-a", headers=h).json()["items"]
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["id"], cid)
        # respond
        rr = self.client.post(f"/team/comm/{cid}/respond",
                              json={"from_agent": "strategist", "content": "done"}, headers=h)
        self.assertEqual(rr.status_code, 200, rr.text)

    def test_loop_guard_blocked_surface(self):
        t, u = self._ctx()
        h = self._h(u, t)
        node = self.client.post("/team/comm",
                                json={"from_agent": "strategist", "to_agent": "tutor",
                                      "content": "start", "thread_id": "thr-b"}, headers=h).json()["id"]
        status = "open"
        # respond to each open node (responder = current node's to_agent)
        for _ in range(MAX_DEPTH + 4):
            items = self.client.get(f"/team/comm?thread_id=thr-b", headers=h).json()["items"]
            cur = next((x for x in items if x["id"] == node), None)
            if cur is None or cur["status"] != "open":
                status = cur["status"] if cur else "blocked"
                break
            res = self.client.post(f"/team/comm/{node}/respond",
                                   json={"from_agent": cur["to_agent"], "content": "r"},
                                   headers=h).json()
            node = res["id"]
            status = res["status"]
            if status == "blocked":
                break
        blocked = self.client.get("/team/comm/blocked", headers=h).json()["items"]
        self.assertEqual(status, "blocked")
        self.assertGreaterEqual(len(blocked), 1)
        self.assertTrue(any(b["status"] == "blocked" for b in blocked))

    def test_foreign_user_isolated(self):
        t, u = self._ctx()
        self.client.post("/team/comm",
                         json={"from_agent": "strategist", "to_agent": "tutor",
                               "content": "task"}, headers=self._h(u, t))
        other = "fu2_" + uuid.uuid4().hex[:8]
        r = self.client.get("/team/comm", headers=self._h(other, t))
        self.assertEqual(r.json()["items"], [])

    def test_non_human_403(self):
        t, u = self._ctx()
        r = self.client.post("/team/comm",
                             json={"from_agent": "strategist", "to_agent": "tutor",
                                   "content": "task"}, headers=self._h(u, t, role="agent"))
        self.assertEqual(r.status_code, 403, r.text)

    def test_ledger_is_not_consequential(self):
        t, u = self._ctx()
        self.client.post("/team/comm",
                         json={"from_agent": "strategist", "to_agent": "workspace_architect",
                               "content": "ask", "thread_id": "thr-c"}, headers=self._h(u, t))
        db = Database(path=DB_PATH, tenant_id=t)
        # no team goal / plan / execution created by the ledger
        for table in ("team_goals", "coordination_plans", "coordination_executions"):
            n = db.query(f"SELECT COUNT(*) AS n FROM {table} WHERE tenant_id=? AND user_id=?",
                         (t, u))[0]["n"]
            self.assertEqual(n, 0, table)


if __name__ == "__main__":
    unittest.main()
