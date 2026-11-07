"""Live (real Ollama) smoke tests for the six agents.

These are INTENTIONALLY separate from mocked tests. They run the actual
ModelRouter -> Ollama path and are skipped automatically when Ollama is
unavailable. Run manually with:

    python -m unittest tests.test_m8_live -v
"""
import os
import tempfile
import unittest
import urllib.request

from storage.database import Database
from core.runtime import build_runtime

AGENTS = ["tutor", "strategist", "executive_assistant",
          "communications", "soundboard", "workspace_architect"]


def _ollama_up() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        return True
    except Exception:
        return False


OLLAMA_UP = _ollama_up()

# Live-Ollama smoke tests are opt-in (PAT_RUN_LIVE_TESTS=1) so the default suite
# stays deterministic and fast: they dispatch to the real, slow local model and
# are meant to be run on demand with `python -m unittest tests.test_m8_live`.
_LIVE_OK = os.getenv("PAT_RUN_LIVE_TESTS", "").strip().lower() in ("1", "true", "yes")
_SKIP_REASON = "live-Ollama smoke tests are opt-in (set PAT_RUN_LIVE_TESTS=1)"


@unittest.skipUnless(OLLAMA_UP and _LIVE_OK, f"Ollama unavailable or {_SKIP_REASON}")
class TestLiveAgents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(cls.path)
        cls.db = Database(path=cls.path, tenant_id="local")

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.path)
        except OSError:
            pass

    def test_all_six_agents_live(self):
        orch = build_runtime(self.db, "local", "local")
        for name in AGENTS:
            with self.subTest(agent=name):
                r = orch.dispatch(name, "Reply with one short sentence.")
                self.assertIsInstance(r["reply"], str)
                self.assertTrue(r["reply"].strip(), f"{name} returned an empty reply")
                self.assertEqual(r["location"], "local:ollama:llama3.1")


@unittest.skipUnless(OLLAMA_UP and _LIVE_OK, f"Ollama unavailable or {_SKIP_REASON}")
class TestLiveConversation(unittest.TestCase):
    def test_two_turn_conversation_live(self):
        """Real two-turn conversation through the actual HTTP router (Ollama)."""
        import uuid
        from fastapi.testclient import TestClient
        from api.app import app
        from core.auth import issue_token

        c = TestClient(app)
        tenant = f"liveconv-{uuid.uuid4().hex[:8]}"
        tok = issue_token("u1", tenant, "admin")

        r1 = c.post("/agents/tutor/run",
                    json={"task": "Remember that my favorite fruit is mango."},
                    headers={"x-token": tok})
        self.assertEqual(r1.status_code, 200)
        tid = r1.json()["thread_id"]
        self.assertEqual(r1.json()["context_messages"], 0)

        r2 = c.post("/agents/tutor/run",
                    json={"task": "What is my favorite fruit?", "thread_id": tid},
                    headers={"x-token": tok})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["context_messages"], 2)
        self.assertTrue(r2.json()["reply"].strip())
        self.assertEqual(r2.json()["location"], "local:ollama:llama3.1")


if __name__ == "__main__":
    unittest.main()
