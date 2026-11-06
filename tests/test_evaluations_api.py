import unittest

from fastapi.testclient import TestClient

from api.app import app


class EvaluationApiTests(unittest.TestCase):
    def test_scenarios_are_listed(self):
        response = TestClient(app).get("/evaluations/scenarios")
        self.assertEqual(response.status_code, 200)
        self.assertIn("instagram_campaign", response.json()["scenarios"])

    def test_local_campaign_evaluation(self):
        response = TestClient(app).post("/evaluations/run", json={
            "scenario": "instagram_campaign",
            "agents": ["strategist", "communications"],
            "plan_status": "awaiting_approval",
            "output": {"text": "campaign content", "published": False},
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["passed"])

    def test_running_status_is_an_approval_gated_workflow_state(self):
        response = TestClient(app).post("/evaluations/run", json={
            "scenario": "business_research",
            "agents": ["strategist"],
            "plan_status": "running",
            "output": {"text": "research"},
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["passed"])

    def test_owned_execution_list_is_available(self):
        response = TestClient(app).get("/evaluations/executions")
        self.assertEqual(response.status_code, 200)
        self.assertIn("executions", response.json())


if __name__ == "__main__":
    unittest.main()
