"""Phase A tests: persistent brand intelligence (migrations, BrandService, API).

Covers additive migrations on fresh + existing DBs, tenant isolation, multiple
brands with explicit selection, immutable version history with proposal/approval
traceability, admin-gated actions, and credential-content rejection.
"""
import os
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token
from core.brand import BrandService
from storage.database import Database

BRAND_TABLES = ("brands", "brand_facts", "brand_proposals", "brand_history")


def _fresh_db(tenant="local"):
    d = tempfile.TemporaryDirectory()
    path = os.path.join(d.name, "brand.db")
    db = Database(path=path, tenant_id=tenant)
    return d, db


class TestBrandMigration(unittest.TestCase):
    def test_fresh_db_has_brand_tables(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(path=os.path.join(d, "f.db"), tenant_id="local")
            tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
            for t in BRAND_TABLES:
                self.assertIn(t, tables)

    def test_existing_db_is_migrated_without_data_loss(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "existing.db")
            # Simulate a pre-M10 database that already has the tenants table + data.
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)")
            conn.execute("INSERT INTO tenants (id,name,created_at) VALUES ('local','Local','2020-01-01')")
            conn.commit()
            conn.close()

            db = Database(path=path, tenant_id="local")
            tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
            for t in BRAND_TABLES:
                self.assertIn(t, tables)
            rows = db.query("SELECT name FROM tenants WHERE id='local'")
            self.assertEqual(rows[0]["name"], "Local")

    def test_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "i.db")
            Database(path=path, tenant_id="local")
            # Reopening must not error or duplicate anything.
            db = Database(path=path, tenant_id="local")
            tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(len([t for t in BRAND_TABLES if t in tables]), len(BRAND_TABLES))


class TestBrandService(unittest.TestCase):
    def setUp(self):
        self._dir, self.db = _fresh_db()
        self.svc = BrandService(self.db, "local")

    def tearDown(self):
        self._dir.cleanup()

    def test_brand_crud_and_default_selection(self):
        b1 = self.svc.create_brand("Acme", user_id="u1", is_default=True)
        b2 = self.svc.create_brand("Globex", user_id="u1")
        names = sorted(b["name"] for b in self.svc.list_brands())
        self.assertEqual(names, ["Acme", "Globex"])
        self.assertEqual(self.svc.get_default_brand()["id"], b1)
        # Explicitly switch the default.
        self.svc.set_default_brand(b2, user_id="u1")
        self.assertEqual(self.svc.get_default_brand()["id"], b2)
        # Ensure only one default remains.
        defaults = [b for b in self.svc.list_brands() if b["is_default"]]
        self.assertEqual(len(defaults), 1)

    def test_multiple_brands_do_not_combine(self):
        b1 = self.svc.create_brand("A", user_id="u1")
        b2 = self.svc.create_brand("B", user_id="u1")
        pid = self.svc.propose(b1, "voice", "tone", "friendly", user_id="u1")
        self.svc.approve(pid, "u1")
        self.assertEqual(len(self.svc.list_facts(b1)), 1)
        self.assertEqual(len(self.svc.list_facts(b2)), 0)

    def test_propose_approve_and_retrieve(self):
        b = self.svc.create_brand("Acme", user_id="u1")
        pid = self.svc.propose(b, "voice", "tone", "warm", user_id="u1")
        self.assertEqual(self.svc.list_facts(b), [])
        fid = self.svc.approve(pid, "admin_user")
        facts = self.svc.list_facts(b)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["value"], "warm")
        self.assertEqual(facts[0]["id"], fid)
        self.assertEqual(facts[0]["proposal_id"], pid)
        self.assertEqual(facts[0]["approved_by_user_id"], "admin_user")

    def test_reject_does_not_create_fact(self):
        b = self.svc.create_brand("Acme", user_id="u1")
        pid = self.svc.propose(b, "mission", "purpose", "x", user_id="u1")
        self.svc.reject(pid, "admin_user")
        self.assertEqual(self.svc.list_facts(b), [])
        self.assertEqual(self.svc.list_proposals(b)[0]["status"], "rejected")

    def test_immutable_version_history(self):
        b = self.svc.create_brand("Acme", user_id="u1")
        p1 = self.svc.propose(b, "voice", "tone", "friendly", user_id="u1")
        self.svc.approve(p1, "admin")
        p2 = self.svc.propose(b, "voice", "tone", "professional", user_id="u1", base_version=1)
        self.svc.approve(p2, "admin")

        versions = self.svc.fact_versions(b, "voice", "tone")
        self.assertEqual([v["version"] for v in versions], [1, 2])
        self.assertEqual(versions[0]["value"], "friendly")       # immutable
        self.assertEqual(versions[0]["status"], "superseded")
        self.assertEqual(versions[1]["value"], "professional")
        self.assertEqual(versions[1]["status"], "approved")
        # list_facts returns only the active version.
        active = self.svc.list_facts(b)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["value"], "professional")

    def test_stale_edit_proposal_is_rejected(self):
        b = self.svc.create_brand("Acme", user_id="u1")
        p1 = self.svc.propose(b, "voice", "tone", "friendly", user_id="u1")
        self.svc.approve(p1, "admin")
        # Two edits both based on v1; approving the first advances to v2.
        pa = self.svc.propose(b, "voice", "tone", "casual", user_id="u1", base_version=1)
        pb = self.svc.propose(b, "voice", "tone", "formal", user_id="u1", base_version=1)
        self.svc.approve(pa, "admin")
        with self.assertRaises(ValueError):
            self.svc.approve(pb, "admin")  # stale: v1 != current v2

    def test_credential_content_is_rejected(self):
        b = self.svc.create_brand("Acme", user_id="u1")
        with self.assertRaises(ValueError):
            self.svc.propose(b, "identity", "api_key", "sk-123", user_id="u1")
        with self.assertRaises(ValueError):
            self.svc.propose(b, "identity", "brand", "password is hunter2", user_id="u1")

    def test_history_traceability(self):
        b = self.svc.create_brand("Acme", user_id="u1")
        pid = self.svc.propose(b, "values", "integrity", "yes", user_id="u1")
        self.svc.approve(pid, "admin")
        events = self.svc.history(b)
        actions = [e["action"] for e in events]
        self.assertIn("create_brand", actions)
        self.assertIn("propose", actions)
        approve = [e for e in events if e["action"] == "approve"][0]
        self.assertEqual(approve["new_value"], "yes")
        self.assertEqual(approve["proposal_id"], pid)

    def test_revoke_marks_fact_revoked_and_excluded(self):
        b = self.svc.create_brand("Acme", user_id="u1")
        pid = self.svc.propose(b, "voice", "tone", "warm", user_id="u1")
        fid = self.svc.approve(pid, "admin")
        self.svc.revoke(fid, "admin")
        self.assertEqual(self.svc.list_facts(b), [])
        versions = self.svc.fact_versions(b, "voice", "tone")
        self.assertEqual(versions[0]["status"], "revoked")

    def test_tenant_isolation_at_service_level(self):
        d2, db2 = _fresh_db(tenant="tenantB")
        try:
            svc_b = BrandService(db2, "tenantB")
            b = self.svc.create_brand("Acme", user_id="u1")
            # Tenant B cannot see Tenant A's brand.
            with self.assertRaises(ValueError):
                svc_b.get_brand(b)
            self.assertEqual(svc_b.list_brands(), [])
        finally:
            d2.cleanup()


