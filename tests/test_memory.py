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


class TestConversationPair(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ms = MemoryService(db=self.db, tenant_id="t1")
        # ensure thread exists for touch
        self.ms.get_or_create_thread("u1", "thread1", "agent1", "hi")

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _rows(self, turn_id=None):
        if turn_id:
            return self.db.query(
                "SELECT role, content, turn_id, tenant_id, user_id, thread_id FROM conversation_memory WHERE tenant_id=? AND user_id=? AND thread_id=? AND turn_id=?",
                ("t1", "u1", "thread1", turn_id))
        return self.db.query(
            "SELECT role, content FROM conversation_memory WHERE tenant_id=? AND user_id=? AND thread_id=?",
            ("t1", "u1", "thread1"))

    def test_pair_atomic_success(self):
        self.ms.add_conversation_pair("u1", "thread1", "hello", "world", turn_id="t1")
        rows = self._rows("t1")
        self.assertEqual(len(rows), 2)
        roles = {r["role"] for r in rows}
        self.assertEqual(roles, {"user", "assistant"})
        for r in rows:
            self.assertEqual(r["turn_id"], "t1")
            self.assertEqual(r["tenant_id"], "t1")
            self.assertEqual(r["user_id"], "u1")
            self.assertEqual(r["thread_id"], "thread1")
        contents = {r["role"]: r["content"] for r in rows}
        self.assertEqual(contents["user"], "hello")
        self.assertEqual(contents["assistant"], "world")

    def test_pair_rollback_on_second_insert_failure(self):
        import contextlib
        from unittest.mock import patch

        real_tm = self.db.transaction_immediate

        @contextlib.contextmanager
        def patched():
            with real_tm() as c:
                class W:
                    def __init__(self):
                        self._c = c
                        self._n = 0
                    def execute(self, sql, params=()):
                        self._n += 1
                        if self._n == 2:
                            raise RuntimeError("forced failure")
                        return self._c.execute(sql, params)
                    def __getattr__(self, name):
                        return getattr(self._c, name)
                yield W()

        with patch.object(self.db, "transaction_immediate", patched):
            with self.assertRaises(RuntimeError):
                self.ms.add_conversation_pair("u1", "thread1", "hi", "bye", turn_id=None)
        # nothing persisted
        all_rows = self.db.query(
            "SELECT * FROM conversation_memory WHERE tenant_id=? AND user_id=? AND thread_id=?",
            ("t1", "u1", "thread1"))
        self.assertEqual(len(all_rows), 0)

    def test_pair_duplicate_completed_is_idempotent(self):
        self.ms.add_conversation_pair("u1", "thread1", "hello", "world", turn_id="dup1")
        self.ms.add_conversation_pair("u1", "thread1", "hello", "world", turn_id="dup1")
        rows = self._rows("dup1")
        self.assertEqual(len(rows), 2)

    def test_pair_partial_detected(self):
        # insert only assistant row manually for turn_id partial1
        self.db.execute(
            "INSERT INTO conversation_memory (id,tenant_id,user_id,thread_id,role,content,created_at,turn_id) VALUES (?,?,?,?,?,?,?,?)",
            ("a1", "t1", "u1", "thread1", "assistant", "world", __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(), "partial1"))
        with self.assertRaises(RuntimeError):
            self.ms.add_conversation_pair("u1", "thread1", "hello", "world", turn_id="partial1")
        # still only one row
        rows = self._rows("partial1")
        self.assertEqual(len(rows), 1)

    def test_pair_conflicting_content_rejected(self):
        self.ms.add_conversation_pair("u1", "thread1", "hello", "world", turn_id="conf1")
        with self.assertRaises(RuntimeError):
            self.ms.add_conversation_pair("u1", "thread1", "different", "world", turn_id="conf1")
        # original unchanged
        rows = self._rows("conf1")
        self.assertEqual(len(rows), 2)
        contents = {r["role"]: r["content"] for r in rows}
        self.assertEqual(contents["user"], "hello")

    def test_pair_tenant_isolation(self):
        ms2 = MemoryService(db=Database(path=self.path, tenant_id="t2"), tenant_id="t2")
        # t2 cannot see t1's thread rows via its own memory service query path; just ensure insert scoped
        self.ms.add_conversation_pair("u1", "thread1", "hi", "yo", turn_id="iso1")
        t2_rows = self.db.query(
            "SELECT * FROM conversation_memory WHERE tenant_id=?", ("t2",))
        self.assertEqual(len(t2_rows), 0)

    def test_pair_no_turn_id_inserts(self):
        self.ms.add_conversation_pair("u1", "thread1", "a", "b", turn_id=None)
        rows = self.db.query(
            "SELECT * FROM conversation_memory WHERE tenant_id=? AND user_id=? AND thread_id=?",
            ("t1", "u1", "thread1"))
        self.assertEqual(len(rows), 2)

    def test_pair_thread_ownership_not_violated(self):
        # foreign user u2 owns thread_foreign
        ms2 = MemoryService(db=self.db, tenant_id="t1")
        ms2.get_or_create_thread("u2", "thread_foreign", "agent1", "hi")
        before = self.db.query(
            "SELECT updated_at FROM conversation_threads WHERE thread_id=? AND tenant_id=? AND user_id=?",
            ("thread_foreign", "t1", "u2"))[0]["updated_at"]
        # u1 attempts to persist into u2's thread id
        self.ms.add_conversation_pair("u1", "thread_foreign", "x", "y", turn_id="own1")
        # rows are scoped to u1, not u2
        u2_rows = self.db.query(
            "SELECT * FROM conversation_memory WHERE tenant_id=? AND user_id=? AND thread_id=?",
            ("t1", "u2", "thread_foreign"))
        self.assertEqual(len(u2_rows), 0)
        u1_rows = self.db.query(
            "SELECT * FROM conversation_memory WHERE tenant_id=? AND user_id=? AND thread_id=?",
            ("t1", "u1", "thread_foreign"))
        self.assertEqual(len(u1_rows), 2)
        # foreign thread activity timestamp unchanged
        after = self.db.query(
            "SELECT updated_at FROM conversation_threads WHERE thread_id=? AND tenant_id=? AND user_id=?",
            ("thread_foreign", "t1", "u2"))[0]["updated_at"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()