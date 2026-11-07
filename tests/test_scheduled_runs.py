import unittest
from storage.database import Database
from core.run_worker import enqueue_scheduled_run


class ScheduledRunIdempotencyTests(unittest.TestCase):
    def setUp(self):
        import tempfile, os
        self.db_path = os.path.join(tempfile.gettempdir(), "sched_test.db")
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass
        self.db = Database(path=self.db_path, tenant_id="t1")
        # create project
        with self.db.transaction() as c:
            c.execute("INSERT INTO agent_projects (id,tenant_id,user_id,goal,status,plan_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                      ("p1", "t1", "u1", "g", "approved", "{}", "2024-01-01", "2024-01-01"))

    def tearDown(self):
        import os
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    def _count(self, project_id="p1"):
        rows = self.db.query("SELECT COUNT(*) AS c FROM agent_runs WHERE project_id=?", (project_id,))
        return rows[0]["c"]

    def test_first_occurrence_creates_one_run(self):
        rid = enqueue_scheduled_run(self.db, "p1", "t1", "u1", 60)
        self.assertIsNotNone(rid)
        self.assertEqual(self._count(), 1)

    def test_repeated_enqueue_same_occurrence_no_duplicate(self):
        r1 = enqueue_scheduled_run(self.db, "p1", "t1", "u1", 60)
        r2 = enqueue_scheduled_run(self.db, "p1", "t1", "u1", 60)
        self.assertEqual(r1, r2)
        self.assertEqual(self._count(), 1)

    def test_unapproved_project_cannot_enqueue(self):
        with self.db.transaction() as c:
            c.execute("INSERT INTO agent_projects (id,tenant_id,user_id,goal,status,plan_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                      ("p2", "t1", "u1", "g", "awaiting_plan_approval", "{}", "2024-01-01", "2024-01-01"))
        rid = enqueue_scheduled_run(self.db, "p2", "t1", "u1", 60)
        self.assertIsNone(rid)
        self.assertEqual(self._count("p2"), 0)

    def test_approved_project_can_enqueue(self):
        rid = enqueue_scheduled_run(self.db, "p1", "t1", "u1", 60)
        self.assertIsNotNone(rid)

    def test_two_projects_independent(self):
        with self.db.transaction() as c:
            c.execute("INSERT INTO agent_projects (id,tenant_id,user_id,goal,status,plan_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                      ("p3", "t1", "u1", "g", "approved", "{}", "2024-01-01", "2024-01-01"))
        r1 = enqueue_scheduled_run(self.db, "p1", "t1", "u1", 60)
        r3 = enqueue_scheduled_run(self.db, "p3", "t1", "u1", 60)
        self.assertNotEqual(r1, r3)
        self.assertEqual(self._count("p1"), 1)
        self.assertEqual(self._count("p3"), 1)

    def test_project_creation_idempotency_unaffected(self):
        # sanity: agent_projects row still unique by id
        rows = self.db.query("SELECT COUNT(*) AS c FROM agent_projects WHERE id='p1'")
        self.assertEqual(rows[0]["c"], 1)


if __name__ == "__main__":
    unittest.main()