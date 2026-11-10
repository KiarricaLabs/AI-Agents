"""Readiness endpoint tests."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app


class TestReady(unittest.TestCase):
    def test_ready_healthy(self):
        with patch("storage.database.Database.query", return_value=[{"1": 1}]):
            with patch("core.model_router.ModelRouter.check_availability", return_value={"ok": True}):
                c = TestClient(app)
                r = c.get("/ready")
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertTrue(body["ready"])
                self.assertEqual(body["checks"]["database"], "ok")
                self.assertEqual(body["checks"]["model"], "ok")
                self.assertEqual(body["checks"]["queue"], "unknown")
                self.assertIn("timestamp", body)

    def test_ready_db_fail(self):
        with patch("storage.database.Database.query", side_effect=Exception("boom")):
            with patch("core.model_router.ModelRouter.check_availability", return_value={"ok": True}):
                c = TestClient(app)
                r = c.get("/ready")
                self.assertEqual(r.status_code, 503)
                self.assertFalse(r.json()["ready"])
                self.assertEqual(r.json()["checks"]["database"], "fail")
                self.assertNotIn("boom", r.text)

    def test_ready_model_fail(self):
        with patch("storage.database.Database.query", return_value=[{"1": 1}]):
            with patch("core.model_router.ModelRouter.check_availability", return_value={"ok": False}):
                c = TestClient(app)
                r = c.get("/ready")
                self.assertEqual(r.status_code, 503)
                self.assertEqual(r.json()["checks"]["model"], "fail")

    def test_ready_db_timeout(self):
        calls = {"n": 0}

        async def fake_wait_for(coro, timeout):
            try:
                coro.close()
            except Exception:
                pass
            calls["n"] += 1
            if calls["n"] == 1:
                raise asyncio.TimeoutError()
            return True

        with patch("storage.database.Database.query", return_value=[{"1": 1}]):
            with patch("core.model_router.ModelRouter.check_availability", return_value={"ok": True}):
                with patch("asyncio.wait_for", side_effect=fake_wait_for):
                    c = TestClient(app)
                    r = c.get("/ready")
                    self.assertEqual(r.status_code, 503)
                    self.assertEqual(r.json()["checks"]["database"], "fail")

    def test_ready_model_timeout(self):
        calls = {"n": 0}

        async def fake_wait_for(coro, timeout):
            try:
                coro.close()
            except Exception:
                pass
            calls["n"] += 1
            if calls["n"] == 2:
                raise asyncio.TimeoutError()
            return True

        with patch("storage.database.Database.query", return_value=[{"1": 1}]):
            with patch("core.model_router.ModelRouter.check_availability", return_value={"ok": True}):
                with patch("asyncio.wait_for", side_effect=fake_wait_for):
                    c = TestClient(app)
                    r = c.get("/ready")
                    self.assertEqual(r.status_code, 503)
                    self.assertEqual(r.json()["checks"]["model"], "fail")

    def test_ready_queue_unknown_ok(self):
        with patch("storage.database.Database.query", return_value=[{"1": 1}]):
            with patch("core.model_router.ModelRouter.check_availability", return_value={"ok": True}):
                c = TestClient(app)
                r = c.get("/ready")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["checks"]["queue"], "unknown")

    def test_health_unchanged(self):
        c = TestClient(app)
        r = c.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})


if __name__ == "__main__":
    unittest.main()
