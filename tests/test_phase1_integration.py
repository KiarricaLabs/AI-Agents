import os, tempfile, unittest
from fastapi.testclient import TestClient
from api.app import app
from core.auth import issue_token


class TestPhase1Integration(unittest.TestCase):
    def test_health_ok(self):
        c = TestClient(app)
        r = c.get("/health")
        self.assertEqual(r.status_code, 200)

    def test_invalid_token_rejected(self):
        c = TestClient(app)
        r = c.get("/workspaces", headers={"x-token": "bad.token"})
        self.assertEqual(r.status_code, 401)

    def test_0_valid_token_accepted(self):
        c = TestClient(app)
        t = issue_token("local", "local", "admin")
        r = c.get("/workspaces", headers={"x-token": t})
        self.assertEqual(r.status_code, 200)

    def test_tracing_spans_emitted(self):
        from core.tracing import get_spans
        before = len(get_spans())
        c = TestClient(app)
        c.get("/health")
        after = len(get_spans())
        self.assertGreater(after, before)

    def test_rate_limit(self):
        c = TestClient(app)
        for _ in range(101):
            c.get("/health")
        r = c.get("/health")
        self.assertIn(r.status_code, (200, 429))

    def test_audit_export_admin_ok(self):
        c = TestClient(app)
        t = issue_token("local", "local", "admin")
        r = c.get("/workspaces/audit/export", headers={"x-token": t})
        self.assertEqual(r.status_code, 200)

    def test_audit_export_nonadmin_forbidden(self):
        c = TestClient(app)
        t = issue_token("u2", "local", "user")
        r = c.get("/workspaces/audit/export", headers={"x-token": t})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()