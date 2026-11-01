"""Phase B tests: manifest-scoped memory grounding, proposals, isolation, migration."""
import os
import sqlite3
import tempfile
import unittest

from storage.database import Database
from core.memory import MemoryService
from core.memory_scope import ScopedMemory
from core.model_router import ModelResult
from agents.registry import AgentRegistry

AGENTS_DIR = "/Users/kiarricafavors/personal-ai-team/agents"


def _manifest(reg, name):
    reg.load()
    return reg.get(name)


class TestMemoryScope(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ms = MemoryService(db=self.db, tenant_id="t1")
        self.reg = AgentRegistry(AGENTS_DIR)

    def tearDown(self):
        os.remove(self.path)

    def _seed_profile(self, key, value):
        pid = self.ms.propose("u1", "agent1", "profile", key, value, confidence=0.9)
        self.ms.approve(pid, "u1")

    def test_retrieve_returns_only_manifest_categories(self):
        self._seed_profile("name", "Kia")
        self.ms.set_private("tutor", "u1", "study_note", "likes algebra")
        manifest = _manifest(self.reg, "tutor")  # read = ["profile","goals","notes"]
        sm = ScopedMemory(self.ms, manifest, "tutor", "u1")
        facts = sm.retrieve()
        keys = {f["key"] for f in facts}
        self.assertIn("name", keys)
        self.assertIn("study_note", keys)
        # "goals" deferred: every returned fact is profile or notes
        self.assertTrue(all(f["category"] in ("profile", "notes") for f in facts))

    def test_retrieval_is_audited_without_content(self):
        self._seed_profile("name", "Kia")
        self.ms.set_private("tutor", "u1", "study_note", "likes algebra")
        manifest = _manifest(self.reg, "tutor")
        sm = ScopedMemory(self.ms, manifest, "tutor", "u1")
        sm.retrieve()
        retrievals = [r for r in self.ms.audit_history("u1") if r["action"] == "retrieve"]
        self.assertTrue(retrievals)
        self.assertNotIn("Kia", retrievals[0].get("detail") or "")
        self.assertNotIn("algebra", retrievals[0].get("detail") or "")

    def test_cannot_propose_without_permission(self):
        manifest = _manifest(self.reg, "communications")  # no memory:propose
        sm = ScopedMemory(self.ms, manifest, "communications", "u1")
        with self.assertRaises(PermissionError):
            sm.propose("fact", "x", "y", reason="r")

    def test_propose_requires_permission_and_is_pending(self):
        manifest = _manifest(self.reg, "tutor")
        sm = ScopedMemory(self.ms, manifest, "tutor", "u1")
        pid = sm.propose("fact", "color", "blue", reason="stated preference", context="user said blue")
        self.assertTrue(pid)
        row = self.ms.db.query("SELECT * FROM memory_proposals WHERE id=?", (pid,))[0]
        self.assertEqual(row["status"], "proposed")
        self.assertEqual(row["reason"], "stated preference")
        self.assertEqual(row["context"], "user said blue")
        self.assertEqual(row["agent_id"], "tutor")
        # never auto-committed
        self.assertEqual(self.ms.list_profile("u1"), [])

    def test_notes_are_private_to_owning_agent(self):
        self.ms.set_private("tutor", "u1", "k", "v")
        manifest = _manifest(self.reg, "communications")  # read=["profile"] only
        sm = ScopedMemory(self.ms, manifest, "communications", "u1")
        facts = sm.retrieve()
        self.assertFalse(any(f.get("key") == "k" for f in facts))

    def test_tenant_isolation(self):
        self._seed_profile("name", "Kia")
        ms2 = MemoryService(db=Database(path=self.path, tenant_id="t2"), tenant_id="t2")
        manifest = _manifest(self.reg, "tutor")
        sm2 = ScopedMemory(ms2, manifest, "tutor", "u1")
        self.assertEqual(sm2.retrieve(), [])


class TestAgentGrounding(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ms = MemoryService(db=self.db, tenant_id="t1")
        self.reg = AgentRegistry(AGENTS_DIR)

    def tearDown(self):
        os.remove(self.path)

    def test_ground_separates_facts_from_reply(self):
        pid = self.ms.propose("u1", "agent1", "profile", "name", "Kia", confidence=0.9)
        self.ms.approve(pid, "u1")
        captured = {}

        class FakeRouter:
            def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
                captured["system"] = system
                return ModelResult("generated reply", "ollama", "llama3.1", "local:ollama:llama3.1")

        from agents.tutor.agent import TutorAgent
        agent = TutorAgent(memory=self.ms, router=FakeRouter(), manifest=_manifest(self.reg, "tutor"), user_id="u1")
        res = agent.run("what do you know about me?")

        self.assertEqual(res["reply"], "generated reply")
        self.assertTrue(any(f["key"] == "name" and f["value"] == "Kia" for f in res["facts"]))
        self.assertIn("KNOWN FACTS", captured["system"])
        self.assertIn("name: Kia", captured["system"])
        self.assertIn("inference", captured["system"].lower())

    def test_proposals_created_via_context_are_pending(self):
        class FakeRouter:
            def complete(self, *a, **kw):
                return ModelResult("ok", "ollama", "llama3.1", "local:ollama:llama3.1")

        from agents.tutor.agent import TutorAgent
        agent = TutorAgent(memory=self.ms, router=FakeRouter(), manifest=_manifest(self.reg, "tutor"), user_id="u1")
        ctx = {"memory_proposals": [{"kind": "preference", "key": "color", "value": "blue",
                                     "reason": "stated", "context": "user said blue"}]}
        res = agent.run("remember my color", context=ctx)
        self.assertEqual(len(res["proposals"]), 1)
        row = self.ms.db.query("SELECT * FROM memory_proposals WHERE id=?", (res["proposals"][0],))[0]
        self.assertEqual(row["status"], "proposed")
        self.assertEqual(row["reason"], "stated")
        self.assertEqual(row["context"], "user said blue")

    def test_no_memory_agent_still_generates(self):
        class FakeRouter:
            def complete(self, *a, **kw):
                return ModelResult("ok", "ollama", "llama3.1", "local:ollama:llama3.1")

        from agents.tutor.agent import TutorAgent
        agent = TutorAgent(router=FakeRouter(), manifest=_manifest(self.reg, "tutor"))  # memory=None
        res = agent.run("hi")
        self.assertEqual(res["reply"], "ok")
        self.assertEqual(res["facts"], [])
        self.assertEqual(res["proposals"], [])


class TestProposalApproveReject(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ms = MemoryService(db=self.db, tenant_id="t1")

    def tearDown(self):
        os.remove(self.path)

    def test_approve_reject_with_reason_context(self):
        pid = self.ms.propose("u1", "agent1", "profile", "city", "Oakland",
                              reason="asked", context="user lives in Oakland", confidence=0.9)
        self.ms.reject(pid, "u1")
        self.assertEqual(self.ms.list_proposals("u1", status="rejected")[0]["id"], pid)
        self.assertEqual(self.ms.list_profile("u1"), [])

        pid2 = self.ms.propose("u1", "agent1", "profile", "city", "Oakland",
                              reason="asked", context="user lives in Oakland", confidence=0.9)
        self.ms.approve(pid2, "u1")
        items = self.ms.list_profile("u1")
        self.assertEqual(items[0]["key"], "city")
        self.assertEqual(items[0]["value"], "Oakland")


class TestMigration(unittest.TestCase):
    def test_new_db_has_reason_context_columns(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        db = Database(path=path, tenant_id="t1")
        cols = [r["name"] for r in db.query("PRAGMA table_info(memory_proposals)")]
        self.assertIn("reason", cols)
        self.assertIn("context", cols)
        os.remove(path)

    def test_existing_db_is_migrated_additively(self):
        # Simulate a pre-Phase-B database (old memory_proposals schema, no reason/context).
        old_schema = (
            "CREATE TABLE memory_proposals ("
            "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, agent_id TEXT,"
            "kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, source TEXT,"
            "confidence REAL DEFAULT 0.5, status TEXT NOT NULL DEFAULT 'proposed',"
            "expires_at TEXT, created_at TEXT NOT NULL, decided_at TEXT)"
        )
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        conn = sqlite3.connect(path)
        conn.execute(old_schema)
        conn.commit()
        conn.close()

        db = Database(path=path, tenant_id="t1")  # migrations should add reason/context
        cols = [r["name"] for r in db.query("PRAGMA table_info(memory_proposals)")]
        self.assertIn("reason", cols)
        self.assertIn("context", cols)
        # idempotent: re-open does not error
        Database(path=path, tenant_id="t1")
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
