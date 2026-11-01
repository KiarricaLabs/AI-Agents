"""Conversational-memory tests: persistence, grounding, isolation, and failure handling.

Uses a mocked ModelRouter so the assertions are deterministic; a separate live
two-turn test lives in tests/test_m8_live.py.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token
from core.model_router import ModelResult


class _CaptureRouter:
    def __init__(self):
        self.calls = []

    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        self.calls.append({"system": system, "prompt": prompt, "context": context})
        return ModelResult("ok reply", "ollama", "llama3.1", "local:ollama:llama3.1")


class TestConversationMemory(unittest.TestCase):
    @patch("core.runtime.ModelRouter")
    def test_two_turn_history_is_grounded(self, MockRouter):
        cap = _CaptureRouter()
        MockRouter.return_value = cap
        c = TestClient(app)
        tok = issue_token("ua", "m9A", "admin")

        r1 = c.post("/agents/tutor/run", json={"task": "my brand is Acme"}, headers={"x-token": tok})
        self.assertEqual(r1.status_code, 200)
        tid = r1.json()["thread_id"]
        self.assertEqual(r1.json()["context_messages"], 0)

        r2 = c.post("/agents/tutor/run",
                    json={"task": "what is my brand?", "thread_id": tid},
                    headers={"x-token": tok})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["context_messages"], 2)

        # The second turn's system prompt must carry the first exchange.
        sys2 = cap.calls[-1]["system"]
        self.assertIn("untrusted context", sys2)
        self.assertIn("my brand is Acme", sys2)

    @patch("core.runtime.ModelRouter")
    def test_new_thread_has_no_history(self, MockRouter):
        cap = _CaptureRouter()
        MockRouter.return_value = cap
        c = TestClient(app)
        tok = issue_token("ua", "m9B", "admin")

        r = c.post("/agents/tutor/run", json={"task": "hello"}, headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["context_messages"], 0)
        self.assertNotIn("untrusted context", cap.calls[0]["system"])

    @patch("core.runtime.ModelRouter")
    def test_cross_user_thread_isolation(self, MockRouter):
        cap = _CaptureRouter()
        MockRouter.return_value = cap
        c = TestClient(app)
        ta = issue_token("ua", "m9C", "admin")
        tb = issue_token("ub", "m9C", "admin")

        ra = c.post("/agents/tutor/run", json={"task": "secret-a"}, headers={"x-token": ta})
        tid = ra.json()["thread_id"]

        rb = c.post("/agents/tutor/run",
                    json={"task": "what did A say?", "thread_id": tid},
                    headers={"x-token": tb})
        self.assertEqual(rb.status_code, 200)
        self.assertEqual(rb.json()["context_messages"], 0)
        self.assertNotIn("secret-a", cap.calls[-1]["system"])

    @patch("core.runtime.ModelRouter")
    def test_cross_tenant_thread_isolation(self, MockRouter):
        cap = _CaptureRouter()
        MockRouter.return_value = cap
        c = TestClient(app)
        ta = issue_token("ua", "m9D", "admin")
        tb = issue_token("ub", "m9E", "admin")

        ra = c.post("/agents/tutor/run", json={"task": "tenant-d-secret"}, headers={"x-token": ta})
        tid = ra.json()["thread_id"]

        rb = c.post("/agents/tutor/run",
                    json={"task": "x", "thread_id": tid},
                    headers={"x-token": tb})
        self.assertEqual(rb.status_code, 200)
        self.assertEqual(rb.json()["context_messages"], 0)
        self.assertNotIn("tenant-d-secret", cap.calls[-1]["system"])

    @patch("core.runtime.ModelRouter")
    def test_history_window_is_capped(self, MockRouter):
        cap = _CaptureRouter()
        MockRouter.return_value = cap
        c = TestClient(app)
        tok = issue_token("ua", "m9G", "admin")

        tid = None
        for i in range(7):
            body = {"task": f"turn msg {i}"}
            if tid:
                body["thread_id"] = tid
            r = c.post("/agents/tutor/run", json=body, headers={"x-token": tok})
            self.assertEqual(r.status_code, 200)
            tid = r.json()["thread_id"]

        # 14 prior messages exist; only the last 12 are injected.
        r8 = c.post("/agents/tutor/run",
                    json={"task": "final", "thread_id": tid},
                    headers={"x-token": tok})
        self.assertEqual(r8.status_code, 200)
        self.assertEqual(r8.json()["context_messages"], 12)
        sys = cap.calls[-1]["system"]
        self.assertNotIn("turn msg 0", sys)   # oldest dropped
        self.assertIn("turn msg 6", sys)      # most recent kept

    @patch("core.runtime.ModelRouter")
    def test_persistence_failure_still_returns_reply(self, MockRouter):
        MockRouter.return_value = _CaptureRouter()
        c = TestClient(app)
        tok = issue_token("ua", "m9H", "admin")

        with patch("core.memory.MemoryService.add_conversation", side_effect=Exception("disk full")):
            r = c.post("/agents/tutor/run", json={"task": "hello"}, headers={"x-token": tok})

        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["reply"], "ok reply")
        self.assertIn("history_warning", body)


if __name__ == "__main__":
    unittest.main()
