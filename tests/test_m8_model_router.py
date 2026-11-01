"""Phase A tests: ModelRouter (routing, location, timeout/retry) and agent LLM wiring."""
import unittest
from unittest.mock import patch

from core.model_router import ModelRouter, ModelResult

AGENTS_DIR = "/Users/kiarricafavors/personal-ai-team/agents"


class TestModelRouter(unittest.TestCase):
    def test_default_resolution_is_ollama(self):
        router = ModelRouter()
        provider, model = router._resolve(None)
        self.assertEqual(provider, "ollama")

    def test_manifest_model_spec_is_used(self):
        router = ModelRouter()
        provider, model = router._resolve({"provider": "ollama", "model": "llama3.1"})
        self.assertEqual(provider, "ollama")
        self.assertEqual(model, "llama3.1")

    def test_non_ollama_provider_raises_loudly(self):
        router = ModelRouter(retries=1)
        with self.assertRaises(RuntimeError) as ctx:
            router.complete("tutor", "hi", model_spec={"provider": "openai", "model": "gpt-4"})
        self.assertIn("openai", str(ctx.exception))
        self.assertIn("No cloud routing", str(ctx.exception))

    def test_location_reported_on_success(self):
        router = ModelRouter(retries=1)
        with patch.object(router, "_generate_once", return_value="hello"):
            res = router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "llama3.1"})
        self.assertEqual(res.text, "hello")
        self.assertEqual(res.provider, "ollama")
        self.assertEqual(res.location, "local:ollama:llama3.1")

    def test_retry_then_success(self):
        router = ModelRouter(retries=3)
        calls = {"n": 0}

        def flaky(model, prompt, system):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("connection refused")
            return "final"

        with patch.object(router, "_generate_once", side_effect=flaky):
            res = router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})
        self.assertEqual(calls["n"], 3)
        self.assertEqual(res.text, "final")

    def test_retries_exhausted_raises(self):
        router = ModelRouter(retries=2)

        def always_fail(model, prompt, system):
            raise OSError("down")

        with patch.object(router, "_generate_once", side_effect=always_fail):
            with self.assertRaises(RuntimeError) as ctx:
                router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})
        self.assertIn("2 attempts", str(ctx.exception))

    def test_timeout_flows_to_client(self):
        router = ModelRouter(timeout=7, retries=1)
        captured = {}

        class FakeClient:
            def __init__(self, **kw):
                captured["kw"] = kw

            def complete(self, prompt, system="", timeout=120):
                captured["timeout"] = timeout
                return "ok"

        import core.llm_client as lc
        orig = lc.LLMClient
        lc.LLMClient = FakeClient
        try:
            res = router.complete("tutor", "hi", model_spec={"provider": "ollama", "model": "m"})
        finally:
            lc.LLMClient = orig
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(res.location, "local:ollama:m")

    def test_model_result_to_dict(self):
        r = ModelResult("x", "ollama", "m", "local:ollama:m")
        self.assertEqual(r.to_dict(), {"text": "x", "provider": "ollama", "model": "m", "location": "local:ollama:m"})


class TestAgentWiring(unittest.TestCase):
    def test_agent_calls_router_and_returns_structured_output(self):
        from agents.registry import AgentRegistry
        from agents.tutor.agent import TutorAgent

        reg = AgentRegistry(AGENTS_DIR)
        reg.load()
        manifest = reg.get("tutor")

        captured = {}

        class FakeRouter:
            def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
                captured["system"] = system
                captured["model_spec"] = model_spec
                return ModelResult("reply text", "ollama", "llama3.1", "local:ollama:llama3.1")

        agent = TutorAgent(router=FakeRouter(), manifest=manifest)
        res = agent.run("explain gravity")

        self.assertEqual(res["agent"], "tutor")
        self.assertEqual(res["reply"], "reply text")
        self.assertEqual(res["location"], "local:ollama:llama3.1")
        self.assertEqual(captured["model_spec"]["provider"], "ollama")
        # persona grounding: system prompt carries role + capabilities from the manifest
        self.assertIn("Personal tutor", captured["system"])
        self.assertIn("explain", captured["system"])

    def test_agent_without_router_raises(self):
        from agents.tutor.agent import TutorAgent
        agent = TutorAgent(router=None, manifest={"identity": {"role": "tutor"}})
        with self.assertRaises(RuntimeError):
            agent.run("hello")


if __name__ == "__main__":
    unittest.main()
