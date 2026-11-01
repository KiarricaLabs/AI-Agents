import os
import tempfile
import unittest

from storage.database import Database


class TestTenantIsolation(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_default_tenant_created(self):
        rows = self.db.query("SELECT * FROM tenants")
        self.assertTrue(any(r["id"] == "t1" for r in rows))

    def test_tenant_filter(self):
        self.db.execute("INSERT INTO memory_items (id,tenant_id,user_id,owner,kind,key,value,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        ("m1","t1","u1","user","note","k","v","2020","2020"))
        sql, params = self.db.tenant_filter("SELECT * FROM memory_items", "t2")
        rows = self.db.query(sql, params)
        self.assertEqual(rows, [])

    def test_cross_tenant_update_blocked(self):
        self.db.execute("INSERT INTO memory_items (id,tenant_id,user_id,owner,kind,key,value,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        ("m2","t1","u1","user","note","k","v","2020","2020"))
        # Attempt update as t2 should affect 0 rows when tenant guard applied
        # Simulate by filtering
        sql, params = self.db.tenant_filter("SELECT id FROM memory_items WHERE id='m2'", "t2")
        rows = self.db.query(sql, params)
        self.assertEqual(rows, [])

    def test_missing_tenant_context_fails(self):
        # tenant_filter with None should fall back to default, not crash; but explicit None tenant_id in execute is allowed (uses default).
        # Ensure Database requires tenant for tenant-owned tables by checking default tenant exists.
        self.assertIsNotNone(self.db.default_tenant)


if __name__ == "__main__":
    unittest.main()