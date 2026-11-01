"""Phase D tests: structured-output validation and its orchestrator integration."""
import unittest
from unittest.mock import patch

from core.validation import validate_output

AGENTS_DIR = "/Users/kiarricafavors/personal-ai-team/agents"


class TestValidation(unittest.TestCase):
    def test_valid_output(self):
        ok, err = validate_output("tutor", {"reply": "hello"})
        self.assertTrue(ok, err)

    def test_non_dict_rejected(self):
        ok, err = validate_output("tutor", "just text")
        self.assertFalse(ok)

    def test_missing_reply_rejected(self):
        ok, err = validate_output("tutor", {"agent": "tutor"})
        self.assertFalse(ok)
        self.assertIn("reply", err)

    def test_reply_must_be_string(self):
        ok, err = validate_output("tutor", {"reply": 123})
        self.assertFalse(ok)
        self.assertIn("str", err)

    def test_secret_rejected(self):
        ok, err = validate_output("tutor", {"reply": "my password is hunter2"})
        self.assertFalse(ok)
        self.assertIn("secret", err)

    def test_oversized_rejected(self):
        ok, err = validate_output("tutor", {"reply": "a" * 20001})
        self.assertFalse(ok)
        self.assertIn("length", err)


class TestOrchestratorValidation(unittest.TestCase):
    def test_dispatch_gates_on_validation(self):
        from agents.registry import AgentRegistry
        from core.orchestrator import Orchestrator
        from core.policy import PolicyEngine
        from core.model_router import ModelResult

        reg = AgentRegistry(AGENTS_DIR)
        reg.load()
        pol = PolicyEngine.from_dict({"rules": [{"subject": "*", "action": "*", "resource": "*", "effect": "allow"}]})

        class FakeRouter:
            def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
                return ModelResult("ok", "ollama", "llama3.1", "local:ollama:llama3.1")

        orch = Orchestrator(reg, policy=pol, router=FakeRouter())
        with patch("core.validation.validate_output", return_value=(False, "bad output")):
            with self.assertRaises(ValueError):
                orch.dispatch("tutor", "hi")

    def test_dispatch_succeeds_with_valid_output(self):
        from agents.registry import AgentRegistry
        from core.orchestrator import Orchestrator
        from core.policy import PolicyEngine
        from core.model_router import ModelResult

        reg = AgentRegistry(AGENTS_DIR)
        reg.load()
        pol = PolicyEngine.from_dict({"rules": [{"subject": "*", "action": "*", "resource": "*", "effect": "allow"}]})

        class FakeRouter:
            def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
                return ModelResult("ok", "ollama", "llama3.1", "local:ollama:llama3.1")

        orch = Orchestrator(reg, policy=pol, router=FakeRouter())
        res = orch.dispatch("tutor", "hi")
        self.assertEqual(res["agent"], "tutor")


if __name__ == "__main__":
    unittest.main()
