"""M10 — Agent-to-Workspace Phase A: proposal storage/link tables, service,
dependency validation, idempotency, lifecycle, isolation, and API read endpoints.

Verifies (fresh + existing migration, idempotency), proposal dependency
validation, missing-parent rejection, tenant/user isolation, duplicate/
idempotency, status handling, and that proposals never create actual work
records (projects/goals/assignments/deliverables/tasks/episodes).
"""
from __future__ import annotations

import os
import tempfile
import unittest
import sqlite3

from fastapi.testclient import TestClient

from storage.database import Database
from core.auth import issue_token
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService
from core.work_proposals import WorkProposalService
from api.app import app


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


def _tables(db, names):
    ph = ",".join("?" for _ in names)
    rows = db.query(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({ph})", list(names))
    return {r["name"] for r in rows}


class TestMigration(unittest.TestCase):
    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = getattr(self, "path", "") + s
            if os.path.exists(p):
                os.remove(p)

    def test_fresh_db_creates_m10_tables(self):
        self.path = _fresh_db()
        db = Database(path=self.path, tenant_id="local")
        self.assertEqual(_tables(db, ["work_proposals"]) , {"work_proposals"})
        self.assertEqual(_tables(db, ["work_links"]), {"work_links"})

    def test_existing_db_receives_m10_tables_and_is_idempotent(self):
        # Simulate a pre-existing base DB without M10 tables, then re-open.
        self.path = _fresh_db()
        db = Database(path=self.path, tenant_id="local")
        with sqlite3.connect(self.path) as c:
            c.execute("DROP TABLE work_proposals")
            c.execute("DROP TABLE work_links")
        # Re-open: the isolated init hook must add them back.
        db2 = Database(path=self.path, tenant_id="local")
        self.assertEqual(_tables(db2, ["work_proposals"]), {"work_proposals"})
        self.assertEqual(_tables(db2, ["work_links"]), {"work_links"})
        # Repeated open is idempotent (no error, no duplicate definitions).
        Database(path=self.path, tenant_id="local")
        Database(path=self.path, tenant_id="local")
        rows = db2.query("SELECT COUNT(*) AS n FROM work_proposals")
        self.assertEqual(rows[0]["n"], 0)


class TestWorkProposalService(unittest.TestCase):
    TENANT = "tenantA"

    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=self.TENANT)
        self.svc = WorkProposalService(self.db, self.TENANT, "u1")
        # Parent fixtures used by dependency-validation tests.
        self.ws = WorkspaceService(self.db, self.TENANT, "u1").create("W")
        self.pr = ProjectService(self.db, self.TENANT, "u1").create(self.ws, "P")
        self.gl = GoalService(self.db, self.TENANT, "u1").create(self.pr, "Goal", 1)

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)

    def _count(self, table):
        return self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def _record_counts(self):
        return {t: self._count(t) for t in
                ("projects", "goals", "assignments", "deliverables", "tasks", "episodes")}

    def test_goal_proposal_validates_and_creates_only_a_proposal(self):
        before = self._record_counts()
        r = self.svc.propose("goal", "strategist", action="create",
                             payload={"title": "Grow", "priority": 2, "project_id": self.pr},
                             idempotency_key="k1")
        self.assertEqual(r["status"], "proposed")
        self.assertEqual(r["reused"], False)
        # Only a proposal row was added; no actual work record was created.
        after = self._record_counts()
        self.assertEqual(before, after, "propose must not create work records")
        rows = self.db.query("SELECT * FROM work_proposals WHERE id=?", (r["proposal_id"],))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "proposed")
        self.assertEqual(rows[0]["project_id"], self.pr)

    def test_list_and_detail(self):
        r = self.svc.propose("goal", "strategist", payload={"project_id": self.pr},
                             reason="three objectives",
                             thread_id="conv-1", idempotency_key="k2")
        item = self.svc.get(r["proposal_id"])
        self.assertIsNotNone(item)
        self.assertEqual(item["source_thread_id"], "conv-1")
        self.assertEqual(item["proposed_change"], "create goal")
        self.assertEqual(item["parent"]["project_id"], self.pr)
        self.assertIn("expected_result", item)
        ids = {x["id"] for x in self.svc.list()}
        self.assertIn(r["proposal_id"], ids)

    def test_missing_parent_rejected(self):
        with self.assertRaises(ValueError) as e:
            self.svc.propose("goal", "strategist", payload={"title": "no parent"})
        self.assertIn("project_id", str(e.exception))

    def test_foreign_parent_rejected(self):
        # A goal under another tenant's project must be rejected.
        with self.assertRaises(ValueError) as e:
            self.svc.propose("goal", "strategist",
                             payload={"project_id": "not-owned-project"})
        self.assertIn("ownership", str(e.exception))

    def test_assignment_requires_existing_goal_and_subject(self):
        with self.assertRaises(ValueError):
            self.svc.propose("assignment", "taylor", payload={"agent_id": "brandon"})
        r = self.svc.propose("assignment", "taylor",
                             payload={"goal_id": self.gl, "agent_id": "brandon",
                                      "priority": 1},
                             idempotency_key="k3")
        row = self.db.query("SELECT * FROM work_proposals WHERE id=?", (r["proposal_id"],))[0]
        self.assertEqual(row["goal_id"], self.gl)
        self.assertEqual(row["subject_id"], "brandon")

    def test_unsupported_combination_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.propose("goal", "strategist", action="update", payload={"project_id": self.pr})

    def test_tenant_user_isolation(self):
        r = self.svc.propose("goal", "strategist", payload={"project_id": self.pr},
                             idempotency_key="secret")
        # Different tenant cannot see it.
        svcB = WorkProposalService(self.db, "tenantB", "u1")
        self.assertEqual(svcB.list(), [])
        self.assertIsNone(svcB.get(r["proposal_id"]))
        # Same tenant, different user cannot see it.
        svcU2 = WorkProposalService(self.db, self.TENANT, "u2")
        self.assertEqual(svcU2.list(), [])
        self.assertIsNone(svcU2.get(r["proposal_id"]))

    def test_idempotency_duplicate_returns_same_proposal(self):
        kwargs = dict(work_type="goal", agent_id="strategist",
                      payload={"project_id": self.pr})
        a = self.svc.propose(**kwargs, idempotency_key="dup")
        b = self.svc.propose(**kwargs, idempotency_key="dup")
        self.assertEqual(a["proposal_id"], b["proposal_id"])
        self.assertEqual(b["reused"], True)
        rows = self.db.query("SELECT COUNT(*) AS n FROM work_proposals")
        self.assertEqual(rows[0]["n"], 1)
        # Without a key, each propose is distinct.
        c = self.svc.propose(**kwargs)
        self.assertNotEqual(a["proposal_id"], c["proposal_id"])

    def test_status_lifecycle(self):
        r = self.svc.propose("goal", "strategist", payload={"project_id": self.pr},
                             idempotency_key="s1")
        # reject -> rejected, terminal
        self.svc.reject(r["proposal_id"], "u1", "no")
        self.assertEqual(self.svc.get(r["proposal_id"])["status"], "rejected")
        with self.assertRaises(ValueError):
            self.svc.reject(r["proposal_id"], "u1", "again")
        # mark_failed preserves the proposal row
        f = self.svc.propose("goal", "strategist", payload={"project_id": self.pr},
                             idempotency_key="s2")
        self.svc.mark_failed(f["proposal_id"], "boom")
        self.assertEqual(self.svc.get(f["proposal_id"])["status"], "failed")

    def test_no_tasks_or_episodes_created(self):
        self.svc.propose("goal", "strategist", payload={"project_id": self.pr})
        self.svc.propose("assignment", "taylor",
                         payload={"goal_id": self.gl, "agent_id": "brandon"})
        self.assertEqual(self._count("tasks"), 0)
        self.assertEqual(self._count("episodes"), 0)


