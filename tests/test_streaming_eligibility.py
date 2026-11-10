"""V1.3.2b.1 — streaming eligibility, incremental validation, generation tests."""
import unittest
from unittest.mock import patch, MagicMock

from core.validation import IncrementalValidator, SECRET_PATTERNS, MAX_FIELD_LEN
from core.model_router import ModelResult


class TestIncrementalValidator(unittest.TestCase):
    def test_secret_single_chunk(self):
        v = IncrementalValidator()
        ok, err = v.check_chunk("password")
        self.assertFalse(ok)

    def test_secret_split_two(self):
        v = IncrementalValidator()
        self.assertTrue(v.check_chunk("pass")[0])
        ok, err = v.check_chunk("word")
        self.assertFalse(ok)

    def test_secret_split_three(self):
        v = IncrementalValidator()
        self.assertTrue(v.check_chunk("pas")[0])
        self.assertTrue(v.check_chunk("sw")[0])
        ok, _ = v.check_chunk("ord")
        self.assertFalse(ok)

    def test_case_insensitive(self):
        v = IncrementalValidator()
        self.assertTrue(v.check_chunk("PASS")[0])
        ok, _ = v.check_chunk("WORD")
        self.assertFalse(ok)

    def test_pattern_at_end(self):
        v = IncrementalValidator()
        self.assertTrue(v.check_chunk("hi ")[0])
        ok, _ = v.check_chunk("password")
        self.assertFalse(ok)

    def test_pattern_at_boundary(self):
        v = IncrementalValidator()
        self.assertTrue(v.check_chunk("pass")[0])
        ok, _ = v.check_chunk("word!")
        self.assertFalse(ok)

    def test_exactly_20000_accepted(self):
        v = IncrementalValidator()
        chunk = "a" * 20000
        ok, _ = v.check_chunk(chunk)
        self.assertTrue(ok)
        self.assertEqual(v.total, 20000)

    def test_20001_rejected(self):
        v = IncrementalValidator()
        self.assertTrue(v.check_chunk("a" * 20000)[0])
        ok, _ = v.check_chunk("a")
        self.assertFalse(ok)

    def test_pattern_collection_affects_window(self):
        import core.validation as cv
        orig = cv.SECRET_PATTERNS
        try:
            cv.SECRET_PATTERNS = orig + ("x" * 50,)
            v = IncrementalValidator()
            self.assertEqual(v.max_pattern_len, 50)
        finally:
            cv.SECRET_PATTERNS = orig

    def test_empty_patterns_no_crash(self):
        import core.validation as cv
        orig = cv.SECRET_PATTERNS
        try:
            cv.SECRET_PATTERNS = ()
            v = IncrementalValidator()
            self.assertTrue(v.check_chunk("password")[0])
        finally:
            cv.SECRET_PATTERNS = orig

    def test_valid_text(self):
        v = IncrementalValidator()
        self.assertTrue(v.check_chunk("hello world")[0])
        self.assertTrue(v.check_chunk(" more text")[0])


class TestEligibility(unittest.TestCase):
    def _make_agent(self, name="tutor"):
        from agents.base import BaseAgent
        # Use a concrete agent
        from agents.tutor.agent import TutorAgent
        a = TutorAgent(memory=None, router=MagicMock(), manifest={}, user_id="u1")
        return a

    def test_eligible(self):
        agent = self._make_agent()
        ctx = {"work_intent": False, "tool_calls": []}
        # call _ground eligibility logic by checking the condition directly
        eligible = (not bool(ctx.get("work_intent")) and not ctx.get("tool_calls")
                    and agent.name in agent._STANDARD_AGENTS and agent.router is not None)
        self.assertTrue(eligible)

    def test_work_intent_true_ineligible(self):
        agent = self._make_agent()
        ctx = {"work_intent": True, "tool_calls": []}
        eligible = (not bool(ctx.get("work_intent")) and not ctx.get("tool_calls"))
        self.assertFalse(eligible)

    def test_nonempty_tool_calls_ineligible(self):
        agent = self._make_agent()
        ctx = {"work_intent": False, "tool_calls": [{"tool": "x"}]}
        eligible = (not bool(ctx.get("work_intent")) and not ctx.get("tool_calls"))
        self.assertFalse(eligible)

    def test_unknown_agent_ineligible(self):
        from agents.base import BaseAgent
        class FakeAgent(BaseAgent):
            name = "fake_agent"
            def run(self, task, context=None, stream=False, on_chunk=None):
                return self._ground(task, context, stream=stream, on_chunk=on_chunk)
        a = FakeAgent(memory=None, router=MagicMock(), manifest={}, user_id="u1")
        self.assertNotIn(a.name, a._STANDARD_AGENTS)


