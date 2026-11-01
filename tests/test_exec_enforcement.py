import os, tempfile, unittest
from storage.database import Database
from core.policy import PolicyEngine
from core.tasks import TaskService
from core.orchestrator import Orchestrator
from agents.registry import AgentRegistry


class TestExecEnforcement(unittest.TestCase):
    def test_denied_task_never_executes(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(path)
        db = Database(path=path, tenant_id="t1")
        # deny-all policy
        pol = PolicyEngine.from_dict({"rules": []})
        called = {"n": 0}
        def execf(a, p):
            called["n"] += 1
            return {"done": True}
        ts = TaskService(db=db, tenant_id="t1", user_id="u1", executor=execf, policy=pol)
        tid = ts.create("tutor", {"msg": "hi"})
        res = ts.run(tid)
        self.assertFalse(res["ok"])
        self.assertEqual(called["n"], 0)
        os.remove(path)

    def test_allowed_task_executes(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(path)
        db = Database(path=path, tenant_id="t1")
        pol = PolicyEngine.from_dict({"rules": [{"subject": "*", "action": "*", "resource": "*", "effect": "allow"}]})
        called = {"n": 0}
        def execf(a, p):
            called["n"] += 1
            return {"done": True}
        ts = TaskService(db=db, tenant_id="t1", user_id="u1", executor=execf, policy=pol)
        tid = ts.create("tutor", {"msg": "hi"})
        res = ts.run(tid)
        self.assertTrue(res["ok"])
        self.assertEqual(called["n"], 1)
        os.remove(path)

    def test_orchestrator_denied_never_dispatches(self):
        reg = AgentRegistry("/Users/kiarricafavors/personal-ai-team/agents")
        reg.load()
        pol = PolicyEngine.from_dict({"rules": []})
        orch = Orchestrator(reg, policy=pol)
        with self.assertRaises(PermissionError):
            orch.dispatch("tutor", "hi")


if __name__ == "__main__":
    unittest.main()