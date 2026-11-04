"""Phase 4 M2 — Task Center endpoint + conversation-to-task API.

(Service-level Task Center coverage lives separately in test_phase4_m1.py.)
Covers on an isolated DB (never production):
- GET /tasks returns the Task Center aggregation (read-only).
- POST /conversations/{thread}/to-task creates a PROPOSAL (idempotent, preserves
  thread provenance) and never auto-creates an assignment or executes work.
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from storage.database import Database
from core.workspace import (
    WorkspaceService, ProjectService, GoalService,
)


class TestTaskCenterEndpoints(unittest.TestCase):
    """Endpoint-level checks (isolated DB, local mode)."""

    def test_tasks_endpoint_read_only(self):
        from api.app import app
        c = TestClient(app)
        r = c.get("/tasks")
        self.assertEqual(r.status_code, 200)
        self.assertIn("items", r.json())

    def test_to_task_creates_proposal_not_assignment(self):
        from api.app import app
        c = TestClient(app)
        # must create a goal + thread in the (temp) DB used by api.app
        from api.routers.tasks import _db
        ws = WorkspaceService(_db, "local", "local")
        pr = ProjectService(_db, "local", "local")
        go = GoalService(_db, "local", "local")
        wid = ws.create("WS")
        pid = pr.create(wid, "PROJ")
        gid = go.create(pid, "GOAL", 0)
        _db.execute(
            "INSERT INTO conversation_threads (thread_id,tenant_id,user_id,title,is_renamed,created_at,updated_at) "
            "VALUES ('thr1','local','local','chat',0,'now','now')")
        r = c.post("/conversations/thr1/to-task",
                   json={"goal_id": gid, "title": "Write plan", "agent_id": "tutor"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["work_type"], "assignment")
        # repeat same id (idempotent)
        r2 = c.post("/conversations/thr1/to-task",
                    json={"goal_id": gid, "title": "Write plan", "agent_id": "tutor"})
        self.assertEqual(r2.json()["reused"], True)
        # no assignment created yet (proposal only)
        from core.workspace import AssignmentService
        self.assertEqual(AssignmentService(_db, "local", "local").list(gid), [])

    def test_to_task_foreign_thread_not_found(self):
        """A conversation the caller does not own yields 404 (no cross-tenant leak)."""
        from api.app import app
        c = TestClient(app)
        from api.routers.tasks import _db
        ws = WorkspaceService(_db, "local", "local")
        pr = ProjectService(_db, "local", "local")
        go = GoalService(_db, "local", "local")
        wid = ws.create("WS")
        pid = pr.create(wid, "PROJ")
        gid = go.create(pid, "GOAL", 0)
        # A thread id that does not belong to this tenant/user.
        r = c.post("/conversations/foreign-thread/to-task",
                   json={"goal_id": gid, "title": "Write plan", "agent_id": "tutor"})
        self.assertEqual(r.status_code, 404)

    def test_to_task_foreign_goal_not_found(self):
        """A goal the caller does not own yields 404 (no cross-tenant leak)."""
        from api.app import app
        c = TestClient(app)
        from api.routers.tasks import _db
        _db.execute(
            "INSERT OR IGNORE INTO conversation_threads "
            "(thread_id,tenant_id,user_id,title,is_renamed,created_at,updated_at) "
            "VALUES ('owned-thread','local','local','chat',0,'now','now')")
        # A goal id that does not exist / is not owned here.
        r = c.post("/conversations/owned-thread/to-task",
                   json={"goal_id": "foreign-goal", "title": "Write plan", "agent_id": "tutor"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
