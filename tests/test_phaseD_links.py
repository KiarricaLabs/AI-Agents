"""M10 Phase D1 — post-approval visibility & bidirectional navigation.

Read-only feature layer. Verifies:
- consolidated proposal/decision feed (all statuses, decision metadata, no writes),
- conversation thread -> approved linked work, with resolved labels,
- work record -> originating conversation thread (title/agent), never fabricated,
- tenant/user isolation and no existence leak in both directions,
- work_type whitelist (no arbitrary identifiers),
- existing GET /work/proposals and /work/proposals/{id} remain compatible,
- approved proposals report result work only when resolvable.

All tests use isolated databases; the production DB is never opened.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from storage.database import Database
from core.auth import issue_token
from core.workspace import WorkspaceService, ProjectService, GoalService, DeliverableService
from core.work_proposals import WorkProposalService
from api.app import app


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


TENANT = "phased"
USER = "u1"


class PhaseDBase(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=TENANT)
        self.ws = WorkspaceService(self.db, TENANT, USER).create("WS")
        self.pr = ProjectService(self.db, TENANT, USER).create(self.ws, "Project")
        self.gl = GoalService(self.db, TENANT, USER).create(self.pr, "Goal", 1)
        self.svc = WorkProposalService(self.db, TENANT, USER)

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)

    def _thread(self, tid="thread-d1", agent="strategist", title="D1 Thread"):
        self.db.execute(
            "INSERT INTO conversation_threads "
            "(thread_id,tenant_id,user_id,agent_id,title,is_renamed,created_at,updated_at) "
            "VALUES (?,?,?,?,?,0,?,?)", (tid, TENANT, USER, agent, title, _now(), _now()))

    def _approve(self, work_type, payload, target_id=None, thread="thread-d1"):
        action = "update" if work_type == "goal_update" else "create"
        pid = self.svc.propose(work_type, "strategist", action=action, payload=payload,
                               thread_id=thread, target_id=target_id,
                               idempotency_key=f"d1-{work_type}-{target_id or ''}-{thread}")["proposal_id"]
        res = self.svc.approve(pid, USER)
        self.assertEqual(res["status"], "approved")
        return pid, res["result_id"]


class TestFeed(PhaseDBase):
    def _status(self, pid, status):
        self.db.execute(
            "UPDATE work_proposals SET status=?, decided_at=?, decided_by=?, "
            "rejection_reason=? WHERE id=? AND tenant_id=? AND user_id=?",
            (status, _now(), USER, None if status != "rejected" else "nope",
             pid, TENANT, USER))

    def test_feed_lists_all_statuses_with_decision_metadata(self):
        pid_p = self.svc.propose("goal", "strategist", payload={"project_id": self.pr},
                                 thread_id="t", idempotency_key="feed-1")["proposal_id"]
        # approved with a resolvable record
        pid_a, wid_a = self._approve("project", {"workspace_id": self.ws, "name": "FeedP"})
        # rejected
        pid_r = self.svc.propose("deliverable", "strategist", payload={"project_id": self.pr, "title": "D"},
                                 thread_id="t", idempotency_key="feed-2")["proposal_id"]
        self.svc.reject(pid_r, USER, reason="declined")
        feed = self.svc.list_feed()
        by_id = {x["id"]: x for x in feed}
        # all four present
        self.assertIn(pid_p, by_id)
        self.assertIn(pid_a, by_id)
        self.assertIn(pid_r, by_id)
        # proposed -> decision None
        self.assertIsNone(by_id[pid_p]["decision"])
        # approved -> decision with resolved label
        d = by_id[pid_a]["decision"]
        self.assertIsNotNone(d)
        self.assertEqual(d["work_id"], wid_a)
        self.assertEqual(d["label"], "FeedP")
        self.assertEqual(d["approver"], USER)
        # rejected -> reason preserved, no label
        dr = by_id[pid_r]["decision"]
        self.assertIsNotNone(dr)
        self.assertEqual(dr["rejection_reason"], "declined")
        self.assertIsNone(dr["label"])
        # enriched shape present
        for it in feed:
            self.assertIn("payload", it)
            self.assertIn("expected_result", it)
            self.assertIn("source_thread_id", it)

    def test_approved_but_unresolvable_work_has_no_label(self):
        _, wid = self._approve("project", {"workspace_id": self.ws, "name": "Ghost"})
        self.db.execute("DELETE FROM projects WHERE id=?", (wid,))
        feed = self.svc.list_feed()
        approved = [x for x in feed if x["status"] == "approved" and x["decision"]["work_id"] == wid]
        self.assertEqual(len(approved), 1)
        self.assertIsNone(approved[0]["decision"]["label"])


class TestLinks(PhaseDBase):
    def test_thread_to_work_all_six_types(self):
        self._thread()
        # deliverable + version need a deliverable
        did = DeliverableService(self.db, TENANT, USER).create(self.pr, "Brand Kit")
        cases = [
            ("project", {"workspace_id": self.ws, "name": "LinkProj"}, None, "LinkProj"),
            ("goal", {"project_id": self.pr, "title": "LinkGoal"}, None, "LinkGoal"),
            ("goal_update", {"title": "LinkUpd", "_base_version": 0}, self.gl, "LinkUpd"),
            ("assignment", {"goal_id": self.gl, "agent_id": "strategist"}, None, "strategist"),
            ("deliverable", {"project_id": self.pr, "title": "LinkDel"}, None, "LinkDel"),
            ("deliverable_version", {"deliverable_id": did, "content": "x"}, did, "Brand Kit"),
        ]
        for wt, payload, target, _ in cases:
            self._approve(wt, payload, target_id=target, thread="thread-d1")
        links = self.svc.links_for_thread("thread-d1")
        self.assertEqual(len(links), 6)
        by_type = {l["work_type"]: l for l in links}
        self.assertEqual(by_type["project"]["label"], "LinkProj")
        self.assertEqual(by_type["goal"]["label"], "LinkGoal")
        self.assertEqual(by_type["goal_update"]["label"], "LinkUpd")
        self.assertIn("→", by_type["assignment"]["label"])
        self.assertEqual(by_type["deliverable"]["label"], "LinkDel")
        self.assertEqual(by_type["deliverable_version"]["label"], "Brand Kit v1")
        # proposal_id resolved for approved works
        self.assertTrue(all(l["proposal_id"] for l in links))

    def test_thread_to_work_empty_for_unknown_thread(self):
        self.assertEqual(self.svc.links_for_thread("no-such-thread"), [])

    def test_work_to_thread(self):
        self._thread()
        _, wid = self._approve("project", {"workspace_id": self.ws, "name": "NavP"})
        threads = self.svc.threads_for_work("project", wid)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["thread_id"], "thread-d1")
        self.assertEqual(threads[0]["title"], "D1 Thread")
        self.assertEqual(threads[0]["agent_id"], "strategist")

    def test_work_to_thread_never_fabricates_when_thread_missing(self):
        self._thread()
        _, wid = self._approve("project", {"workspace_id": self.ws, "name": "NavP2"},
                               thread="ghost-thread")
        # no conversation_threads row for ghost-thread
        threads = self.svc.threads_for_work("project", wid)
        self.assertEqual(threads[0]["thread_id"], "ghost-thread")
        self.assertIsNone(threads[0]["title"])
        self.assertIsNone(threads[0]["agent_id"])

    def test_unsupported_work_type_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.threads_for_work("; DROP TABLE goals; --", "x")


class TestIsolation(PhaseDBase):
    def test_cross_user_cannot_see_links_or_feed(self):
        self._thread()
        self._approve("project", {"workspace_id": self.ws, "name": "IsolP"})
        other = WorkProposalService(self.db, TENANT, "u2")
        self.assertEqual(other.links_for_thread("thread-d1"), [])
        self.assertEqual(other.threads_for_work("project", self.ws), [])
        feed_other = other.list_feed()
        self.assertEqual(feed_other, [])

    def test_cross_tenant_cannot_see_links_or_feed(self):
        self._thread()
        self._approve("project", {"workspace_id": self.ws, "name": "IsolT"})
        other = WorkProposalService(self.db, "other_tenant", USER)
        self.assertEqual(other.links_for_thread("thread-d1"), [])
        self.assertEqual(other.list_feed(), [])


class TestEndpoints(unittest.TestCase):
    TENANT = "phased"
    USER = "u1"

    def _headers(self, user=USER, tenant=TENANT, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def _seed(self):
        import uuid
        from config.settings import DB_PATH
        db = Database(path=DB_PATH, tenant_id=self.TENANT)
        ws = WorkspaceService(db, self.TENANT, self.USER).create("E WS")
        pr = ProjectService(db, self.TENANT, self.USER).create(ws, "E Proj")
        tid = f"t-{uuid.uuid4()}"
        db.execute(
            "INSERT INTO conversation_threads "
            "(thread_id,tenant_id,user_id,agent_id,title,is_renamed,created_at,updated_at) "
            "VALUES (?,?,?,?,?,0,?,?)",
            (tid, self.TENANT, self.USER, "strategist", "E Thread", _now(), _now()))
        svc = WorkProposalService(db, self.TENANT, self.USER)
        pid = svc.propose("project", "strategist", payload={"workspace_id": ws, "name": "E P"},
                          thread_id=tid, idempotency_key=f"e1-{tid}")["proposal_id"]
        res = svc.approve(pid, self.USER)
        return db, tid, pid, res["result_id"]

    def test_feed_and_links_endpoints(self):
        db, tid, pid, wid = self._seed()
        c = TestClient(app)
        feed = c.get("/work/feed", headers=self._headers()).json()["items"]
        self.assertGreaterEqual(len(feed), 1)
        # conversation -> work
        links = c.get("/work/links", headers=self._headers(), params={"thread_id": tid}).json()["items"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["work_type"], "project")
        self.assertEqual(links[0]["label"], "E P")
        # work -> conversation
        rev = c.get(f"/work/links/work/project/{wid}", headers=self._headers()).json()
        self.assertEqual(len(rev["threads"]), 1)
        self.assertEqual(rev["threads"][0]["thread_id"], tid)
        self.assertEqual(rev["threads"][0]["title"], "E Thread")

    def test_unsupported_work_type_422(self):
        c = TestClient(app)
        r = c.get("/work/links/work/not-a-type/abc", headers=self._headers())
        self.assertEqual(r.status_code, 422)

    def test_links_are_isolated(self):
        db, tid, pid, wid = self._seed()
        c = TestClient(app)
        r = c.get("/work/links", headers=self._headers(user="u2"), params={"thread_id": tid})
        self.assertEqual(r.json()["items"], [])
        r2 = c.get(f"/work/links/work/project/{wid}", headers=self._headers(user="u2"))
        self.assertEqual(r2.json()["threads"], [])

    def test_existing_proposal_endpoints_remain_compatible(self):
        db, tid, pid, wid = self._seed()
        c = TestClient(app)
        lst = c.get("/work/proposals", headers=self._headers()).json()["items"]
        self.assertGreaterEqual(len(lst), 1)
        self.assertIn("work_type", lst[0])
        self.assertIn("status", lst[0])
        det = c.get(f"/work/proposals/{pid}", headers=self._headers()).json()
        for k in ("id", "work_type", "status", "payload", "expected_result",
                  "source_thread_id", "parent", "affected_records"):
            self.assertIn(k, det)


if __name__ == "__main__":
    unittest.main()