class TestBrandAPI(unittest.TestCase):
    def _admin(self, user="ua", tenant="ba"):
        return {"x-token": issue_token(user, tenant, "admin")}

    def _user(self, user="ub", tenant="ba"):
        return {"x-token": issue_token(user, tenant, "user")}

    def test_create_brand_requires_admin(self):
        c = TestClient(app)
        r = c.post("/brand", json={"name": "Acme"}, headers=self._user())
        self.assertEqual(r.status_code, 403)

    def test_create_and_list_brands(self):
        c = TestClient(app)
        h = self._admin()
        r = c.post("/brand", json={"name": "Acme"}, headers=h)
        self.assertEqual(r.status_code, 200)
        bid = r.json()["id"]
        r = c.get("/brand", headers=h)
        names = [b["name"] for b in r.json()["brands"] if b["id"] == bid]
        self.assertEqual(names, ["Acme"])

    def test_tenant_isolation_via_api(self):
        c = TestClient(app)
        ha = self._admin(user="ua", tenant="ba")
        hb = self._admin(user="ub", tenant="bb")
        r = c.post("/brand", json={"name": "Acme"}, headers=ha)
        bid = r.json()["id"]
        # Tenant B cannot see Tenant A's brand or its facts/proposals.
        self.assertEqual(c.get("/brand", headers=hb).json()["brands"], [])
        self.assertEqual(c.get(f"/brand/{bid}", headers=hb).status_code, 404)
        self.assertEqual(c.get(f"/brand/{bid}/facts", headers=hb).status_code, 404)

    def test_proposal_approval_flow_via_api(self):
        c = TestClient(app)
        h = self._admin(user="ua", tenant="bc")
        bid = c.post("/brand", json={"name": "Acme"}, headers=h).json()["id"]
        pid = c.post(f"/brand/{bid}/proposals",
                     json={"category": "voice", "key": "tone", "value": "warm"}, headers=h).json()["proposal_id"]
        # Not yet approved -> no facts.
        self.assertEqual(c.get(f"/brand/{bid}/facts", headers=h).json()["facts"], [])
        # Non-admin cannot approve.
        self.assertEqual(c.post(f"/brand/proposals/{pid}/approve", json={}, headers=self._user(user="u2", tenant="bc")).status_code, 403)
        # Admin approves.
        r = c.post(f"/brand/proposals/{pid}/approve", json={}, headers=h)
        self.assertEqual(r.status_code, 200)
        facts = c.get(f"/brand/{bid}/facts", headers=h).json()["facts"]
        self.assertEqual([f["value"] for f in facts], ["warm"])

    def test_approve_and_revoke_require_admin(self):
        c = TestClient(app)
        h = self._admin(user="ua", tenant="bd")
        bid = c.post("/brand", json={"name": "Acme"}, headers=h).json()["id"]
        pid = c.post(f"/brand/{bid}/proposals",
                     json={"category": "voice", "key": "tone", "value": "warm"}, headers=h).json()["proposal_id"]
        fid = c.post(f"/brand/proposals/{pid}/approve", json={}, headers=h).json()["fact_id"]
        self.assertEqual(c.post(f"/brand/facts/{fid}/revoke", json={}, headers=self._user(user="u2", tenant="bd")).status_code, 403)
        self.assertEqual(c.post(f"/brand/proposals/{pid}/reject", json={}, headers=self._user(user="u2", tenant="bd")).status_code, 403)

    def test_credential_rejection_via_api(self):
        c = TestClient(app)
        h = self._admin(user="ua", tenant="be")
        bid = c.post("/brand", json={"name": "Acme"}, headers=h).json()["id"]
        r = c.post(f"/brand/{bid}/proposals",
                   json={"category": "identity", "key": "api_key", "value": "secret"}, headers=h)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
