"""Phase C tests: ToolRegistry, local tools, permission enforcement, audit, timeout.

Deterministic; no external services. Covers registration, manifest scoping,
policy default-deny, the consequential gate, safe arithmetic evaluation,
tenant-isolated audit, and failure isolation.
"""
import os
import tempfile
import time
import unittest
from datetime import datetime

from storage.database import Database
from core.policy import PolicyEngine
from core.tools import Tool, ToolRegistry, build_registry
from core.tools.local.calculate import CalculateTool
from core.tools.local.now import NowTool


def _allow_tool(agent, tool="*"):
    return PolicyEngine.from_dict({"rules": [
        {"subject": agent, "action": "tool", "resource": tool, "effect": "allow"},
    ]})


def _manifest(name, tools):
    return {"name": name, "tools": tools}


class TestToolRegistry(unittest.TestCase):
    def test_build_registry_registers_inventory(self):
        reg = build_registry()
        self.assertTrue(reg.has("now"))
        self.assertTrue(reg.has("calculate"))
        self.assertIsInstance(reg.get("now"), NowTool)
        self.assertIsInstance(reg.get("calculate"), CalculateTool)

    def test_unknown_or_deferred_tool_is_error(self):
        reg = build_registry()
        for name in ("web_search", "email", "calendar"):
            self.assertFalse(reg.has(name))
            with self.assertRaises(ValueError):
                reg.invoke("tutor", name, {}, manifest=_manifest("tutor", [name]))

    def test_manifest_isolation(self):
        reg = build_registry()
        # tutor may not call "now" (not in its manifest tools)
        with self.assertRaises(PermissionError):
            reg.invoke("tutor", "now", {}, manifest=_manifest("tutor", ["calculate"]))

    def test_policy_default_deny(self):
        reg = build_registry()
        pol = PolicyEngine.from_dict({"rules": []})  # deny-all
        with self.assertRaises(PermissionError):
            reg.invoke("tutor", "calculate", {"expression": "1+1"},
                       manifest=_manifest("tutor", ["calculate"]), policy=pol)

    def test_policy_allows_when_rule_matches(self):
        reg = build_registry()
        pol = _allow_tool("tutor", "calculate")
        res = reg.invoke("tutor", "calculate", {"expression": "2+2"},
                         manifest=_manifest("tutor", ["calculate"]), policy=pol)
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"], 4)

    def test_policy_wrong_resource_denied(self):
        reg = build_registry()
        pol = _allow_tool("tutor", "now")  # only "now" allowed
        with self.assertRaises(PermissionError):
            reg.invoke("tutor", "calculate", {"expression": "1+1"},
                       manifest=_manifest("tutor", ["calculate"]), policy=pol)

    def test_consequential_requires_approval(self):
        class SendEmail(Tool):
            name = "send_email"
            consequential = True
            def run(self, args, context=None):
                return "sent"
        reg = ToolRegistry()
        reg.register(SendEmail())
        pol = _allow_tool("assistant", "send_email")
        with self.assertRaises(PermissionError):
            reg.invoke("assistant", "send_email", {},
                       manifest=_manifest("assistant", ["send_email"]), policy=pol)
        res = reg.invoke("assistant", "send_email", {},
                         manifest=_manifest("assistant", ["send_email"]), policy=pol,
                         approved=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"], "sent")

    def test_timeout_is_clean_and_other_tools_still_work(self):
        class SlowTool(Tool):
            name = "slow"
            consequential = False
            def run(self, args, context=None):
                time.sleep(0.5)
                return "late"
        reg = ToolRegistry(default_timeout=0.05)
        reg.register(SlowTool())
        reg.register(CalculateTool())
        pol = _allow_tool("tutor")
        res = reg.invoke("tutor", "slow", {}, manifest=_manifest("tutor", ["slow"]), policy=pol)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "timeout")
        # registry remains usable afterwards
        res2 = reg.invoke("tutor", "calculate", {"expression": "3*4"},
                          manifest=_manifest("tutor", ["calculate"]), policy=pol)
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["result"], 12)


