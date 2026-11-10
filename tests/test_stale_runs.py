"""Stale run visibility endpoint tests."""
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT


def _insert_run(db, run_id, status, started_at, tenant="t1", user="u1"):
    try:
        db.execute(
            "INSERT INTO agent_runs (id, project_id, tenant_id, user_id, status, created_at, started_at) VALUES (?,?,?,?,?,?,?)",
            (run_id, "p1", tenant, user, status, started_at, started_at),
        )
    except Exception:
        pass


class TestStaleRuns(unittest.TestCase):
    def setUp(self):
        self.db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        try:
            self.db.execute("DELETE FROM agent_runs WHERE project_id='p1'")
        except Exception:
            pass

    def _tok(self, u="u1", t="t1"):
        return issue_token(u, t, "user", 3600)

    def test_stale_returned(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        _insert_run(self.db, "r-old", "running", old)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertIn("r-old", ids)

    def test_fresh_excluded(self):
        fresh = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        _insert_run(self.db, "r-fresh", "running", fresh)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertNotIn("r-fresh", ids)

    def test_completed_excluded(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        _insert_run(self.db, "r-done", "completed", old)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertNotIn("r-done", ids)

    def test_failed_excluded(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        _insert_run(self.db, "r-fail", "failed", old)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertNotIn("r-fail", ids)

    def test_queued_excluded(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        _insert_run(self.db, "r-q", "queued", old)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertNotIn("r-q", ids)

    def test_custom_threshold(self):
        age = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        _insert_run(self.db, "r-60", "running", age)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=30", headers={"x-token": tok})
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertIn("r-60", ids)

    def test_invalid_threshold(self):
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=0", headers={"x-token": tok})
        self.assertEqual(r.status_code, 422)
        r2 = c.get("/runs/stale?older_than_seconds=100000", headers={"x-token": tok})
        self.assertEqual(r2.status_code, 422)

    def test_auth_required(self):
        c = TestClient(app)
        r = c.get("/runs/stale", headers={"x-token": "bad"})
        self.assertEqual(r.status_code, 401)

    def test_tenant_isolation(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        _insert_run(self.db, "r-other", "running", old, tenant="t2", user="u2")
        c = TestClient(app)
        tok = self._tok("u1", "t1")
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertNotIn("r-other", ids)

    def test_read_only(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        _insert_run(self.db, "r-ro", "running", old)
        c = TestClient(app)
        tok = self._tok()
        before = self.db.query("SELECT status, started_at FROM agent_runs WHERE id='r-ro'")
        c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        after = self.db.query("SELECT status, started_at FROM agent_runs WHERE id='r-ro'")
        self.assertEqual(before, after)


class TestStaleRunsHardening(unittest.TestCase):
    def setUp(self):
        self.db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        try:
            self.db.execute("DELETE FROM agent_runs WHERE project_id='p1'")
        except Exception:
            pass

    def _tok(self, u="u1", t="t1"):
        return issue_token(u, t, "user", 3600)

    def test_exact_field_set(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        _insert_run(self.db, "r-fields", "running", old)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        self.assertTrue(items)
        allowed = {"run_id", "project_id", "status", "started_at", "age_seconds", "possibly_stale"}
        for item in items:
            self.assertEqual(set(item.keys()), allowed)

    def test_missing_started_at_safe(self):
        try:
            self.db.execute(
                "INSERT INTO agent_runs (id, project_id, tenant_id, user_id, status, created_at, started_at) VALUES (?,?,?,?,?,?,?)",
                ("r-nostart", "p1", "t1", "u1", "running", datetime.now(timezone.utc).isoformat(), None),
            )
        except Exception:
            pass
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertNotIn("r-nostart", ids)

    def test_naive_timestamp_skipped(self):
        naive = (datetime.now(timezone.utc) - timedelta(seconds=400)).replace(tzinfo=None).isoformat()
        _insert_run(self.db, "r-naive", "running", naive)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertNotIn("r-naive", ids)


class TestNaiveTimestampCoexistence(unittest.TestCase):
    def setUp(self):
        self.db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        try:
            self.db.execute("DELETE FROM agent_runs WHERE project_id='p1'")
        except Exception:
            pass

    def _tok(self, u="u1", t="t1"):
        return issue_token(u, t, "user", 3600)

    def test_naive_skipped_valid_returned(self):
        naive = (datetime.now(timezone.utc) - timedelta(seconds=400)).replace(tzinfo=None).isoformat()
        aware = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        _insert_run(self.db, "r-naive2", "running", naive)
        _insert_run(self.db, "r-aware2", "running", aware)
        c = TestClient(app)
        tok = self._tok()
        r = c.get("/runs/stale?older_than_seconds=300", headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        ids = [x["run_id"] for x in r.json()["items"]]
        self.assertNotIn("r-naive2", ids)
        self.assertIn("r-aware2", ids)


if __name__ == "__main__":
    unittest.main()