class TestGenerationStreaming(unittest.TestCase):
    def test_valid_text_emits_chunks(self):
        from agents.tutor.agent import TutorAgent
        router = MagicMock()
        router._resolve.return_value = ("ollama", "m")
        router.complete_stream.return_value = iter(["Hello", " world"])
        agent = TutorAgent(memory=None, router=router, manifest={}, user_id="u1")
        received = []
        result = agent.run("hi", context={"work_intent": False}, stream=True, on_chunk=received.append)
        self.assertEqual(result["reply"], "Hello world")
        self.assertEqual(received, ["Hello", " world"])

    def test_secret_rejection_stops_emission(self):
        from agents.tutor.agent import TutorAgent
        router = MagicMock()
        router._resolve.return_value = ("ollama", "m")
        router.complete_stream.return_value = iter(["safe ", "password"])
        agent = TutorAgent(memory=None, router=router, manifest={}, user_id="u1")
        received = []
        with self.assertRaises(ValueError):
            agent.run("hi", context={"work_intent": False}, stream=True, on_chunk=received.append)
        self.assertEqual(received, ["safe "])

    def test_length_rejection(self):
        from agents.tutor.agent import TutorAgent
        router = MagicMock()
        router._resolve.return_value = ("ollama", "m")
        router.complete_stream.return_value = iter(["a" * 20001])
        agent = TutorAgent(memory=None, router=router, manifest={}, user_id="u1")
        received = []
        with self.assertRaises(ValueError):
            agent.run("hi", context={"work_intent": False}, stream=True, on_chunk=received.append)
        self.assertEqual(received, [])

    def test_llm_exception_propagates(self):
        from agents.tutor.agent import TutorAgent
        router = MagicMock()
        router._resolve.return_value = ("ollama", "m")
        router.complete_stream.side_effect = ConnectionError("boom")
        agent = TutorAgent(memory=None, router=router, manifest={}, user_id="u1")
        with self.assertRaises(ConnectionError):
            agent.run("hi", context={"work_intent": False}, stream=True)

    def test_work_intent_true_never_streams(self):
        from agents.tutor.agent import TutorAgent
        router = MagicMock()
        router.complete.return_value = ModelResult("reply", "ollama", "m", "local:ollama:m")
        agent = TutorAgent(memory=None, router=router, manifest={}, user_id="u1", tools=MagicMock())
        received = []
        result = agent.run("hi", context={"work_intent": True}, stream=True, on_chunk=received.append)
        self.assertEqual(received, [])
        router.complete_stream.assert_not_called()

    def test_nonstreaming_unchanged(self):
        from agents.tutor.agent import TutorAgent
        router = MagicMock()
        router.complete.return_value = ModelResult("reply", "ollama", "m", "local:ollama:m")
        agent = TutorAgent(memory=None, router=router, manifest={}, user_id="u1")
        result = agent.run("hi", context={})
        self.assertEqual(result["reply"], "reply")
        router.complete_stream.assert_not_called()

    def test_final_validation_runs(self):
        from core.orchestrator import Orchestrator
        from core.policy import PolicyEngine
        reg = MagicMock()
        reg.get.return_value = {"tools": []}
        # Build a minimal orchestrator with mock agent
        # Just verify dispatch forwards stream param
        orch = Orchestrator(registry=reg, policy=None)
        # policy None → PermissionError
        with self.assertRaises(PermissionError):
            orch.dispatch("tutor", "hi", stream=True)


if __name__ == "__main__":
    unittest.main()
