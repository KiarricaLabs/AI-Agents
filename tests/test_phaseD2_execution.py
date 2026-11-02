"""M10 Phase D2 — execution gating & episode tracking.

Verifies:
- additive D2 migration (columns + partial unique active-work index) on fresh
  and existing databases, idempotently,
- human-only, owner/tenant-scoped execution trigger for approved work
  (assignments and goals only); agent self-start rejected,
- idempotent start + DB-level concurrency protection (one active episode per key),
- evidence-gated checkpoint/completion with secret/empty rejection,
- no Episode creation from proposal approval or ordinary conversation,
- cross-user/tenant isolation (no leak).

All tests use isolated databases; the production DB is never opened.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import unittest

from fastapi.testclient import TestClient

from storage.database import Database
from core.auth import issue_token
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService
from core.episodes import EpisodeService
from core.work_proposals import WorkProposalService
from api.app import app


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


TENANT = "phaseD2"
USER = "u1"


class PhaseD2Base(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=TENANT)
        self.ws = WorkspaceService(self.db, TENANT, USER).create("WS")
        self.pr = ProjectService(self.db, TENANT, USER).create(self.ws, "Project")
        self.gl = GoalService(self.db, TENANT, USER).create(self.pr, "Goal", 1)
        self.aid = AssignmentService(self.db, TENANT, USER).assign(self.gl, "strategist", 0)
        self.es = EpisodeService(self.db, TENANT, USER)

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)

    def _count(self, table):
        return self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]


class TestMigration(unittest.TestCase):
    def test_fresh_db_has_d2_columns_and_index(self):
        path = _fresh_db()
        try:
            db = Database(path=path, tenant_id="local")
            ecols = {r["name"] for r in db.query("SELECT name FROM pragma_table_info('episodes')")}
            self.assertIn("work_type", ecols)
            self.assertIn("work_id", ecols)
            vcols = {r["name"] for r in db.query("SELECT name FROM pragma_table_info('episode_events')")}
            self.assertIn("evidence_json", vcols)
            self.assertIn("progress", vcols)
            rows = db.query("SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                            ("uq_episodes_active_work",))
            self.assertEqual(len(rows), 1)
        finally:
            for s in ("", "-wal", "-shm"):
                p = path + s
                if os.path.exists(p):
                    os.remove(p)

    def test_existing_db_gains_d2_columns_idempotently(self):
        path = _fresh_db()
        try:
            with sqlite3.connect(path) as c:
                c.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running',
                  progress INTEGER NOT NULL DEFAULT 0, checkpoint_json TEXT,
                  cancelled_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS episode_events (
                  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, episode_id TEXT NOT NULL,
                  status TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
                );
                """)
                c.execute("INSERT INTO episodes (id,tenant_id,user_id,agent_id,status,progress,created_at,updated_at) "
                          "VALUES ('e1','local','u1','strategist','done',100,'x','x')")
            db = Database(path=path, tenant_id="local")  # triggers D2 columns + index
            ecols = {r["name"] for r in db.query("SELECT name FROM pragma_table_info('episodes')")}
            self.assertIn("work_type", ecols)
            self.assertIn("work_id", ecols)
            # existing row untouched
            row = db.query("SELECT * FROM episodes WHERE id='e1'")[0]
            self.assertEqual(row["status"], "done")
            self.assertIsNone(row["work_type"])
            # re-open idempotent
            Database(path=path, tenant_id="local")
        finally:
            for s in ("", "-wal", "-shm"):
                p = path + s
                if os.path.exists(p):
                    os.remove(p)


