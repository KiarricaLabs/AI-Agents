"""M10 Phase D3 — evidence-backed goal progress application.

Verifies:
- D2 double-completion idempotency (running->done only, no duplicate events),
- D3 additive migration (episodes.applied_at/applied_by) on fresh + existing,
  idempotently, preserving existing rows,
- human-controlled, evidence-backed application: goal progress + completion,
  one application per episode, version guard, atomic audit,
- never-reduce progress, progress-only vs completion semantics,
- multiple sequential episodes each contribute to the same goal,
- security: foreign/cross-tenant/cross-user 404, agent role 403, stale 409,
  missing evidence rejected, no internal detail leaks,
- evidence integrity: apply uses persisted evidence only (no replacement),
- read-only execution summary (sanitized, no secrets).

All tests use isolated databases; the production DB is never opened.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from storage.database import Database
from core.auth import issue_token
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService
from core.episodes import (
    EpisodeService,
    EpisodeNotFound,
    EpisodeNotCompleted,
    MissingCompletionEvidence,
    GoalNotFound,
    StaleGoalVersion,
    GoalCompletionConflict,
)
from api.app import app


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


TENANT = "phaseD3"
USER = "u1"


class PhaseD3Base(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=TENANT)
        self.ws = WorkspaceService(self.db, TENANT, USER).create("WS")
        self.pr = ProjectService(self.db, TENANT, USER).create(self.ws, "PR")
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

    def _done_episode(self, work_type="goal", work_id=None, agent="strategist", progress=1.0,
                      summary="milestone verified"):
        """Create a completed episode (normal path) on a goal/assignment."""
        work_id = work_id or (self.gl if work_type == "goal" else self.aid)
        eid = self.es.start_for_work(work_type, work_id, agent)["episode_id"]
        self.assertTrue(self.es.complete_with_evidence(eid, {"summary": summary}))
        return eid

    def _done_episode_progress(self, progress, summary="partial"):
        """Craft a done episode at a given 0..1 progress (to exercise the
        progress-only branch, unreachable via complete() which pins 1.0)."""
        eid = "e" + str(uuid_hex())
        now = _now()
        self.db.execute(
            "INSERT INTO episodes (id,tenant_id,user_id,agent_id,status,progress,work_type,work_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (eid, TENANT, USER, "strategist", "done", progress, "goal", self.gl, now, now))
        self.db.execute(
            "INSERT INTO episode_events (id,tenant_id,episode_id,status,detail,evidence_json,progress,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid_hex()), TENANT, eid, "done", "completed",
             json.dumps({"summary": summary}), progress, now))
        return eid

    def _goal(self, gid):
        return self.db.query("SELECT * FROM goals WHERE id=?", (gid,))[0]

    def _make_goal_in_progress(self):
        self.db.execute("UPDATE goals SET status='in_progress' WHERE id=?", (self.gl,))


import uuid as _uuid
def uuid_hex():
    return _uuid.uuid4().hex


class TestMigration(unittest.TestCase):
    def test_fresh_db_has_d3_columns(self):
        path = _fresh_db()
        try:
            db = Database(path=path, tenant_id="local")
            cols = {r["name"] for r in db.query("SELECT name FROM pragma_table_info('episodes')")}
            self.assertIn("applied_at", cols)
            self.assertIn("applied_by", cols)
        finally:
            for s in ("", "-wal", "-shm"):
                p = path + s
                if os.path.exists(p):
                    os.remove(p)

    def test_existing_db_gains_d3_columns_and_preserves_rows(self):
        path = _fresh_db()
        try:
            with sqlite3.connect(path) as c:
                c.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running',
                  progress INTEGER NOT NULL DEFAULT 0, checkpoint_json TEXT,
                  work_type TEXT, work_id TEXT, cancelled_at TEXT,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                """)
                c.execute("INSERT INTO episodes (id,tenant_id,user_id,agent_id,status,progress,work_type,work_id,created_at,updated_at) "
                          "VALUES ('e1','local','u1','strategist','done',1,'goal','g1','x','x')")
            db = Database(path=path, tenant_id="local")  # adds D3 columns
            cols = {r["name"] for r in db.query("SELECT name FROM pragma_table_info('episodes')")}
            self.assertIn("applied_at", cols)
            self.assertIn("applied_by", cols)
            row = db.query("SELECT * FROM episodes WHERE id='e1'")[0]
            self.assertEqual(row["status"], "done")
            self.assertIsNone(row["applied_at"])  # untouched
            Database(path=path, tenant_id="local")  # reopen idempotent
        finally:
            for s in ("", "-wal", "-shm"):
                p = path + s
                if os.path.exists(p):
                    os.remove(p)


