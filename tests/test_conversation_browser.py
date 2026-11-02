"""Persistent Chat History & Conversation Browser — backend tests.

Covers thread list unification (incl. legacy 'Agent unknown'), rename persistence
(never overwritten by auto-titles or touches), full transcripts (not the 12-message
context window), tenant/user isolation, and the browser/rename endpoints.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from storage.database import Database
from core.memory import MemoryService
from core.auth import issue_token
from fastapi.testclient import TestClient
from api.app import app


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


class TestThreadMetadata(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="local")
        self.svc = MemoryService(db=self.db, tenant_id="local")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)

    def test_list_unifies_legacy_and_attributed_threads(self):
        u = "u1"
        self.svc.add_conversation(u, "grow my business", "user", "tA")
        self.svc.add_conversation(u, "plan", "assistant", "tA")
        self.svc.get_or_create_thread(u, "tA", "strategist", "grow my business")
        self.svc.add_conversation(u, "legacy hi", "user", "tB")
        self.svc.add_conversation(u, "legacy reply", "assistant", "tB")

        threads = {c["thread_id"]: c for c in self.svc.list_threads(u)}
        self.assertEqual(threads["tA"]["agent_id"], "strategist")
        self.assertEqual(threads["tA"]["title"], "grow my business")
        self.assertEqual(threads["tB"]["agent_id"], None)  # => 'Agent unknown'
        self.assertEqual(threads["tB"]["title"], "legacy hi")
        self.assertEqual(threads["tB"]["message_count"], 2)

    def test_rename_persists_and_is_never_overwritten(self):
        u = "u1"
        self.svc.add_conversation(u, "autotitle", "user", "t3")
        self.svc.add_conversation(u, "reply", "assistant", "t3")
        self.svc.get_or_create_thread(u, "t3", "tutor", "autotitle")
        self.svc.rename_thread(u, "t3", "My Renamed Convo")
        self.svc.get_or_create_thread(u, "t3", "tutor", "must not overwrite")
        self.svc.touch_thread(u, "t3")
        t3 = [c for c in self.svc.list_threads(u) if c["thread_id"] == "t3"][0]
        self.assertEqual(t3["title"], "My Renamed Convo")
        self.assertTrue(t3["is_renamed"])
        self.assertEqual(t3["agent_id"], "tutor")

    def test_full_transcript_not_limited_to_context_window(self):
        u = "u1"
        for i in range(15):
            self.svc.add_conversation(u, f"m{i}", "user", "t4")
            self.svc.add_conversation(u, f"r{i}", "assistant", "t4")
        tr = self.svc.list_conversation(u, "t4")
        self.assertEqual(len(tr), 30)  # well beyond HISTORY_WINDOW(12)

    def test_tenant_user_isolation_within_service(self):
        svcA = MemoryService(db=self.db, tenant_id="tenantA")
        svcB = MemoryService(db=self.db, tenant_id="tenantB")
        svcA.add_conversation("ua", "secret A", "user", "tX")
        svcA.get_or_create_thread("ua", "tX", "strategist", "secret A")
        svcB.add_conversation("ub", "secret B", "user", "tY")
        # B cannot list A's user/thread; A only sees its own.
        self.assertEqual(svcB.list_threads("ua"), [])
        namesA = {c["thread_id"] for c in svcA.list_threads("ua")}
        self.assertEqual(namesA, {"tX"})


class TestBrowserEndpoints(unittest.TestCase):
    def _headers(self, tenant="local", user="u1"):
        return {"x-token": issue_token(user, tenant, "admin")}

    def _seed_thread(self, thread_id, title, user="u1", tenant="local"):
        from config.settings import DB_PATH, DEFAULT_TENANT
        db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        svc = MemoryService(db=db, tenant_id=tenant)
        svc.add_conversation(user, title, "user", thread_id)
        svc.add_conversation(user, "reply", "assistant", thread_id)
        svc.get_or_create_thread(user, thread_id, "tutor", title)

    def test_list_via_endpoint(self):
        c = TestClient(app)
        r = c.get("/memory/conversations", headers=self._headers())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("items", body)
        for item in body["items"]:
            self.assertTrue({"thread_id", "agent_id", "title", "last_activity"} <= set(item))

    def test_rename_nonexistent_thread_returns_404(self):
        # Renaming a thread that does not exist must not return successful ok:true.
        c = TestClient(app)
        r = c.patch("/memory/conversations/does-not-exist", json={"title": "Renamed"}, headers=self._headers())
        self.assertEqual(r.status_code, 404)

    def test_rename_owned_thread_success(self):
        c = TestClient(app)
        self._seed_thread("ownedT", "seed title")
        r = c.patch("/memory/conversations/ownedT", json={"title": "My Title"}, headers=self._headers())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("ok"), True)
        from config.settings import DB_PATH, DEFAULT_TENANT
        db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        svc = MemoryService(db=db, tenant_id="local")
        t = [x for x in svc.list_threads("u1") if x["thread_id"] == "ownedT"][0]
        self.assertEqual(t["title"], "My Title")
        self.assertTrue(t["is_renamed"])


class TestBrowserIsolationEndpoints(unittest.TestCase):
    """Endpoint-boundary isolation: identity comes from the token; a user/tenant
    must not list or rename another user's/tenant's conversations, and a 404 must
    not reveal whether a foreign thread exists."""

    TENANT = "convbrowse"
    OWNER = "owner"
    INTRUDER = "intruder"

    @classmethod
    def setUpClass(cls):
        from config.settings import DB_PATH, DEFAULT_TENANT
        db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        svc = MemoryService(db=db, tenant_id=cls.TENANT)
        svc.add_conversation(cls.OWNER, "private goal", "user", "privT")
        svc.add_conversation(cls.OWNER, "reply", "assistant", "privT")
        svc.get_or_create_thread(cls.OWNER, "privT", "strategist", "private goal")

    def _h(self, user, tenant=None):
        return {"x-token": issue_token(user, tenant or self.TENANT, "admin")}

    def test_owner_lists_own_conversation(self):
        c = TestClient(app)
        items = c.get("/memory/conversations", headers=self._h(self.OWNER)).json()["items"]
        self.assertIn("privT", {x["thread_id"] for x in items})

    def test_cannot_list_another_users_conversations(self):
        c = TestClient(app)
        items = c.get("/memory/conversations", headers=self._h(self.INTRUDER)).json()["items"]
        self.assertNotIn("privT", {x["thread_id"] for x in items})

    def test_cannot_rename_another_users_thread(self):
        c = TestClient(app)
        r = c.patch("/memory/conversations/privT", json={"title": "nope"}, headers=self._h(self.INTRUDER))
        self.assertEqual(r.status_code, 404)

    def test_cross_tenant_cannot_list_or_rename(self):
        c = TestClient(app)
        r_list = c.get("/memory/conversations", headers=self._h(self.OWNER, tenant="othert"))
        tids = {x["thread_id"] for x in r_list.json()["items"]}
        self.assertNotIn("privT", tids)
        r = c.patch("/memory/conversations/privT", json={"title": "x"}, headers=self._h(self.OWNER, tenant="othert"))
        self.assertEqual(r.status_code, 404)

    def test_nonexistent_and_unauthorized_both_404_no_leak(self):
        c = TestClient(app)
        a = c.patch("/memory/conversations/ghost", json={"title": "x"}, headers=self._h(self.OWNER))
        b = c.patch("/memory/conversations/privT", json={"title": "x"}, headers=self._h(self.INTRUDER))
        self.assertEqual(a.status_code, 404)
        self.assertEqual(b.status_code, 404)
        # The thread must be untouched after the unauthorized attempt.
        from config.settings import DB_PATH, DEFAULT_TENANT
        db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        svc = MemoryService(db=db, tenant_id=self.TENANT)
        t = [x for x in svc.list_threads(self.OWNER) if x["thread_id"] == "privT"][0]
        self.assertEqual(t["title"], "private goal")


if __name__ == "__main__":
    unittest.main()
