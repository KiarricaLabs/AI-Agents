"""HTTP-level tests for the workspaces router, focused on the additive
deliverable-listing enrichment (latest_status / latest_version) added for the
Phase C "Work" view.

These run against the isolated test database (see tests/__init__.py).
"""
import unittest

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token


def _auth(tenant, user="u1"):
    return {"x-token": issue_token(user, tenant, "admin")}


class TestDeliverableListingEnrichment(unittest.TestCase):
    def test_latest_status_and_version_are_exposed(self):
        c = TestClient(app)
        h = _auth("tenantC")

        wid = c.post("/workspaces", json={"name": "W"}, headers=h).json()["id"]
        pid = c.post("/workspaces/projects", json={"workspace_id": wid, "name": "P"}, headers=h).json()["id"]
        did = c.post("/workspaces/deliverables", json={"project_id": pid, "title": "Report"}, headers=h).json()["id"]

        # no versions yet -> latest_status / latest_version are null
        items = c.get("/workspaces/deliverables", headers=h).json()["items"]
        row = next(d for d in items if d["id"] == did)
        self.assertIsNone(row["latest_status"])
        self.assertIsNone(row["latest_version"])

        v1 = c.post(f"/workspaces/deliverables/{did}/versions", json={"content": "v1"}, headers=h).json()
        v2 = c.post(f"/workspaces/deliverables/{did}/versions", json={"content": "v2"}, headers=h).json()
        self.assertEqual(v2["version"], 2)

        items = c.get("/workspaces/deliverables", headers=h).json()["items"]
        row = next(d for d in items if d["id"] == did)
        self.assertEqual(row["latest_version"], 2)
        self.assertEqual(row["latest_status"], "draft")

        c.post(f"/workspaces/versions/{v2['id']}/approve", headers=h)
        items = c.get("/workspaces/deliverables", headers=h).json()["items"]
        row = next(d for d in items if d["id"] == did)
        self.assertEqual(row["latest_status"], "approved")

    def test_cross_tenant_deliverables_not_listed(self):
        c = TestClient(app)
        ha = _auth("tenantC2", "ua")
        hb = _auth("tenantC2b", "ub")

        wid = c.post("/workspaces", json={"name": "W"}, headers=ha).json()["id"]
        pid = c.post("/workspaces/projects", json={"workspace_id": wid, "name": "P"}, headers=ha).json()["id"]
        c.post("/workspaces/deliverables", json={"project_id": pid, "title": "Secret"}, headers=ha)

        # tenant B has its own (empty) deliverable set; tenant A's rows are hidden
        items_b = c.get("/workspaces/deliverables", headers=hb).json()["items"]
        self.assertNotIn("Secret", [d["title"] for d in items_b])


if __name__ == "__main__":
    unittest.main()