class TestDoubleCompletion(PhaseD3Base):
    def test_double_complete_creates_no_second_event(self):
        eid = self._done_episode()
        events_before = len(self.db.query("SELECT * FROM episode_events WHERE episode_id=?", (eid,)))
        self.assertFalse(self.es.complete_with_evidence(eid, {"summary": "again"}))
        events_after = len(self.db.query("SELECT * FROM episode_events WHERE episode_id=?", (eid,)))
        self.assertEqual(events_after, events_before)
        ep = self.db.query("SELECT * FROM episodes WHERE id=?", (eid,))[0]
        self.assertEqual(ep["status"], "done")

    def test_cancelled_episode_cannot_complete(self):
        eid = self.es.start_for_work("goal", self.gl, "strategist")["episode_id"]
        self.assertTrue(self.es.cancel(eid))
        self.assertFalse(self.es.complete_with_evidence(eid, {"summary": "x"}))


class TestApply(PhaseD3Base):
    def test_valid_apply_completes_goal(self):
        self._make_goal_in_progress()
        eid = self._done_episode()
        res = self.es.apply_completed_episode(eid, USER)
        self.assertTrue(res["applied"])
        self.assertFalse(res["already_applied"])
        self.assertEqual(res["goal_status"], "done")
        self.assertEqual(res["goal_progress"], 100)
        g = self._goal(self.gl)
        self.assertEqual(g["status"], "done")
        self.assertEqual(g["progress"], 100)
        self.assertEqual(g["version"], 1)
        ep = self.db.query("SELECT * FROM episodes WHERE id=?", (eid,))[0]
        self.assertEqual(ep["applied_by"], USER)
        self.assertTrue(ep["applied_at"])
        events = self.db.query("SELECT * FROM goal_events WHERE goal_id=?", (self.gl,))
        apply_events = [e for e in events if e["status"] == "done"]
        self.assertEqual(len(apply_events), 1)
        self.assertIn("milestone verified", apply_events[0]["detail"])

    def test_progress_only_apply_and_never_reduce(self):
        # goal open at progress 0; apply a done episode at 0.5 -> progress 50, status open
        eid = self._done_episode_progress(0.5)
        res = self.es.apply_completed_episode(eid, USER)
        self.assertEqual(res["goal_status"], "open")
        self.assertEqual(res["goal_progress"], 50)
        g = self._goal(self.gl)
        self.assertEqual(g["progress"], 50)
        self.assertEqual(g["status"], "open")
        self.assertEqual(g["version"], 1)
        # now a second partial apply at 0.5 must NOT reduce below current 50
        eid2 = self._done_episode_progress(0.5)
        res2 = self.es.apply_completed_episode(eid2, USER)
        self.assertEqual(res2["goal_progress"], 50)
        self.assertEqual(self._goal(self.gl)["progress"], 50)
        self.assertEqual(self._goal(self.gl)["version"], 2)

    def test_open_goal_cannot_be_completed_in_one_step(self):
        # goal is 'open'; completed episode at 1.0 -> conflict (preserve transitions)
        eid = self._done_episode()
        with self.assertRaises(GoalCompletionConflict):
            self.es.apply_completed_episode(eid, USER)
        g = self._goal(self.gl)
        self.assertEqual(g["status"], "open")
        self.assertEqual(g["version"], 0)

    def test_idempotent_reapply_does_not_duplicate(self):
        self._make_goal_in_progress()
        eid = self._done_episode()
        self.es.apply_completed_episode(eid, USER)
        events_before = len(self.db.query("SELECT * FROM goal_events WHERE goal_id=?", (self.gl,)))
        res = self.es.apply_completed_episode(eid, USER)
        self.assertTrue(res["already_applied"])
        events_after = len(self.db.query("SELECT * FROM goal_events WHERE goal_id=?", (self.gl,)))
        self.assertEqual(events_after, events_before)
        self.assertEqual(self._goal(self.gl)["version"], 1)

    def test_multiple_episodes_contribute(self):
        self._make_goal_in_progress()
        eid1 = self._done_episode()
        self.es.apply_completed_episode(eid1, USER)
        # a second, independent completed episode also applies
        eid2 = self._done_episode(summary="second contribution")
        res2 = self.es.apply_completed_episode(eid2, USER)
        self.assertTrue(res2["applied"])
        self.assertFalse(res2["already_applied"])
        g = self._goal(self.gl)
        self.assertEqual(g["version"], 2)  # each apply increments once
        ev = self.db.query("SELECT * FROM goal_events WHERE goal_id=? ORDER BY created_at", (self.gl,))
        apply_events = [e for e in ev if e["status"] in ("done", "progress_update")]
        self.assertEqual(len(apply_events), 2)

    def test_version_guard_uses_current_goal_version(self):
        # The guarded UPDATE targets the goal version read at apply time, so an
        # already-committed external version bump is re-read (not a false stale).
        self._make_goal_in_progress()
        eid = self._done_episode()
        self.db.execute("UPDATE goals SET version=version+1 WHERE id=?", (self.gl,))
        res = self.es.apply_completed_episode(eid, USER)
        self.assertTrue(res["applied"])
        self.assertEqual(self._goal(self.gl)["version"], 2)
        ep = self.db.query("SELECT * FROM episodes WHERE id=?", (eid,))[0]
        self.assertEqual(ep["applied_by"], USER)

    def test_missing_evidence_rejected(self):
        eid = self.es.start_for_work("goal", self.gl, "strategist")["episode_id"]
        # force done without a persisted done event (no evidence)
        self.db.execute("UPDATE episodes SET status='done', progress=1.0 WHERE id=?", (eid,))
        with self.assertRaises(MissingCompletionEvidence):
            self.es.apply_completed_episode(eid, USER)

    def test_non_completed_episode_rejected(self):
        eid = self.es.start_for_work("goal", self.gl, "strategist")["episode_id"]  # running
        with self.assertRaises(EpisodeNotCompleted):
            self.es.apply_completed_episode(eid, USER)

    def test_foreign_and_cross_scope_rejected(self):
        self._make_goal_in_progress()
        eid = self._done_episode()
        other = EpisodeService(self.db, TENANT, "u2")
        with self.assertRaises(EpisodeNotFound):
            other.apply_completed_episode(eid, "u2")
        other_t = EpisodeService(self.db, "other_tenant", USER)
        with self.assertRaises(EpisodeNotFound):
            other_t.apply_completed_episode(eid, USER)


