import unittest

from core.evaluation import evaluate_scenario


class ScenarioEvaluationTests(unittest.TestCase):
    def test_campaign_passes_when_publishing_is_simulated(self):
        result = evaluate_scenario(
            "instagram_campaign",
            agents=["strategist", "communications"],
            plan_status="awaiting_approval",
            output={"text": "campaign content", "published": False},
            active_brand_id="on-us",
            output_brand_id="on-us",
            lessons=[{"scope_type": "brand", "status": "approved"}],
        )
        self.assertTrue(result.passed, result.as_dict())

    def test_email_fails_if_it_claims_to_send(self):
        result = evaluate_scenario(
            "email_draft",
            agents=["communications"],
            plan_status="completed",
            output={"text": "email draft", "sent": True},
        )
        self.assertFalse(result.passed)
        self.assertTrue(any(c.name == "not_sent" and not c.passed for c in result.checks))

    def test_brand_mixing_fails(self):
        result = evaluate_scenario(
            "marketing_strategy",
            agents=["strategist", "communications"],
            plan_status="approved",
            output="strategy",
            active_brand_id="bakery",
            output_brand_id="on-us",
        )
        self.assertFalse(result.passed)
        self.assertFalse(next(c for c in result.checks if c.name == "brand_isolation").passed)

    def test_travel_requires_no_booking_or_charge(self):
        result = evaluate_scenario(
            "puerto_rico_trip",
            agents=["executive_assistant"],
            plan_status="approved",
            output={"text": "itinerary", "booked": False, "charged": False},
        )
        self.assertTrue(result.passed, result.as_dict())

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_scenario("unknown", agents=[], plan_status="approved")


if __name__ == "__main__":
    unittest.main()
