"""Agent execution API + memory identity/tenant-isolation HTTP tests (mocked model)."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token
from core.model_router import ModelResult

ALL_AGENTS = {
    "tutor", "strategist", "executive_assistant",
    "communications", "soundboard", "workspace_architect",
}

_GOOD = ModelResult("hello from test", "ollama", "llama3.1", "local:ollama:llama3.1")


class _FakeRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        return _GOOD


class _SecretRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        return ModelResult("my password is hunter2", "ollama", "llama3.1", "local:ollama:llama3.1")


class TestAgentsApi(unittest.TestCase):
    def test_list_agents(self):
        c = TestClient(app)
        r = c.get("/agents")
        self.assertEqual(r.status_code, 200)
        names = {a["name"] for a in r.json()["agents"]}
        self.assertEqual(names, ALL_AGENTS)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_run_agent_ok(self, _m):
        c = TestClient(app)
        r = c.post("/agents/tutor/run", json={"task": "explain gravity"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["agent"], "tutor")
        self.assertEqual(body["reply"], "hello from test")
        self.assertIn("local:ollama", body["location"])

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_unknown_agent_404(self, _m):
        c = TestClient(app)
        r = c.post("/agents/nope/run", json={"task": "x"})
        self.assertEqual(r.status_code, 404)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_empty_task_422(self, _m):
        c = TestClient(app)
        r = c.post("/agents/tutor/run", json={"task": ""})
        self.assertEqual(r.status_code, 422)

    @patch("core.runtime.ModelRouter", return_value=_SecretRouter())
    def test_secret_output_422(self, _m):
        c = TestClient(app)
        r = c.post("/agents/tutor/run", json={"task": "x"})
        self.assertEqual(r.status_code, 422)

    def test_missing_identity_rejected(self):
        from api.routers.agents import _identity

        class R:
            class state:
                pass

        with self.assertRaises(Exception):
            _identity(R())

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_cross_tenant_memory_isolation(self, _m):
        c = TestClient(app)
        ta = issue_token("ua", "m8A", "admin")
        tb = issue_token("ub", "m8B", "admin")

        # Seed approved profile memory for tenant A only.
        pid = c.post("/memory/proposals",
                     json={"agent_id": "tutor", "kind": "profile", "key": "color",
                           "value": "blue", "confidence": 0.9},
                     headers={"x-token": ta}).json()["proposal_id"]
        c.post(f"/memory/proposals/{pid}/approve", json={}, headers={"x-token": ta})

        ra = c.post("/agents/tutor/run", json={"task": "what do you know about me?"},
                    headers={"x-token": ta}).json()
        self.assertTrue(any(f.get("key") == "color" for f in ra["facts"]))

        rb = c.post("/agents/tutor/run", json={"task": "what do you know about me?"},
                    headers={"x-token": tb}).json()
        self.assertFalse(any(f.get("key") == "color" for f in rb["facts"]))

    def test_memory_approve_cross_tenant_rejected(self):
        c = TestClient(app)
        ta = issue_token("ua", "m8A", "admin")
        tb = issue_token("ub", "m8B", "admin")

        pid = c.post("/memory/proposals",
                     json={"agent_id": "tutor", "kind": "profile", "key": "city",
                           "value": "Oakland", "confidence": 0.9},
                     headers={"x-token": ta}).json()["proposal_id"]

        # Tenant B cannot approve tenant A's proposal (ownership-scoped query).
        r = c.post(f"/memory/proposals/{pid}/approve", json={}, headers={"x-token": tb})
        self.assertEqual(r.status_code, 400)

    def test_memory_profile_tenant_scoped(self):
        c = TestClient(app)
        tb = issue_token("ub", "m8B", "admin")
        # Tenant B sees only its own profile (none of tenant A's "color"/"city").
        r = c.get("/memory/profile", headers={"x-token": tb})
        self.assertEqual(r.status_code, 200)
        keys = [it["key"] for it in r.json()["items"]]
        self.assertNotIn("color", keys)
        self.assertNotIn("city", keys)

    def test_memory_cross_user_same_tenant_isolation(self):
        # Two different users within the same tenant must be isolated by user_id.
        c = TestClient(app)
        t_u1 = issue_token("ua", "m8X", "admin")
        t_u2 = issue_token("ub", "m8X", "admin")

        pid = c.post("/memory/proposals",
                     json={"agent_id": "tutor", "kind": "profile", "key": "pet",
                           "value": "cat", "confidence": 0.9},
                     headers={"x-token": t_u1}).json()["proposal_id"]
        c.post(f"/memory/proposals/{pid}/approve", json={}, headers={"x-token": t_u1})

        # Same-tenant second user does not see the first user's profile memory.
        r = c.get("/memory/profile", headers={"x-token": t_u2})
        keys = [it["key"] for it in r.json()["items"]]
        self.assertNotIn("pet", keys)

        # Same-tenant second user cannot approve the first user's proposal.
        pid2 = c.post("/memory/proposals",
                      json={"agent_id": "tutor", "kind": "profile", "key": "hobby",
                            "value": "chess", "confidence": 0.9},
                      headers={"x-token": t_u1}).json()["proposal_id"]
        r2 = c.post(f"/memory/proposals/{pid2}/approve", json={}, headers={"x-token": t_u2})
        self.assertEqual(r2.status_code, 400)


if __name__ == "__main__":
    unittest.main()
