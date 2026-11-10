"""Regression tests for current intent priority."""
import unittest
from agents.base import BaseAgent

class TestIntentPriority(unittest.TestCase):
    def _agent(self):
        a = BaseAgent(manifest={"identity": {"display_name": "A", "role": "Strategist"}}, user_id="u1")
        a.name = "strategist"
        a.manifest["capabilities"] = []
        return a

    def test_priority_in_system_prompt(self):
        a = self._agent()
        prompt = a._system_prompt(facts=[{"key": "goal", "value": "Instagram"}], brand=[{"key": "role", "value": "Founder"}], history=[])
        self.assertIn("CURRENT TASK PRIORITY", prompt)
        self.assertIn("take precedence", prompt)

    def test_rejection_handling_in_prompt(self):
        a = self._agent()
        prompt = a._system_prompt()
        self.assertIn("rejects", prompt.lower())

if __name__ == "__main__":
    unittest.main()
