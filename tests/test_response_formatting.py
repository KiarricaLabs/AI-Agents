"""Verify the shared system prompt carries consistent response-formatting guidance.

Feature (conversational UX polish): agents should be natural, use headings only
when appropriate, avoid excessive bullets, and explain technical detail plainly.
"""
import unittest

from agents.base import BaseAgent


class TestResponseStyleGuidance(unittest.TestCase):
    def _prompt(self, facts=None, history=None):
        agent = BaseAgent(manifest={"identity": {"role": "Tester", "personality": "calm"}, "capabilities": []})
        return agent._system_prompt(facts=facts, history=history)

    def test_guidance_is_always_present(self):
        prompt = self._prompt()
        self.assertIn("RESPONSE STYLE", prompt)
        self.assertIn("natural and conversational", prompt)
        self.assertIn("Markdown", prompt)

    def test_guidance_discourages_excessive_formatting(self):
        prompt = self._prompt()
        self.assertIn("do not overuse bullet points", prompt)

    def test_guidance_does_not_override_memory_or_history_sections(self):
        prompt = self._prompt(
            facts=[{"key": "brand", "value": "Acme", "kind": "fact"}],
            history=[{"role": "user", "content": "hello"}],
        )
        # Guidance is additive; grounding markers remain intact.
        self.assertIn("KNOWN FACTS", prompt)
        self.assertIn("RECENT CONVERSATION", prompt)
        self.assertIn("RESPONSE STYLE", prompt)


if __name__ == "__main__":
    unittest.main()
