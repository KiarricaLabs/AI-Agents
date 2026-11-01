import os
import tempfile
import unittest

from storage.database import Database
from core.memory import MemoryService


class TestMemory(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ms = MemoryService(db=self.db, tenant_id="t1")

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_propose_and_approve(self):
        pid = self.ms.propose("u1", "agent1", "profile", "name", "Kia", confidence=0.9)
        self.ms.approve(pid, "u1")
        items = self.ms.list_profile("u1")
        self.assertTrue(any(i["key"] == "name" for i in items))

    def test_reject(self):
        pid = self.ms.propose("u1", "agent1", "profile", "city", "Oakland", confidence=0.9)
        self.ms.reject(pid, "u1")
        proposals = self.ms.list_proposals("u1", status="rejected")
        self.assertTrue(any(p["id"] == pid for p in proposals))

    def test_edit_before_approval(self):
        pid = self.ms.propose("u1", "agent1", "profile", "city", "Oakland", confidence=0.9)
        self.ms.approve(pid, "u1", edited_value="San Francisco")
        items = self.ms.list_profile("u1")
        self.assertTrue(any(i["value"] == "San Francisco" for i in items))

    def test_revoke(self):
        pid = self.ms.propose("u1", "agent1", "profile", "hobby", "music", confidence=0.9)
        self.ms.approve(pid, "u1")
        items = self.ms.list_profile("u1")
        mid = items[0]["id"]
        self.ms.revoke(mid, "u1")
        items2 = self.ms.list_profile("u1")
        self.assertFalse(any(i["id"] == mid for i in items2))

    def test_sensitive_blocked(self):
        with self.assertRaises(ValueError):
            self.ms.propose("u1", "agent1", "profile", "password", "secret123", confidence=0.9)

    def test_low_confidence_blocked(self):
        with self.assertRaises(ValueError):
            self.ms.propose("u1", "agent1", "profile", "x", "y", confidence=0.1)

    def test_private_memory_isolation(self):
        self.ms.set_private("agent1", "u1", "notes", "private stuff")
        # agent2 cannot read agent1 private without permission
        with self.assertRaises(PermissionError):
            self.ms.read_private("agent2", "agent1", "u1", permission=False)
        # with permission ok
        res = self.ms.read_private("agent2", "agent1", "u1", permission=True)
        self.assertTrue(len(res) > 0)

    def test_conversation_not_auto_profile(self):
        self.ms.add_conversation("u1", "I love pizza")
        items = self.ms.list_profile("u1")
        self.assertEqual(items, [])

    def test_audit_history(self):
        pid = self.ms.propose("u1", "agent1", "profile", "color", "blue", confidence=0.9)
        self.ms.approve(pid, "u1")
        hist = self.ms.audit_history("u1")
        self.assertTrue(len(hist) >= 2)

    def test_tenant_isolation(self):
        ms2 = MemoryService(db=Database(path=self.path, tenant_id="t2"), tenant_id="t2")
        # t2 db shares same file but different tenant; querying t1 data should be empty
        self.assertEqual(ms2.list_profile("u1"), [])

    def test_expire(self):
        pid = self.ms.propose("u1", "agent1", "profile", "tmp", "val", confidence=0.9, expires_at="2000-01-01T00:00:00+00:00")
        # expire won't affect proposed? expire_proposals targets proposed with past expiry
        n = self.ms.expire_proposals()
        self.assertGreaterEqual(n, 1)


if __name__ == "__main__":
    unittest.main()