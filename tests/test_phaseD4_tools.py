"""D4.3 #3 — read-only tool wiring.

Only ``calculate`` and ``now`` are genuinely implemented (safe read-only tools).
The unimplemented ``web_search``/``email``/``calendar`` capabilities have been
removed from the manifests (capability honesty), so they are never whitelisted
and never declared as available. Tool execution is gated by a server-side
read-only whitelist + manifest + policy + the tool itself.
"""
from __future__ import annotations
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from core.model_router import ModelResult
from core.runtime import load_registry
from core.tools import build_registry
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


class TestCapabilityHonesty(unittest.TestCase):
    """M10 closeout — manifest capability honesty.

    Every tool an agent *declares* in its manifest must have a real registered
    implementation. If an unimplemented capability is ever re-added (e.g.
    ``web_search``, ``email``, ``calendar``), this fails so the agent cannot
    present an unavailable action as available.
    """

    def test_every_declared_tool_is_implemented(self):
        reg = load_registry()
        impl = set(build_registry().list())  # tool names actually registered
        for name in reg.list():
            manifest = reg.get(name)
            declared = set(manifest.get("tools") or [])
            missing = declared - impl
            self.assertEqual(
                missing,
                set(),
                f"Agent '{name}' declares unimplemented tool(s): {sorted(missing)}",
            )

    def test_known_phantom_capabilities_absent(self):
        reg = load_registry()
        forbidden = {"web_search", "email", "calendar"}
        for name in reg.list():
            manifest = reg.get(name)
            declared = set(manifest.get("tools") or [])
            perms = set(manifest.get("permissions") or [])
            self.assertEqual(
                declared & forbidden, set(),
                f"Agent '{name}' re-added a phantom tool: {sorted(declared & forbidden)}",
            )
            self.assertEqual(
                perms & {"tool:" + t for t in forbidden}, set(),
                f"Agent '{name}' re-added a phantom tool permission",
            )

    def test_all_six_manifests_load_and_keep_identity(self):
        reg = load_registry()
        expected = {"tutor", "strategist", "executive_assistant",
                    "communications", "soundboard", "workspace_architect"}
        self.assertEqual(set(reg.list()), expected)
        # Identity fields were not disturbed by the honesty audit.
        for name in reg.list():
            ident = reg.get(name).get("identity") or {}
            for field in ("display_name", "archetype", "role", "personality",
                          "communication_style", "boundaries",
                          "responsibilities", "decision_making",
                          "signature_characteristics"):
                self.assertTrue(
                    str(ident.get(field, "")).strip(),
                    f"Agent '{name}' lost identity field '{field}'",
                )


if __name__ == "__main__":
    unittest.main()
