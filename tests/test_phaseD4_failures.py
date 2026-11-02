"""M10 Phase D4.2 — graceful AI generation failure handling.

Covers the normalized failure taxonomy and how the API/agents surface failures:

- Ollama unavailable / connection refused / timeout  -> model_unavailable
- Empty/whitespace model output                       -> model_empty
- Memory/brand retrieval failure                      -> memory_error (never invents)
- Failed ordinary generation returns a truthful, non-blank reply + marker
- Failed user + assistant turns are persisted (conversation preserved)
- Human-triggered retry does NOT duplicate the user message or consequential work
- Structured/proposal fallback and validation/secret rejection stay intact
- Model health endpoint is read-only and does not mutate state
- Errors are sanitized (no raw exception internals surfaced)

All tests use the isolated test database (set by tests/__init__.py); the
production DB is never opened.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from config.settings import DB_PATH
from storage.database import Database
from core.errors import (
    ModelUnavailableError,
    ModelEmptyOutputError,
    MemoryRetrievalError,
)
from core.model_router import ModelRouter, ModelResult
from agents.base import BaseAgent, FALLBACK_REPLY, _MEMORY_UNAVAILABLE_NOTE
from api.app import app


# ---------------------------------------------------------------------------
# Unit tests: ModelRouter failure taxonomy
# ---------------------------------------------------------------------------
class TestModelRouterFailures(unittest.TestCase):
    def test_unavailable_after_retries(self):
        router = ModelRouter(retries=2)
        def fail(m, p, s):
            raise OSError("down")
        with patch.object(router, "_generate_once", side_effect=fail):
            with self.assertRaises(ModelUnavailableError) as ctx:
                router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})
        self.assertIn("2 attempts", str(ctx.exception))

    def test_connection_refused_is_unavailable(self):
        router = ModelRouter(retries=1)
        def fail(m, p, s):
            raise OSError("Connection refused")
        with patch.object(router, "_generate_once", side_effect=fail):
            with self.assertRaises(ModelUnavailableError):
                router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})

    def test_timeout_is_unavailable(self):
        router = ModelRouter(retries=1)
        def fail(m, p, s):
            raise TimeoutError("timed out")
        with patch.object(router, "_generate_once", side_effect=fail):
            with self.assertRaises(ModelUnavailableError):
                router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})

    def test_empty_output_is_model_empty(self):
        router = ModelRouter(retries=2)
        with patch.object(router, "_generate_once", side_effect=lambda m, p, s: ""):
            with self.assertRaises(ModelEmptyOutputError):
                router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})

    def test_whitespace_output_is_model_empty(self):
        router = ModelRouter(retries=2)
        with patch.object(router, "_generate_once", side_effect=lambda m, p, s: "  \n \t "):
            with self.assertRaises(ModelEmptyOutputError):
                router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})

    def test_error_message_is_sanitized(self):
        # No raw host/connection detail is embedded in the raised message.
        router = ModelRouter(retries=1)
        def fail(m, p, s):
            raise OSError("localhost:11434 refused")
        with patch.object(router, "_generate_once", side_effect=fail):
            try:
                router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})
                self.fail("expected ModelUnavailableError")
            except ModelUnavailableError as e:
                msg = str(e)
                self.assertNotIn("11434", msg)
                self.assertNotIn("localhost", msg)
                self.assertIn("attempt", msg)

    def test_health_up(self):
        with patch("core.llm_client.LLMClient.ping", return_value=True):
            info = ModelRouter(timeout=120).check_availability()
        self.assertTrue(info["ok"])
        self.assertTrue(info["available"])
        self.assertEqual(info["code"], "ok")
        self.assertEqual(info["provider"], "ollama")

    def test_health_down(self):
        def boom(*a, **k):
            raise OSError("refused")

        with patch("core.llm_client.LLMClient.ping", side_effect=boom):
            info = ModelRouter(timeout=120).check_availability()
        self.assertFalse(info["ok"])
        self.assertTrue(info["available"] is False)
        self.assertEqual(info["code"], "model_unavailable")
        self.assertNotIn("refused", str(info))


# ---------------------------------------------------------------------------
# Agent layer: ordinary-path generation failure behavior
# ---------------------------------------------------------------------------
class _UnavailableRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None, json_format=False):
        raise ModelUnavailableError("down")

    def check_availability(self):
        return {"ok": False, "available": False, "provider": "ollama",
                "model": "m", "location": "local:ollama:m", "code": "model_unavailable"}


class _EmptyRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None, json_format=False):
        raise ModelEmptyOutputError("empty")


class _GoodRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None, json_format=False):
        return ModelResult("all good", "ollama", "llama3.1", "local:ollama:llama3.1")


class TestAgentGenerationFailures(unittest.TestCase):
    def _agent(self, router):
        return BaseAgent(memory=None, router=router, manifest={"identity": {"role": "tutor"}})

    def test_unavailable_surfaces_marker(self):
        # BaseAgent._generate turns the exception into a marked failure result.
        agent = self._agent(_UnavailableRouter())
        mr = agent._generate("hi")
        self.assertEqual(mr.generation_error["code"], "model_unavailable")
        self.assertTrue(mr.generation_error["retryable"])
        self.assertTrue(mr.text.strip())
        self.assertIn("didn't", mr.text)

    def test_empty_surfaces_marker(self):
        agent = self._agent(_EmptyRouter())
        mr = agent._generate("hi")
        self.assertEqual(mr.generation_error["code"], "model_empty")
        self.assertTrue(mr.text.strip())

    def test_ground_ordinary_unavailable_attaches_marker(self):
        agent = self._agent(_UnavailableRouter())
        out = agent._ground("hi")
        self.assertEqual(out.get("generation_error", {}).get("code"), "model_unavailable")
        self.assertTrue(out["reply"].strip())
        self.assertNotEqual(out["reply"], "")  # never a blank success

    def _tmp_memory(self):
        import os
        import tempfile
        from core.memory import MemoryService
        fd2, path = tempfile.mkstemp(suffix=".db")
        os.close(fd2)
        os.remove(path)
        mem = MemoryService(Database(path=path, tenant_id="local"), tenant_id="local")
        return path, mem

    def test_memory_failure_never_invents_and_notes_it(self):
        import os
        from core.memory_scope import ScopedMemory
        path, mem = self._tmp_memory()
        try:
            agent = BaseAgent(memory=mem, user_id="u1", router=_GoodRouter(),
                              manifest={"identity": {"role": "tutor"}})
            with patch.object(ScopedMemory, "retrieve", side_effect=MemoryRetrievalError("nope")):
                out = agent._ground("hi")
        finally:
            for s in (path, path + "-wal", path + "-shm"):
                if os.path.exists(s):
                    os.remove(s)
        self.assertEqual(out.get("generation_error", {}).get("code"), "memory_error")
        self.assertEqual(out["facts"], [])           # do not invent memory
        self.assertIn("saved context", out["reply"])  # note appended
        self.assertIn(_MEMORY_UNAVAILABLE_NOTE, out["reply"])

    def test_denied_memory_proposal_propagates_permission_error(self):
        # M1: a manifest-denied memory proposal is an authorization denial and must
        # NOT be masked as a graceful memory failure (HTTP 200).
        path, mem = self._tmp_memory()
        import os
        try:
            # Manifest has no "memory:propose" permission.
            agent = BaseAgent(memory=mem, user_id="u1", router=_GoodRouter(),
                              manifest={"identity": {"role": "tutor"}})
            ctx = {"thread_id": "t1", "memory_proposals": [
                {"kind": "fact", "key": "k", "value": "v", "confidence": 0.5}]}
            with self.assertRaises(PermissionError):
                agent._ground("hi", context=ctx)
        finally:
            for s in (path, path + "-wal", path + "-shm"):
                if os.path.exists(s):
                    os.remove(s)

    def test_permitted_memory_proposal_still_works(self):
        # M1: a permitted memory proposal still completes normally (no masking,
        # no false authorization denial).
        path, mem = self._tmp_memory()
        import os
        try:
            manifest = {"identity": {"role": "tutor"},
                        "permissions": ["memory:propose"],
                        "memory": {"write": ["profile"]}}
            agent = BaseAgent(memory=mem, user_id="u1", router=_GoodRouter(),
                              manifest=manifest)
            ctx = {"thread_id": "t1", "memory_proposals": [
                {"kind": "fact", "key": "topic", "value": "ok", "confidence": 0.5}]}
            out = agent._ground("hi", context=ctx)
            self.assertTrue(out["proposals"], "permitted proposal should produce a proposal id")
        finally:
            for s in (path, path + "-wal", path + "-shm"):
                if os.path.exists(s):
                    os.remove(s)

    def test_structured_fallback_on_model_failure(self):
        agent = self._agent(_UnavailableRouter())
        out = agent._generate_structured("capture", context={"thread_id": "t1"})
        self.assertEqual(out.get("generation_error", {}).get("code"), "model_unavailable")
        self.assertEqual(out["reply"], FALLBACK_REPLY)  # existing fallback preserved
        self.assertEqual(out["proposal_ids"], [])


# ---------------------------------------------------------------------------
# API integration tests (isolated DB)
# ---------------------------------------------------------------------------
class TestApiFailures(unittest.TestCase):
    def _db(self):
        return Database(path=DB_PATH, tenant_id="local")

    def _ws_counts(self):
        db = self._db()
        return {t: db.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]
                for t in ("goals", "assignments", "work_proposals")}

    def _assert_ws_unchanged(self, before):
        after = self._ws_counts()
        self.assertEqual(after, before, "workspace tables must be unchanged")

    def _conv(self):
        db = Database(path=DB_PATH, tenant_id="local")
        return db.query("SELECT * FROM conversation_memory")

    def _conv_count(self):
        return len(self._conv())

    def test_failed_ordinary_generation_is_honest_and_persisted(self):
        with patch("core.runtime.ModelRouter", return_value=_UnavailableRouter()):
            c = TestClient(app)
            r = c.post("/agents/tutor/run", json={"task": "create a goal"})
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual(b["generation_error"]["code"], "model_unavailable")
        self.assertTrue(b["reply"].strip())
        # no false completion claim
        self.assertNotIn("created", b["reply"].lower())
        # failed user + assistant turns persisted for this thread
        tid = b["thread_id"]
        rows = [x for x in self._conv() if x.get("thread_id") == tid]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["role"], "user")
        self.assertEqual(rows[0]["content"], "create a goal")
        self.assertEqual(rows[1]["role"], "assistant")

    def test_empty_generation_is_not_blank_success(self):
        with patch("core.runtime.ModelRouter", return_value=_EmptyRouter()):
            c = TestClient(app)
            r = c.post("/agents/tutor/run", json={"task": "hi"})
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual(b["generation_error"]["code"], "model_empty")
        self.assertNotEqual(b["reply"], "")

    def test_failed_turn_creates_no_workspace_records(self):
        before = self._ws_counts()
        with patch("core.runtime.ModelRouter", return_value=_UnavailableRouter()):
            c = TestClient(app)
            c.post("/agents/tutor/run", json={"task": "add a goal"})
        self._assert_ws_unchanged(before)

    def test_retry_does_not_duplicate_user_message_or_work(self):
        before = self._ws_counts()
        class _Seq:
            def __init__(self):
                self.n = 0

            def complete(self, agent_id, prompt, system="", model_spec=None, context=None, json_format=False):
                self.n += 1
                if self.n == 1:
                    raise ModelUnavailableError("down")
                return ModelResult("recovered", "ollama", "llama3.1", "local:ollama:llama3.1")

        seq = _Seq()
        with patch("core.runtime.ModelRouter", return_value=seq):
            c = TestClient(app)
            r1 = c.post("/agents/tutor/run", json={"task": "tell me about x"})
            tid = r1.json()["thread_id"]
            r2 = c.post("/agents/tutor/run",
                        json={"task": "tell me about x", "thread_id": tid, "retry": True})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["reply"], "recovered")
        # exactly one user message for this task, plus failure + success assistant rows
        rows = [x for x in self._conv() if x.get("thread_id") == tid]
        user_msgs = [x for x in rows if x.get("role") == "user"]
        self.assertEqual(len(user_msgs), 1)
        self.assertEqual(user_msgs[0]["content"], "tell me about x")
        # no workspace records created by the retry
        self._assert_ws_unchanged(before)

    def test_retry_fallback_when_no_prior_user_message(self):
        # retry=true but no prior user message for this task -> normal persistence
        with patch("core.runtime.ModelRouter", return_value=_GoodRouter()):
            c = TestClient(app)
            r = c.post("/agents/tutor/run",
                       json={"task": "unique task", "thread_id": "t-nonexistent", "retry": True})
        self.assertEqual(r.status_code, 200)
        # still persists a user message (safe fallback, no accidental loss)
        rows = [x for x in self._conv() if x.get("thread_id") == "t-nonexistent"]
        self.assertGreaterEqual(len(rows), 1)

    def test_memory_retrieval_failure_is_safe_via_api(self):
        from core.memory_scope import ScopedMemory
        with patch("core.runtime.ModelRouter", return_value=_GoodRouter()), \
             patch.object(ScopedMemory, "retrieve", side_effect=MemoryRetrievalError("boom")):
            c = TestClient(app)
            r = c.post("/agents/tutor/run", json={"task": "hi"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["generation_error"]["code"], "memory_error")
        self.assertIn("saved context", r.json()["reply"])

    def test_history_warning_is_nonfatal(self):
        # Persistence failure must not drop a successful reply.
        with patch("core.runtime.ModelRouter", return_value=_GoodRouter()), \
             patch("core.memory.MemoryService.add_conversation", side_effect=RuntimeError("disk")), \
             patch("core.memory.MemoryService.touch_thread"), \
             patch("core.memory.MemoryService.get_or_create_thread"):
            c = TestClient(app)
            r = c.post("/agents/tutor/run", json={"task": "hi"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reply"], "all good")
        self.assertIn("history_warning", r.json())

    def test_model_health_is_read_only(self):
        db = Database(path=DB_PATH, tenant_id="local")
        before = db.query("SELECT COUNT(*) AS n FROM conversation_memory")[0]["n"]
        ws_before = self._ws_counts()
        with patch("core.model_router.ModelRouter.check_availability",
                   return_value={"ok": True, "available": True, "provider": "ollama",
                                 "model": "m", "location": "local:ollama:m", "code": "ok"}):
            r = TestClient(app).get("/agents/model-health")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertTrue(b["backend"]["ok"])
        self.assertTrue(b["model"]["ok"])
        # no workspace/conversation mutation: counts unchanged by the probe
        after = db.query("SELECT COUNT(*) AS n FROM conversation_memory")[0]["n"]
        self.assertEqual(after, before)
        self._assert_ws_unchanged(ws_before)

    def test_model_health_down_is_safe(self):
        with patch("core.model_router.ModelRouter.check_availability",
                   return_value={"ok": False, "available": False, "provider": "ollama",
                                 "model": "m", "location": "local:ollama:m",
                                 "code": "model_unavailable"}):
            r = TestClient(app).get("/agents/model-health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["model"]["code"], "model_unavailable")


if __name__ == "__main__":
    unittest.main()
