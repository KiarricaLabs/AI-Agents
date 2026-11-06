import json
import tempfile
import unittest
from pathlib import Path

from core.action_executor import ActionExecutor
from storage.database import Database


class ActionExecutorTest(unittest.TestCase):
    def test_approved_action_is_recorded_as_local_stub(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(path=str(Path(directory) / "actions.db"), tenant_id="t1")
            now = "2026-01-01T00:00:00+00:00"
            db.execute(
                "INSERT INTO pending_actions "
                "(id,project_id,tenant_id,user_id,agent,type,payload,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("a1", "p1", "t1", "u1", "assistant", "email",
                 json.dumps({"to": "sister@example.test"}), "approved", now, now))
            result = ActionExecutor(db, "t1", "u1").execute("a1")
            self.assertFalse(result["performed"])
            self.assertTrue(result["stub"])
            self.assertEqual(
                db.query("SELECT status FROM pending_actions WHERE id='a1'")[0]["status"],
                "executed")

    def test_unapproved_action_cannot_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(path=str(Path(directory) / "actions.db"), tenant_id="t1")
            now = "2026-01-01T00:00:00+00:00"
            db.execute(
                "INSERT INTO pending_actions "
                "(id,project_id,tenant_id,user_id,agent,type,payload,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("a1", "p1", "t1", "u1", "assistant", "dm",
                 "{}", "pending", now, now))
            with self.assertRaises(ValueError):
                ActionExecutor(db, "t1", "u1").execute("a1")


if __name__ == "__main__":
    unittest.main()
