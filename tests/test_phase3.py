import os, tempfile, unittest
from storage.database import Database
from core.memory import MemoryService
from core.memory_analytics import MemoryAnalytics
from storage.postgres import AVAILABLE


class TestPhase3(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ms = MemoryService(db=self.db, tenant_id="t1")
        self.ma = MemoryAnalytics(db=self.db, tenant_id="t1")

    def tearDown(self):
        try: os.remove(self.path)
        except OSError: pass

    def test_analytics_empty_safe(self):
        stats = self.ma.usage_stats("u1")
        self.assertEqual(stats["profile_count"], 0)
        rates = self.ma.proposal_rates("u1")
        self.assertEqual(rates["total"], 0)
        self.assertEqual(rates["approval_rate"], 0.0)

    def test_analytics_aggregates(self):
        self.ms.propose("u1", "a1", "profile", "k", "v", confidence=0.9)
        stats = self.ma.usage_stats("u1")
        self.assertEqual(stats["profile_count"], 0)  # not approved yet
        rates = self.ma.proposal_rates("u1")
        self.assertEqual(rates["total"], 1)

    def test_no_content_leak(self):
        self.ms.propose("u1", "a1", "profile", "note", "hello123", confidence=0.9)
        stats = self.ma.usage_stats("u1")
        # stats should not contain the secret value
        self.assertNotIn("mypassword123", str(stats))

    def test_cross_tenant_analytics(self):
        ma2 = MemoryAnalytics(db=Database(path=self.path, tenant_id="t2"), tenant_id="t2")
        self.assertEqual(ma2.usage_stats("u1")["profile_count"], 0)

    def test_postgres_graceful_if_missing(self):
        if AVAILABLE:
            self.skipTest("psycopg available")
        from storage.postgres import PostgresDatabase
        with self.assertRaises(RuntimeError):
            PostgresDatabase("postgresql://localhost/test")


if __name__ == "__main__":
    unittest.main()