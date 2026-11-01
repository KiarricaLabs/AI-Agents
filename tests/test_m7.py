import os, tempfile, unittest, json
from core.auth import issue_token, verify_token, hash_refresh
from core.policy import PolicyEngine
from core.jobs import DurableJobQueue
from storage.database import Database
from core.backup import backup, restore


class TestM7(unittest.TestCase):
    def test_auth_roundtrip(self):
        t = issue_token("u1", "t1", "user")
        p = verify_token(t)
        self.assertEqual(p["sub"], "u1")
        self.assertEqual(p["tenant"], "t1")
        expired = verify_token("bad.token")
        self.assertIsNone(expired)

    def test_refresh_hash(self):
        self.assertEqual(hash_refresh("abc"), hash_refresh("abc"))
        self.assertNotEqual(hash_refresh("abc"), hash_refresh("xyz"))

    def test_policy_default_deny(self):
        pe = PolicyEngine.from_dict({"rules": [{"subject": "agent1", "action": "read", "resource": "memory", "effect": "allow"}]})
        self.assertTrue(pe.allow("agent1", "read", "memory"))
        self.assertFalse(pe.allow("agent2", "read", "memory"))
        self.assertFalse(pe.allow("agent1", "write", "memory"))

    def test_policy_invalid(self):
        with self.assertRaises(ValueError):
            PolicyEngine.from_dict("not a dict")

    def test_durable_jobs_idempotency(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(path)
        db = Database(path=path, tenant_id="t1")
        q = DurableJobQueue(db)
        j1 = q.enqueue("t1", {"x": 1}, idempotency_key="k1")
        j2 = q.enqueue("t1", {"x": 1}, idempotency_key="k1")
        self.assertEqual(j1, j2)
        # claim + complete
        job = q.claim(j1)
        self.assertEqual(job["status"], "running")
        q.complete(j1, {"ok": True})
        job2 = q.claim(j1)
        self.assertNotEqual(job2["status"], "running")
        os.remove(path)

    def test_backup_restore(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(path)
        db = Database(path=path, tenant_id="t1")
        backup(path, path + ".bak")
        # modify
        db.execute("INSERT INTO tenants (id,name,created_at) VALUES (?,?,?)", ("t2", "x", "now"))
        restore(path + ".bak", path)
        db2 = Database(path=path, tenant_id="t1")
        rows = db2.query("SELECT * FROM tenants WHERE id='t2'")
        self.assertEqual(rows, [])
        os.remove(path)
        os.remove(path + ".bak")


if __name__ == "__main__":
    unittest.main()