import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.project_runner import ProjectRunner
from storage.database import Database


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def dispatch(self, agent, prompt, context):
        self.calls.append((agent, prompt, context))
        return {"reply": f"{agent} draft"}


class ProjectRunnerTest(unittest.TestCase):
    def test_runs_tasks_in_dependency_order_and_persists_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(path=str(Path(directory) / "test.db"), tenant_id="t1")
            now = "2026-01-01T00:00:00+00:00"
            db.execute(
                "INSERT INTO agent_projects "
                "(id,tenant_id,user_id,goal,status,plan_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("p1", "t1", "u1", "Grow users", "running", "{}", now, now))
            for task in (
                ("a", "strategist", "Define the audience.", "[]"),
                ("b", "communications", "Draft captions.", '["a"]'),
            ):
                db.execute(
                    "INSERT INTO agent_tasks "
                    "(id,project_id,tenant_id,user_id,agent,instruction,depends_on,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (task[0], "p1", "t1", "u1", task[1], task[2], task[3],
                     "pending", now, now))
            runtime = FakeRuntime()
            with patch("core.project_runner.build_runtime", return_value=runtime):
                result = ProjectRunner(db, "t1", "u1").run("p1")
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual([call[0] for call in runtime.calls],
                             ["strategist", "communications"])
            self.assertEqual(
                db.query("SELECT status FROM agent_tasks WHERE id='b'")[0]["status"],
                "done")


if __name__ == "__main__":
    unittest.main()
