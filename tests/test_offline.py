import os
import tempfile
import unittest

os.environ.setdefault("PAT_AI_PROVIDER", "ollama")
os.environ.setdefault("PAT_MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")


class TestOfflineSmoke(unittest.TestCase):
    def test_settings_load(self):
        from config import settings
        self.assertEqual(settings.AI_PROVIDER, "ollama")

    def test_db_init(self):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        from storage.database import Database
        db = Database(path=path)
        self.assertIsNotNone(db)
        os.remove(path)

    def test_llm_client_no_cloud(self):
        from core.llm_client import build_client
        c = build_client(provider="ollama")
        self.assertEqual(c.provider, "ollama")


if __name__ == "__main__":
    unittest.main()