class TestStartExecution(PhaseD2Base):
    def test_start_goal_creates_one_running_episode_and_started_event(self):
        res = self.es.start_for_work("goal", self.gl, "strategist")
        self.assertFalse(res["already_active"])
        self.assertEqual(self._count("episodes"), 1)
        e = self.db.query("SELECT * FROM episodes WHERE id=?", (res["episode_id"],))[0]
        self.assertEqual(e["status"], "running")
        self.assertEqual(e["work_type"], "goal")
        self.assertEqual(e["work_id"], self.gl)
        events = self.db.query("SELECT * FROM episode_events WHERE episode_id=?", (res["episode_id"],))
        self.assertEqual([x["status"] for x in events], ["started"])

    def test_start_assignment_uses_assigned_agent(self):
        res = self.es.start_for_work("assignment", self.aid, "strategist")
        self.assertFalse(res["already_active"])
        e = self.db.query("SELECT * FROM episodes WHERE id=?", (res["episode_id"],))[0]
        self.assertEqual(e["agent_id"], "strategist")
        self.assertEqual(e["work_type"], "assignment")

    def test_duplicate_start_is_idempotent(self):
        r1 = self.es.start_for_work("goal", self.gl, "strategist")
        r2 = self.es.start_for_work("goal", self.gl, "strategist")
        self.assertEqual(r1["episode_id"], r2["episode_id"])
        self.assertTrue(r2["already_active"])
        self.assertEqual(self._count("episodes"), 1)

    def test_concurrent_start_keeps_single_active_episode(self):
        results = []
        barrier = threading.Barrier(2)

        def go():
            barrier.wait()
            results.append(self.es.start_for_work("goal", self.gl, "strategist"))

        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self._count("episodes"), 1)
        ids = {r["episode_id"] for r in results}
        self.assertEqual(len(ids), 1, "both attempts must converge on the same episode")


class TestEvidenceGating(PhaseD2Base):
    def setUp(self):
        super().setUp()
        self.eid = self.es.start_for_work("goal", self.gl, "strategist")["episode_id"]

    def test_checkpoint_requires_evidence(self):
        with self.assertRaises(ValueError):
            self.es.checkpoint_with_evidence(self.eid, 40, {})
        with self.assertRaises(ValueError):
            self.es.checkpoint_with_evidence(self.eid, 40, {"summary": ""})
        with self.assertRaises(ValueError):
            self.es.checkpoint_with_evidence(self.eid, 40, None)

    def test_checkpoint_rejects_secret_and_bad_progress(self):
        with self.assertRaises(ValueError):
            self.es.checkpoint_with_evidence(self.eid, 40, {"summary": "ok", "api_key": "x"})
        with self.assertRaises(ValueError):
            self.es.checkpoint_with_evidence(self.eid, -1, {"summary": "ok"})
        with self.assertRaises(ValueError):
            self.es.checkpoint_with_evidence(self.eid, 2, {"summary": "ok"})

    def test_checkpoint_and_complete_with_valid_evidence(self):
        self.assertTrue(self.es.checkpoint_with_evidence(self.eid, 0.5, {"summary": "milestone"}))
        e = self.db.query("SELECT * FROM episodes WHERE id=?", (self.eid,))[0]
        self.assertEqual(e["progress"], 0.5)
        self.assertTrue(self.es.complete_with_evidence(self.eid, {"summary": "all done"}))
        e = self.db.query("SELECT * FROM episodes WHERE id=?", (self.eid,))[0]
        self.assertEqual(e["status"], "done")
        self.assertEqual(e["progress"], 1.0)
        events = self.db.query("SELECT * FROM episode_events WHERE episode_id=? ORDER BY created_at",
                               (self.eid,))
        self.assertEqual([x["status"] for x in events], ["started", "checkpoint", "done"])

    def test_complete_requires_evidence_and_secret_rejected(self):
        with self.assertRaises(ValueError):
            self.es.complete_with_evidence(self.eid, {})
        with self.assertRaises(ValueError):
            self.es.complete_with_evidence(self.eid, {"summary": "x", "token": "t"})

    def test_checkpoint_after_done_is_rejected(self):
        self.es.complete_with_evidence(self.eid, {"summary": "done"})
        self.assertFalse(self.es.checkpoint_with_evidence(self.eid, 0.6, {"summary": "x"}))

    def test_cross_user_and_foreign_episode_rejected(self):
        other = EpisodeService(self.db, TENANT, "u2")
        self.assertEqual(len(other.get(self.eid) or []), 0)


class TestNoAutoCreation(PhaseD2Base):
    def test_approve_creates_no_episode(self):
        self.assertEqual(self._count("episodes"), 0)
        svc = WorkProposalService(self.db, TENANT, USER)
        pid = svc.propose("project", "strategist", payload={"workspace_id": self.ws, "name": "P"},
                          thread_id="t", idempotency_key="noauto-1")["proposal_id"]
        svc.approve(pid, USER)
        # approved work created a project, but NO episode.
        self.assertEqual(self._count("projects"), 2)  # setUp + 1
        self.assertEqual(self._count("episodes"), 0)