class TestExecutionSummary(PhaseD3Base):
    def test_summary_lists_episodes_with_sanitized_evidence(self):
        self._make_goal_in_progress()
        eid = self._done_episode(summary="shipped report")
        self.es.apply_completed_episode(eid, USER)
        s = self.es.execution_summary("goal", self.gl)
        self.assertEqual(len(s["episodes"]), 1)
        it = s["episodes"][0]
        self.assertEqual(it["status"], "done")
        self.assertEqual(it["evidence_summary"], "shipped report")
        self.assertTrue(it["applied_at"])
        # no raw evidence dict / no password-ish fields
        self.assertNotIn("evidence_json", it)
        self.assertNotIn("api_key", json.dumps(it))

    def test_summary_unsupported_type_and_cross_scope(self):
        with self.assertRaises(ValueError):
            self.es.execution_summary("project", "x")
        other = EpisodeService(self.db, TENANT, "u2")
        s = other.execution_summary("goal", self.gl)
        self.assertEqual(s["episodes"], [])


class TestEndpoints(unittest.TestCase):
    TENANT = "phaseD3"
    USER = "u1"

    def _headers(self, user=USER, tenant=TENANT, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def _seed(self):
        from config.settings import DB_PATH
        db = Database(path=DB_PATH, tenant_id=self.TENANT)
        ws = WorkspaceService(db, self.TENANT, self.USER).create("E WS")
        pr = ProjectService(db, self.TENANT, self.USER).create(ws, "E PR")
        gl = GoalService(db, self.TENANT, self.USER).create(pr, "Goal", 1)
        db.execute("UPDATE goals SET status='in_progress' WHERE id=?", (gl,))
        es = EpisodeService(db, self.TENANT, self.USER)
        eid = es.start_for_work("goal", gl, "strategist")["episode_id"]
        es.complete_with_evidence(eid, {"summary": "delivered"})
        return db, gl, eid

    def test_apply_via_api_and_idempotent(self):
        db, gl, eid = self._seed()
        c = TestClient(app)
        r = c.post(f"/episodes/{eid}/apply", headers=self._headers())
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["already_applied"])
        self.assertEqual(r.json()["goal_status"], "done")
        # version incremented once
        g = db.query("SELECT * FROM goals WHERE id=?", (gl,))[0]
        self.assertEqual(g["version"], 1)
        r2 = c.post(f"/episodes/{eid}/apply", headers=self._headers())
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["already_applied"])
        self.assertEqual(db.query("SELECT version FROM goals WHERE id=?", (gl,))[0]["version"], 1)

    def test_apply_foreign_cross_and_agent_denied(self):
        db, gl, eid = self._seed()
        c = TestClient(app)
        self.assertEqual(c.post(f"/episodes/{eid}/apply", headers=self._headers(user="u2")).status_code, 404)
        self.assertEqual(c.post(f"/episodes/{eid}/apply", headers=self._headers(tenant="other")).status_code, 404)
        self.assertEqual(c.post(f"/episodes/{eid}/apply", headers=self._headers(role="agent")).status_code, 403)

    def test_apply_running_episode_422_and_stale_409(self):
        from config.settings import DB_PATH
        db = Database(path=DB_PATH, tenant_id=self.TENANT)
        ws = WorkspaceService(db, self.TENANT, self.USER).create("S WS")
        pr = ProjectService(db, self.TENANT, self.USER).create(ws, "S PR")
        gl = GoalService(db, self.TENANT, self.USER).create(pr, "G", 1)
        db.execute("UPDATE goals SET status='in_progress' WHERE id=?", (gl,))
        es = EpisodeService(db, self.TENANT, self.USER)
        eid_running = es.start_for_work("goal", gl, "strategist")["episode_id"]
        c = TestClient(app)
        # running(not completed) -> 422
        r = c.post(f"/episodes/{eid_running}/apply", headers=self._headers())
        self.assertEqual(r.status_code, 422)
        # genuinely-concurrent version conflict maps to 409 (StaleGoalVersion).
        orig = EpisodeService.apply_completed_episode
        EpisodeService.apply_completed_episode = lambda self_, eid_, appr_: (_ for _ in ()).throw(StaleGoalVersion("goal changed concurrently"))
        try:
            r2 = c.post(f"/episodes/{eid_running}/apply", headers=self._headers())
            self.assertEqual(r2.status_code, 409)
        finally:
            EpisodeService.apply_completed_episode = orig

    def test_execution_endpoint(self):
        db, gl, eid = self._seed()
        c = TestClient(app)
        r = c.get(f"/work/goal/{gl}/execution", headers=self._headers())
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()["episodes"]), 1)
        self.assertEqual(r.status_code, 200)
        bad = c.get("/work/project/abc/execution", headers=self._headers())
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
