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


@unittest.skipUnless(OLLAMA_UP, "Ollama not running — live test skipped")
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


if __name__ == "__main__":
    unittest.main()
