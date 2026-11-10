"""Run queue visibility endpoint tests."""
import unittest
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT


def _insert_run(db, run_id, status, created_at, tenant="t1", user="u1"):
    try:
        db.execute(
            "INSERT INTO agent_runs (id, project_id, tenant_id, user_id, status, created_at) VALUES (?,?,?,?,?,?)",
            (run_id, "p1", tenant, user, status, created_at),
        )
    except Exception:
        pass


class TestRunQueue(unittest.TestCase):
    def setUp(self):
        self.db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        try:
            self.db.execute("DELETE FROM agent_runs WHERE project_id='p1'")
        except Exception:
            pass

    def _tok(self, u="u1", t="t1"):
        return issue_token(u, t, "user", 3600)

    def test_queued_count(self):
        now = datetime.now(timezone.utc).isoformat()
        _insert_run(self.db, "q1", "queued", now)
        _insert_run(self.db, "q2", "queued", now)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["queued_count"], 2)

    def test_running_count(self):
        now = datetime.now(timezone.utc).isoformat()
        _insert_run(self.db, "rn1", "running", now)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertEqual(r.json()["running_count"], 1)

    def test_oldest_age(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        _insert_run(self.db, "qold", "queued", old)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertIsNotNone(r.json()["oldest_queued_age_seconds"])
        self.assertGreaterEqual(r.json()["oldest_queued_age_seconds"], 90)

    def test_empty_queue(self):
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["queued_count"], 0)
        self.assertEqual(r.json()["running_count"], 0)
        self.assertIsNone(r.json()["oldest_queued_age_seconds"])

    def test_completed_failed_excluded(self):
        now = datetime.now(timezone.utc).isoformat()
        _insert_run(self.db, "qc", "completed", now)
        _insert_run(self.db, "qf", "failed", now)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertEqual(r.json()["queued_count"], 0)

    def test_auth_required(self):
        c = TestClient(app)
        r = c.get("/runs/queue", headers={"x-token": "bad"})
        self.assertEqual(r.status_code, 401)

    def test_tenant_isolation(self):
        now = datetime.now(timezone.utc).isoformat()
        _insert_run(self.db, "qother", "queued", now, tenant="t2", user="u2")
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertEqual(r.json()["queued_count"], 0)

    def test_read_only(self):
        now = datetime.now(timezone.utc).isoformat()
        _insert_run(self.db, "qro", "queued", now)
        c = TestClient(app)
        tok = self._tok()
        before = self.db.query("SELECT status FROM agent_runs WHERE id='qro'")
        c.get("/runs/queue", headers={"x-token": tok})
        after = self.db.query("SELECT status FROM agent_runs WHERE id='qro'")
        self.assertEqual(before, after)

    def test_exact_fields(self):
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertEqual(set(r.json().keys()), {"queued_count", "running_count", "oldest_queued_age_seconds"})

    def test_naive_timestamp_safe(self):
        naive = (datetime.now(timezone.utc) - timedelta(seconds=100)).replace(tzinfo=None).isoformat()
        _insert_run(self.db, "qnaive", "queued", naive)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        # naive oldest skipped -> null (if only naive queued)
        # (age cannot be determined)
        self.assertIsNone(r.json()["oldest_queued_age_seconds"])


class TestQueueResponseContract(unittest.TestCase):
    def setUp(self):
        self.db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        try:
            self.db.execute("DELETE FROM agent_runs WHERE project_id='p1'")
        except Exception:
            pass

    def _tok(self, u="u1", t="t1"):
        return issue_token(u, t, "user", 3600)

    def test_exact_fields_and_types(self):
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/queue", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body.keys()), {"queued_count", "running_count", "oldest_queued_age_seconds"})
        self.assertIsInstance(body["queued_count"], int)
        self.assertIsInstance(body["running_count"], int)
        self.assertTrue(body["oldest_queued_age_seconds"] is None or isinstance(body["oldest_queued_age_seconds"], int))
        self.assertEqual(body["queued_count"], 0)
        self.assertEqual(body["running_count"], 0)
        self.assertIsNone(body["oldest_queued_age_seconds"])


if __name__ == "__main__":
    unittest.main()
