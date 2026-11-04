"""M11 Fix 1 — agent voice: dual-mode response contract + self-reference."""
from __future__ import annotations

import unittest

from core.runtime import load_registry
from agents.base import BaseAgent


class _FakeRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None, json_format=False):
        raise AssertionError("not used")
    def check_availability(self):
        return {"ok": True}


class TestDualModeVoice(unittest.TestCase):
    def _prompt(self, name):
        reg = load_registry()
        manifest = reg.get(name)
        a = BaseAgent(router=_FakeRouter(), manifest=manifest, user_id="local")
        a.name = name
        return a._system_prompt(facts=[], history=None, brand=[])

    def test_response_style_has_dual_mode(self):
        for name in ("tutor", "strategist", "executive_assistant",
                     "communications", "soundboard", "workspace_architect"):
            p = self._prompt(name)
            self.assertIn("dual mode", p, name)
            self.assertIn("CONVERSING WITH THE USER", p, name)
            self.assertIn("DRAFTING A DELIVERABLE", p, name)
            self.assertIn("polished, professional, ready-to-ship", p, name)

    def test_brandon_refers_to_self_as_communications_manager(self):
        p = self._prompt("communications")
        self.assertIn("communications manager", p)
        # still keeps his identity/role intact
        self.assertIn("Communications Manager", p)
        self.assertIn("Brandon", p)

    def test_identity_still_loaded(self):
        # The dual-mode block must not have suppressed personality identity.
        p = self._prompt("executive_assistant")
        self.assertIn("IDENTITY", p)
        self.assertIn("Taylor", p)


if __name__ == "__main__":
    unittest.main()
