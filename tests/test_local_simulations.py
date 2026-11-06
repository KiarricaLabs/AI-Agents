import unittest

from core.tools import build_registry


class LocalSimulationToolTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()

    def test_email_is_local_and_not_sent(self):
        result = self.registry.invoke(
            "communications",
            "simulate_email",
            {"recipient": "sister@example.test", "subject": "Dinner", "body": "Are you free?"},
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["result"]["sent"])
        self.assertEqual(result["result"]["status"], "simulated")

    def test_campaign_is_local_and_not_published(self):
        result = self.registry.invoke(
            "communications",
            "simulate_social_campaign",
            {"platform": "instagram", "campaign": "On Us waitlist", "content": ["post 1"]},
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["result"]["published"])

    def test_travel_is_local_and_not_booked(self):
        result = self.registry.invoke(
            "executive_assistant",
            "simulate_travel",
            {"destination": "Puerto Rico"},
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["result"]["booked"])
        self.assertFalse(result["result"]["charged"])

    def test_missing_required_input_is_explicit(self):
        result = self.registry.invoke(
            "communications",
            "simulate_email",
            {"recipient": "sister@example.test", "subject": "Dinner"},
        )
        self.assertFalse(result["ok"])
        self.assertIn("body is required", result["error"])


if __name__ == "__main__":
    unittest.main()
