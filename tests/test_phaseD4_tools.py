"""D4.3 #3 — read-only tool wiring.

Only ``calculate`` and ``now`` are genuinely implemented (safe read-only tools).
``web_search``/``email``/``calendar`` are declared in manifests but have no
implementation, so they are intentionally not whitelisted. Tool execution is
gated by a server-side read-only whitelist + manifest + policy + the tool itself.
"""
from __future__ import annotations
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from core.model_router import ModelResult
from api.app import app


class _GoodRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None, json_format=False):
        return ModelResult("all good", "ollama", "llama3.1", "local:ollama:llama3.1")
    def check_availability(self):
        return {"ok": True, "available": True, "provider": "ollama", "model": "m",
                "location": "local:ollama:m", "code": "ok"}


class TestReadonlyToolWiring(unittest.TestCase):
    def _run(self, agent, body):
        with patch("core.runtime.ModelRouter", return_value=_GoodRouter()):
            return TestClient(app).post(f"/agents/{agent}/run", json=body)

    def test_calculate_executes_for_tutor(self):
        r = self._run("tutor", {
            "task": "compute",
            "tool_calls": [{"tool": "calculate", "args": {"expression": "17*23"}}],
        })
        self.assertEqual(r.status_code, 200)
        results = r.json().get("tool_results", [])
        calc = [x for x in results if x.get("tool") == "calculate"]
        self.assertTrue(calc, "calculate tool_result missing")
        self.assertTrue(calc[0]["ok"])
        self.assertEqual(calc[0]["result"], 391)

    def test_non_whitelisted_tool_is_dropped(self):
        r = self._run("tutor", {
            "task": "do it",
            "tool_calls": [
                {"tool": "web_search", "args": {"q": "x"}},
                {"tool": "work_propose_goal", "args": {"payload": {"title": "Hack", "project_id": "p"}}},
            ],
        })
        self.assertEqual(r.status_code, 200)
        tools = [x.get("tool") for x in r.json().get("tool_results", [])]
        self.assertNotIn("web_search", tools)
        self.assertNotIn("work_propose_goal", tools)  # never a proposal via this path

    def test_tool_not_in_agent_manifest_is_honest_failure(self):
        # communications does not declare calculate -> manifest gate produces an
        # honest per-tool failure, never a crash or a fabricated success.
        r = self._run("communications", {
            "task": "compute",
            "tool_calls": [{"tool": "calculate", "args": {"expression": "2+2"}}],
        })
        self.assertEqual(r.status_code, 200)
        calc = [x for x in r.json().get("tool_results", []) if x.get("tool") == "calculate"]
        self.assertTrue(calc)
        self.assertFalse(calc[0]["ok"])

    def test_now_executes_for_executive_assistant(self):
        r = self._run("executive_assistant", {
            "task": "time",
            "tool_calls": [{"tool": "now", "args": {}}],
        })
        self.assertEqual(r.status_code, 200)
        now = [x for x in r.json().get("tool_results", []) if x.get("tool") == "now"]
        self.assertTrue(now and now[0]["ok"])

    def test_invalid_calculate_expression_is_safe(self):
        r = self._run("tutor", {
            "task": "compute",
            "tool_calls": [{"tool": "calculate", "args": {"expression": "1/0"}}],
        })
        self.assertEqual(r.status_code, 200)
        calc = [x for x in r.json().get("tool_results", []) if x.get("tool") == "calculate"]
        self.assertFalse(calc[0]["ok"])


if __name__ == "__main__":
    unittest.main()