class TestWorkProposalEndpoints(unittest.TestCase):
    TENANT = "m10endpoint"

    def _headers(self, user="u1", tenant=None):
        return {"x-token": issue_token(user, tenant or self.TENANT, "admin")}

    def test_list_and_detail_endpoints(self):
        c = TestClient(app)
        # Seed a proposal on the suite DB (used by the routers), scoped to the
        # same tenant/user the token will claim.
        from config.settings import DB_PATH
        db = Database(path=DB_PATH, tenant_id=self.TENANT)
        wsvc = WorkspaceService(db, self.TENANT, "u1")
        ws = wsvc.create("WE")
        pr = ProjectService(db, self.TENANT, "u1").create(ws, "PE")
        svc = WorkProposalService(db, self.TENANT, "u1")
        pid = svc.propose("goal", "strategist", payload={"project_id": pr},
                          idempotency_key="ep1")["proposal_id"]

        r = c.get("/work/proposals", headers=self._headers())
        self.assertEqual(r.status_code, 200)
        ids = {x["id"] for x in r.json()["items"]}
        self.assertIn(pid, ids)

        d = c.get(f"/work/proposals/{pid}", headers=self._headers())
        self.assertEqual(d.status_code, 200)
        self.assertEqual(d.json()["work_type"], "goal")

        # Cross-tenant cannot read the proposal.
        r2 = c.get(f"/work/proposals/{pid}", headers=self._headers(tenant="other"))
        self.assertEqual(r2.status_code, 404)

        # Same tenant, different user cannot read it either.
        r3 = c.get(f"/work/proposals/{pid}", headers=self._headers(user="u2"))
        self.assertEqual(r3.status_code, 404)


if __name__ == "__main__":
    unittest.main()