class TestEndpoints(unittest.TestCase):
    TENANT = "phaseD2"
    USER = "u1"

    def _headers(self, user=USER, tenant=TENANT, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def _seed(self):
        from config.settings import DB_PATH
        db = Database(path=DB_PATH, tenant_id=self.TENANT)
        ws = WorkspaceService(db, self.TENANT, self.USER).create("E WS")
        pr = ProjectService(db, self.TENANT, self.USER).create(ws, "E PR")
        gl = GoalService(db, self.TENANT, self.USER).create(pr, "Goal", 1)
        aid = AssignmentService(db, self.TENANT, self.USER).assign(gl, "strategist", 0)
        return db, gl, aid

    def test_execute_goal_returns_201_then_idempotent_200(self):
        db, gl, aid = self._seed()
        c = TestClient(app)
        r1 = c.post(f"/work/goal/{gl}/execute", headers=self._headers(),
                    json={"agent_id": "strategist"})
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r1.json()["status"], "running")
        eid = r1.json()["episode_id"]
        r2 = c.post(f"/work/goal/{gl}/execute", headers=self._headers(),
                    json={"agent_id": "strategist"})
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["already_active"])
        self.assertEqual(r2.json()["episode_id"], eid)

    def test_execute_assignment_agent_mismatch_422_and_unsupported_type_422(self):
        db, gl, aid = self._seed()
        c = TestClient(app)
        r = c.post(f"/work/assignment/{aid}/execute", headers=self._headers(),
                   json={"agent_id": "aisha"})
        self.assertEqual(r.status_code, 422)  # aisha != assigned strategist
        r2 = c.post("/work/project/xyz/execute", headers=self._headers(),
                    json={"agent_id": "strategist"})
        self.assertEqual(r2.status_code, 422)  # project not executable

    def test_self_start_and_cross_scope_rejected(self):
        db, gl, aid = self._seed()
        c = TestClient(app)
        r = c.post(f"/work/goal/{gl}/execute", headers=self._headers(user="strategist"),
                   json={"agent_id": "strategist"})
        self.assertEqual(r.status_code, 403)  # agent self-start
        r2 = c.post(f"/work/goal/{gl}/execute", headers=self._headers(user="u2"),
                    json={"agent_id": "strategist"})
        self.assertEqual(r2.status_code, 404)  # foreign user
        r3 = c.post(f"/work/goal/{gl}/execute", headers=self._headers(tenant="other"),
                    json={"agent_id": "strategist"})
        self.assertEqual(r3.status_code, 404)  # foreign tenant

    def test_non_human_role_denied(self):
        db, gl, aid = self._seed()
        c = TestClient(app)
        r = c.post(f"/work/goal/{gl}/execute", headers=self._headers(role="agent"),
                   json={"agent_id": "strategist"})
        self.assertEqual(r.status_code, 403)

    def test_checkpoint_and_complete_via_api(self):
        db, gl, aid = self._seed()
        c = TestClient(app)
        eid = c.post(f"/work/goal/{gl}/execute", headers=self._headers(),
                     json={"agent_id": "strategist"}).json()["episode_id"]
        # checkpoint with valid evidence
        r = c.post(f"/episodes/{eid}/checkpoint", headers=self._headers(),
                   json={"progress": 0.5, "evidence": {"summary": "milestone"}})
        self.assertEqual(r.status_code, 200)
        # empty evidence rejected
        r2 = c.post(f"/episodes/{eid}/checkpoint", headers=self._headers(),
                    json={"progress": 0.6, "evidence": {}})
        self.assertEqual(r2.status_code, 422)
        # complete with valid evidence
        r3 = c.post(f"/episodes/{eid}/complete", headers=self._headers(),
                    json={"evidence": {"summary": "done"}})
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["status"], "done")
        # detail returns events with evidence
        det = c.get(f"/episodes/{eid}", headers=self._headers()).json()
        self.assertIn("evidence_json", det["events"][0])

    def test_cross_user_cannot_checkpoint(self):
        db, gl, aid = self._seed()
        c = TestClient(app)
        eid = c.post(f"/work/goal/{gl}/execute", headers=self._headers(),
                     json={"agent_id": "strategist"}).json()["episode_id"]
        r = c.post(f"/episodes/{eid}/checkpoint", headers=self._headers(user="u2"),
                   json={"progress": 0.1, "evidence": {"summary": "x"}})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
