import unittest

from agents.base import BaseAgent
from core.career import FIRST_ASSIGNMENT, TEAM_OPERATING_RULES, operating_contract


class CareerContractTests(unittest.TestCase):
    def test_contract_is_stable_and_mentions_first_assignment(self):
        contract = operating_contract()
        self.assertIn("permanent career rules", contract)
        self.assertIn(FIRST_ASSIGNMENT, contract)
        for rule in TEAM_OPERATING_RULES:
            self.assertIn(rule, contract)

    def test_contract_is_separate_from_brand_context(self):
        agent = BaseAgent(
            manifest={
                "name": "test",
                "identity": {"display_name": "Test", "role": "Tester"},
                "capabilities": ["test"],
            }
        )
        prompt = agent._system_prompt(
            brand=[{"category": "identity", "key": "brand_name", "value": "Example"}]
        )
        self.assertLess(prompt.index("IDENTITY"), prompt.index("TEAM OPERATING CONTRACT"))
        self.assertLess(prompt.index("TEAM OPERATING CONTRACT"), prompt.index("BRAND CONTEXT"))
        self.assertIn("On Us", prompt)
        self.assertIn("Example", prompt)

    def test_contract_requires_truthful_action_reporting(self):
        self.assertIn("Never claim to have sent", operating_contract())


if __name__ == "__main__":
    unittest.main()