class TestCalculateTool(unittest.TestCase):
    def setUp(self):
        self.tool = CalculateTool()

    def _eval(self, expr):
        return self.tool.run({"expression": expr})

    def test_basic_arithmetic(self):
        self.assertEqual(self._eval("1+2*3"), 7)
        self.assertEqual(self._eval("(1+2)*3"), 9)
        self.assertEqual(self._eval("10//3"), 3)
        self.assertEqual(self._eval("10%3"), 1)
        self.assertEqual(self._eval("2**10"), 1024)
        self.assertEqual(self._eval("-5 + 2"), -3)
        self.assertEqual(self._eval("7/2"), 3.5)

    def test_names_rejected(self):
        with self.assertRaises(ValueError):
            self._eval("__import__('os')")
        with self.assertRaises(ValueError):
            self._eval("open('/etc/passwd')")

    def test_calls_and_attrs_rejected(self):
        with self.assertRaises(ValueError):
            self._eval("len([1,2])")
        with self.assertRaises(ValueError):
            self._eval("1 .__class__")
        with self.assertRaises(ValueError):
            self._eval("(1).real")

    def test_large_exponent_rejected(self):
        with self.assertRaises(ValueError):
            self._eval("2**101")

    def test_overflow_rejected(self):
        with self.assertRaises(ValueError):
            self._eval("(2**100)**100")

    def test_non_numeric_result_rejected(self):
        with self.assertRaises(ValueError):
            self._eval("'a'")
        with self.assertRaises(ValueError):
            self._eval("True")

    def test_empty_expression_rejected(self):
        with self.assertRaises(ValueError):
            self.tool.run({})

    def test_long_expression_rejected(self):
        with self.assertRaises(ValueError):
            self._eval("1+" * 200)


class TestNowTool(unittest.TestCase):
    def test_returns_iso_timestamps(self):
        result = NowTool().run({})
        # both fields parse as ISO 8601 datetimes
        datetime.fromisoformat(result["utc"])
        datetime.fromisoformat(result["local"])


class TestAuditAndTenantIsolation(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")

    def tearDown(self):
        os.remove(self.path)

    def test_audit_records_tenant_user_and_hash_but_no_raw_args(self):
        reg = ToolRegistry(db=self.db, tenant_id="t1")
        reg.register(CalculateTool())
        pol = _allow_tool("tutor", "calculate")
        reg.invoke("tutor", "calculate", {"expression": "1+1"},
                   manifest=_manifest("tutor", ["calculate"]), policy=pol, user_id="u1")
        rows = self.db.query("SELECT * FROM tool_executions WHERE tenant_id='t1'")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["tenant_id"], "t1")
        self.assertEqual(row["user_id"], "u1")
        self.assertEqual(row["agent_id"], "tutor")
        self.assertEqual(row["tool"], "calculate")
        self.assertEqual(row["status"], "ok")
        # params_hash present and is a digest, not the raw expression
        self.assertTrue(row["params_hash"])
        self.assertEqual(len(row["params_hash"]), 64)
        self.assertNotIn("expression", row["params_hash"])
        # raw args are never persisted anywhere in the row
        for v in row.values():
            self.assertNotIn("1+1", str(v))

    def test_error_is_audited_sanitized(self):
        reg = ToolRegistry(db=self.db, tenant_id="t1")
        reg.register(CalculateTool())
        pol = _allow_tool("tutor", "calculate")
        res = reg.invoke("tutor", "calculate", {"expression": "1/0"},
                         manifest=_manifest("tutor", ["calculate"]), policy=pol, user_id="u1")
        self.assertFalse(res["ok"])
        rows = self.db.query("SELECT * FROM tool_executions WHERE tenant_id='t1'")
        self.assertEqual(rows[0]["status"], "error")
        self.assertTrue(rows[0]["error"])

    def test_registry_is_bound_to_its_tenant(self):
        reg_a = ToolRegistry(db=self.db, tenant_id="t1")
        reg_a.register(CalculateTool())
        pol = _allow_tool("tutor", "calculate")
        reg_a.invoke("tutor", "calculate", {"expression": "1"},
                     manifest=_manifest("tutor", ["calculate"]), policy=pol, user_id="u1")

        fd2, path2 = tempfile.mkstemp(suffix=".db")
        os.close(fd2)
        os.remove(path2)
        db2 = Database(path=path2, tenant_id="t2")
        reg_b = ToolRegistry(db=db2, tenant_id="t2")
        reg_b.register(CalculateTool())
        reg_b.invoke("tutor", "calculate", {"expression": "2"},
                     manifest=_manifest("tutor", ["calculate"]), policy=pol, user_id="u1")

        # Each writes audit scoped to its own tenant/db, never the other's.
        self.assertEqual(len(self.db.query("SELECT * FROM tool_executions")), 1)
        self.assertEqual(self.db.query("SELECT * FROM tool_executions")[0]["tenant_id"], "t1")
        self.assertEqual(len(db2.query("SELECT * FROM tool_executions")), 1)
        self.assertEqual(db2.query("SELECT * FROM tool_executions")[0]["tenant_id"], "t2")
        os.remove(path2)


