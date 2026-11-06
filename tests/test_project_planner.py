import json
import tempfile
import unittest
from pathlib import Path

from core.project_planner import StructuredProjectPlanner
from storage.database import Database


class FakeResult:
    def __init__(self, text):
        self.text = text


class FakeRouter:
    def __init__(self):
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return FakeResult('{"goal":"x","tasks":[]}')
        return FakeResult(json.dumps({
            "goal": "Grow On Us users",
            "tasks": [{
                "id": "audience",
                "agent": "strategist",
                "instruction": "Define the Bay Area audience and metrics.",
                "depends_on": [],
                "deliverable_type": "audience brief",
                "acceptance_criteria": ["Names the target audience", "Defines measurable metrics"],
            }, {
                "id": "content",
                "agent": "communications",
                "instruction": "Draft Instagram content from the audience plan.",
                "depends_on": ["audience"],
                "deliverable_type": "content brief",
                "acceptance_criteria": ["Includes hooks", "Includes calls to action"],
            }],
        }))


class StructuredProjectPlannerTest(unittest.TestCase):
    def test_retries_with_validation_error_and_uses_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(path=str(Path(directory) / "test.db"), tenant_id="t1")
            router = FakeRouter()
            plan = StructuredProjectPlanner(db, "t1", "u1", router).plan(
                "Grow On Us users")
            self.assertEqual(len(plan.tasks), 2)
            self.assertEqual(len(router.calls), 2)
            self.assertIsNotNone(router.calls[0]["json_schema"])
            self.assertIn("validation error", router.calls[1]["prompt"])
            self.assertEqual(
                db.query("SELECT COUNT(*) AS n FROM activity_log")[0]["n"], 4)


if __name__ == "__main__":
    unittest.main()
