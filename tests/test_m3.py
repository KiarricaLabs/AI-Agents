import os, tempfile, unittest, json
from storage.database import Database
from core.tasks import TaskService


class TestM3(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ts = TaskService(db=self.db, tenant_id="t1", user_id="u1", executor=lambda a, p: {"done": True})

    def tearDown(self):
        try: os.remove(self.path)
        except OSError: pass

    def test_create_and_run(self):
        tid = self.ts.create("tutor", {"msg": "hi"})
        res = self.ts.run(tid)
        self.assertTrue(res["ok"])
        t = self.ts.get(tid)
        self.assertEqual(t["status"], "done")

    def test_cancel_terminal(self):
        tid = self.ts.create("tutor", {"msg": "hi"})
        self.assertTrue(self.ts.cancel(tid))
        res = self.ts.run(tid)
        self.assertFalse(res["ok"])
        t = self.ts.get(tid)
        self.assertEqual(t["status"], "cancelled")

    def test_retry(self):
        tid = self.ts.create("tutor", {"msg": "hi"})
        # force fail by bad executor? use new service with failing executor
        ts2 = TaskService(db=self.db, tenant_id="t1", user_id="u1", executor=lambda a, p: (_ for _ in ()).throw(Exception("boom")))
        tid2 = ts2.create("tutor", {"msg": "hi"})
        ts2.run(tid2)
        t = ts2.get(tid2)
        self.assertEqual(t["status"], "failed")
        self.assertTrue(ts2.retry(tid2))
        t2 = ts2.get(tid2)
        self.assertEqual(t2["status"], "queued")

    def test_secret_payload_rejected(self):
        with self.assertRaises(ValueError):
            self.ts.create("tutor", {"api_key": "x"})

    def test_tenant_isolation(self):
        tid = self.ts.create("tutor", {"msg": "hi"})
        ts2 = TaskService(db=Database(path=self.path, tenant_id="t2"), tenant_id="t2", user_id="u1")
        self.assertIsNone(ts2.get(tid))

    def test_user_ownership(self):
        ts2 = TaskService(db=self.db, tenant_id="t1", user_id="u2")
        tid = self.ts.create("tutor", {"msg": "hi"})
        self.assertIsNone(ts2.get(tid))

    def test_events_recorded(self):
        tid = self.ts.create("tutor", {"msg": "hi"})
        self.ts.run(tid)
        evs = self.ts.list_events(tid)
        statuses = [e["status"] for e in evs]
        self.assertIn("queued", statuses)
        self.assertIn("running", statuses)
        self.assertIn("done", statuses)

    def test_duplicate_run_safe(self):
        tid = self.ts.create("tutor", {"msg": "hi"})
        self.ts.run(tid)
        # second run should not re-execute (already done)
        res = self.ts.run(tid)
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()