class TestAgentToolIntegration(unittest.TestCase):
    def _fake_router(self):
        from core.model_router import ModelResult

        class FakeRouter:
            def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
                return ModelResult("reply", "ollama", "llama3.1", "local:ollama:llama3.1")
        return FakeRouter()

    def test_agent_runs_tools_and_returns_results(self):
        from agents.tutor.agent import TutorAgent
        reg = build_registry()
        pol = _allow_tool("tutor", "calculate")
        manifest = {"name": "tutor", "tools": ["calculate"],
                    "model": {"provider": "ollama", "model": "llama3.1"},
                    "identity": {"role": "tutor"}}
        agent = TutorAgent(router=self._fake_router(), manifest=manifest,
                           tools=reg, policy=pol)
        result = agent.run("compute", {"tool_calls": [{"tool": "calculate", "args": {"expression": "6*7"}}]})
        self.assertEqual(len(result["tool_results"]), 1)
        self.assertTrue(result["tool_results"][0]["ok"])
        self.assertEqual(result["tool_results"][0]["result"], 42)

    def test_agent_without_tools_returns_empty_list(self):
        from agents.tutor.agent import TutorAgent
        manifest = {"name": "tutor", "tools": [],
                    "model": {"provider": "ollama", "model": "llama3.1"},
                    "identity": {"role": "tutor"}}
        agent = TutorAgent(router=self._fake_router(), manifest=manifest, tools=None)
        result = agent.run("hi", {"tool_calls": [{"tool": "calculate", "args": {"expression": "1"}}]})
        self.assertEqual(result["tool_results"], [])

    def test_denied_tool_is_isolated_not_crash(self):
        from agents.tutor.agent import TutorAgent
        reg = build_registry()
        pol = PolicyEngine.from_dict({"rules": []})  # deny-all
        manifest = {"name": "tutor", "tools": ["calculate"],
                    "model": {"provider": "ollama", "model": "llama3.1"},
                    "identity": {"role": "tutor"}}
        agent = TutorAgent(router=self._fake_router(), manifest=manifest,
                           tools=reg, policy=pol)
        result = agent.run("hi", {"tool_calls": [{"tool": "calculate", "args": {"expression": "1"}}]})
        self.assertEqual(len(result["tool_results"]), 1)
        self.assertFalse(result["tool_results"][0]["ok"])
        # agent itself still produced a reply (failure isolated to the tool)
        self.assertEqual(result["reply"], "reply")

    def test_one_tool_failure_does_not_abort_others(self):
        from agents.tutor.agent import TutorAgent
        class BadTool(Tool):
            name = "bad"
            consequential = False
            def run(self, args, context=None):
                raise RuntimeError("boom")
        reg = ToolRegistry()
        reg.register(BadTool())
        reg.register(CalculateTool())
        pol = _allow_tool("tutor")
        manifest = {"name": "tutor", "tools": ["bad", "calculate"],
                    "model": {"provider": "ollama", "model": "llama3.1"},
                    "identity": {"role": "tutor"}}
        agent = TutorAgent(router=self._fake_router(), manifest=manifest, tools=reg, policy=pol)
        result = agent.run("hi", {"tool_calls": [
            {"tool": "bad", "args": {}},
            {"tool": "calculate", "args": {"expression": "2+2"}},
        ]})
        self.assertEqual(len(result["tool_results"]), 2)
        self.assertFalse(result["tool_results"][0]["ok"])
        self.assertTrue(result["tool_results"][1]["ok"])
        self.assertEqual(result["tool_results"][1]["result"], 4)


if __name__ == "__main__":
    unittest.main()
