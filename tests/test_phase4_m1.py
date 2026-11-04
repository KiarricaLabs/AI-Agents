"""Phase 4 M1 — Task Center backend groundwork (service level).

Covers the TaskCenter aggregation service and its backing semantics on an
isolated DB (never production):
- Task Center aggregation: assignments-as-tasks enriched with project/goal/agent/
  deliverable/episode/provenance.
- Deliverable readiness: episode-done does NOT auto-mean ready_for_review;
  requires an approved deliverable on the task's project.
- Revision semantics differ from rejection (requested_changes flag + chain).
- Conversation provenance preserved on assignment proposals.
- Cross-tenant / cross-user protection.

(M2 endpoint coverage lives separately in test_phase4_m2.py.)
"""
from __future__ import annotations

import os
import tempfile
import unittest

from storage.database import Database
from core.task_center import TaskCenter
from core.workspace import (
    WorkspaceService, ProjectService, GoalService, AssignmentService, DeliverableService,
)
from core.work_proposals import WorkProposalService
from core.episodes import EpisodeService


def _fresh(path):
    try:
        os.remove(path)
    except OSError:
        pass
    return path


class _Scaffold:
    """Build a workspace/project/goal/assignment and return ids."""

    def __init__(self, db, tenant, user):
        self.db, self.tenant, self.user = db, tenant, user
        self.ws = WorkspaceService(db, tenant, user)
        self.pr = ProjectService(db, tenant, user)
        self.go = GoalService(db, tenant, user)
        self.asg = AssignmentService(db, tenant, user)
        self.dv = DeliverableService(db, tenant, user)

    def make(self, agent="tutor"):
        wid = self.ws.create("WS")
        pid = self.pr.create(wid, "PROJ")       # create(workspace_id, name)
        gid = self.go.create(pid, "GOAL", 0)    # create(project_id, title, priority)
        aid = self.asg.assign(gid, agent, 0)
        return {"wid": wid, "pid": pid, "gid": gid, "aid": aid}


class TestTaskCenter(unittest.TestCase):
    def setUp(self):
        self.path = _fresh(tempfile.mkstemp(suffix=".db")[1])
        self.db = Database(path=self.path, tenant_id="t1")
        self.tc = TaskCenter(self.db, "t1", "u1")

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_awaiting_execution_for_unstarted_approved_assignment(self):
        s = _Scaffold(self.db, "t1", "u1")
        ids = s.make()
        # simulate an approved proposal whose result is this assignment
        wps = WorkProposalService(self.db, "t1", "u1")
        wps.propose("assignment", "tutor",
                    payload={"goal_id": ids["gid"], "agent_id": "tutor"},
                    idempotency_key="k1")
        rows = self.db.query("SELECT id FROM work_proposals WHERE idempotency_key='k1'")
        pid = rows[0]["id"]
        self.db.execute(
            "UPDATE work_proposals SET status='approved', result_id=?, decided_at=?, decided_by=? "
            "WHERE id=? AND tenant_id=?",
            (ids["aid"], "now", "u1", pid, "t1"))
        items = self.tc.list()["items"]
        t = next((x for x in items if x["assignment_id"] == ids["aid"]), None)
        self.assertIsNotNone(t)
        self.assertIn(t["status"], ("awaiting_execution",))
        self.assertEqual(t["project_id"], ids["pid"])

    def test_ready_for_review_requires_approved_deliverable(self):
        s = _Scaffold(self.db, "t1", "u1")
        ids = s.make()
        # episode done, but NO deliverable -> NOT ready_for_review
        es = EpisodeService(self.db, "t1", "u1")
        ep = es.start_for_work("assignment", ids["aid"], "tutor")
        es.complete_with_evidence(ep["episode_id"], {"summary": "done"})
        items = self.tc.list()["items"]
        t = next(x for x in items if x["assignment_id"] == ids["aid"])
        # no approved deliverable -> not ready_for_review by readiness gate
        self.assertNotEqual(t["status"], "ready_for_review")

        # add deliverable with approved version -> becomes ready_for_review
        did = s.dv.create(ids["pid"], "Doc")
        vid, _ = s.dv.add_version(did, "content")
        s.dv.approve(vid, "u1")
        items = self.tc.list()["items"]
        t = next(x for x in items if x["assignment_id"] == ids["aid"])
        # episode done + approved deliverable on the project
        # (status may be ready_for_review or completed depending on applied state)
        self.assertIn(t["status"], ("ready_for_review", "completed"))
        self.assertTrue(t["deliverable"])
        self.assertEqual(t["deliverable"]["status"], "approved")

    def test_revision_requested_differs_from_rejected(self):
        s = _Scaffold(self.db, "t1", "u1")
        ids = s.make()
        did = s.dv.create(ids["pid"], "Doc")
        vid, _ = s.dv.add_version(did, "v1")
        # request changes (revision) -> flag set, version NOT rejected
        s.dv.request_changes(vid, "u1", reason="needs tone")
        v = s.dv.list_versions(did)[0]
        self.assertEqual(v["requested_changes"], 1)
        self.assertNotEqual(v["status"], "rejected")
        # reject a separate path
        did2 = s.dv.create(ids["pid"], "Doc2")
        vid2, _ = s.dv.add_version(did2, "v1")
        s.dv.reject(vid2, "u1", reason="no")
        v2 = s.dv.list_versions(did2)[0]
        self.assertEqual(v2["status"], "rejected")

    def test_revision_chain_links_successor(self):
        s = _Scaffold(self.db, "t1", "u1")
        ids = s.make()
        did = s.dv.create(ids["pid"], "Doc")
        vid1, _ = s.dv.add_version(did, "v1")
        vid2, _ = s.dv.add_version(did, "v2")
        v2 = s.dv.list_versions(did)[1]
        self.assertEqual(v2["revision_of"], vid1)

    def test_conversation_provenance_on_proposal(self):
        s = _Scaffold(self.db, "t1", "u1")
        ids = s.make()
        # seed a conversation thread owned by u1
        self.db.execute(
            "INSERT INTO conversation_threads (thread_id,tenant_id,user_id,title,is_renamed,created_at,updated_at) "
            "VALUES ('th1','t1','u1','chat',0,'now','now')")
        wps = WorkProposalService(self.db, "t1", "u1")
        r = wps.propose("assignment", "tutor",
                        payload={"goal_id": ids["gid"], "title": "Do X", "agent_id": "tutor"},
                        thread_id="th1", idempotency_key="conv-k1")
        rows = self.db.query("SELECT thread_id FROM work_proposals WHERE id=?", (r["proposal_id"],))
        self.assertEqual(rows[0]["thread_id"], "th1")

    def test_cross_tenant_isolation(self):
        # a different tenant's assignment must not appear for u1
        db2_path = _fresh(tempfile.mkstemp(suffix=".db")[1])
        db2 = Database(path=db2_path, tenant_id="t2")
        s2 = _Scaffold(db2, "t2", "u2")
        s2.make()
        items = self.tc.list()["items"]
        self.assertEqual(items, [])
        os.remove(db2_path)


if __name__ == "__main__":
    unittest.main()
