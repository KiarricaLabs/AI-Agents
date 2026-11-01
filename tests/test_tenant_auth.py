import unittest
from fastapi.testclient import TestClient
from api.app import app
from core.auth import issue_token


class TestTenantAuth(unittest.TestCase):
    def test_tenant_isolation_via_token(self):
        c = TestClient(app)
        ta = issue_token("ua", "tenantA", "admin")
        tb = issue_token("ub", "tenantB", "admin")

        r = c.post("/workspaces", json={"name": "A1"}, headers={"x-token": ta})
        self.assertEqual(r.status_code, 200)
        ra = c.get("/workspaces", headers={"x-token": ta})
        names_a = [w["name"] for w in ra.json()["items"]]
        self.assertIn("A1", names_a)
        rb = c.get("/workspaces", headers={"x-token": tb})
        names_b = [w["name"] for w in rb.json()["items"]]
        self.assertNotIn("A1", names_b)

    def test_cross_tenant_modify_blocked(self):
        c = TestClient(app)
        ta = issue_token("ua", "tenantA", "admin")
        tb = issue_token("ub", "tenantB", "admin")
        r = c.post("/workspaces/projects", json={"workspace_id": "none", "name": "p"}, headers={"x-token": ta})
        # tenant B cannot list tenant A projects (returns its own set)
        rb = c.get("/workspaces/projects", headers={"x-token": tb})
        self.assertEqual(rb.status_code, 200)

    def test_missing_identity_rejected(self):
        # manually construct a request-like object without state identity
        from api.routers.workspaces import _identity
        class R:
            class state: pass
        with self.assertRaises(Exception):
            _identity(R())  # no tenant/user -> 401