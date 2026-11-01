import os, unittest
from agents.registry import AgentRegistry


class TestM2(unittest.TestCase):
    def test_registry_loads(self):
        reg = AgentRegistry("/Users/kiarricafavors/personal-ai-team/agents")
        reg.load()
        self.assertIn("tutor", reg.list())
        self.assertIn("soundboard", reg.list())

    def test_invalid_manifest_fails(self):
        import tempfile, json
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "bad"))
        with open(os.path.join(d, "bad", "manifest.json"), "w") as f:
            json.dump({"name": "bad"}, f)
        reg = AgentRegistry(d)
        with self.assertRaises(ValueError):
            reg.load()

    def test_orchestrator_dispatch(self):
        reg = AgentRegistry("/Users/kiarricafavors/personal-ai-team/agents")
        reg.load()
        from core.orchestrator import Orchestrator
        orch = Orchestrator(reg)
        res = orch.dispatch("tutor", "hello")
        self.assertEqual(res["agent"], "tutor")

    def test_unknown_agent(self):
        reg = AgentRegistry("/Users/kiarricafavors/personal-ai-team/agents")
        reg.load()
        from core.orchestrator import Orchestrator
        orch = Orchestrator(reg)
        with self.assertRaises(ValueError):
            orch.dispatch("nope", "hi")


if __name__ == "__main__":
    unittest.main()