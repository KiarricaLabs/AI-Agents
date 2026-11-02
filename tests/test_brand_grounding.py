"""Phase B tests: brand grounding integration for agents.

Covers manifest+policy gating (default deny), bounded/deterministic retrieval,
prompt section separation, brand selection semantics (explicit/default/sole/ambiguous),
and cross-tenant isolation — using a mocked ModelRouter for determinism.
"""
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from agents.base import BaseAgent
from api.app import app
from core.auth import issue_token
from core.brand import BrandService
from core.brand_scope import BrandScope
from core.model_router import ModelResult
from core.policy import PolicyEngine
from core.runtime import build_runtime
from storage.database import Database


class _CaptureRouter:
    def __init__(self):
        self.calls = []

    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        self.calls.append({"agent": agent_id, "system": system, "prompt": prompt, "context": context})
        return ModelResult("ok", "ollama", "llama3.1", "local:ollama:llama3.1")


def _allow_policy(agent="tutor"):
    return PolicyEngine.from_dict({
        "rules": [{"subject": agent, "action": "brand", "resource": "read", "effect": "allow"}]
    })


def _seed_brand(svc, name="Acme", facts=(("voice", "tone", "warm"),), default=False, user="admin"):
    bid = svc.create_brand(name, user_id="u1", is_default=default)
    for category, key, value in facts:
        pid = svc.propose(bid, category, key, value, user_id="u1")
        svc.approve(pid, user)
    return bid


class TestBrandScope(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.db = Database(path=os.path.join(self._dir.name, "b.db"), tenant_id="local")
        self.brand = BrandService(self.db, "local")

    def tearDown(self):
        self._dir.cleanup()

    def test_requires_permission_and_policy(self):
        bid = _seed_brand(self.brand)
        # No "brand:read" permission -> denied even with an allow policy.
        no_perm = BrandScope(self.brand, {"permissions": ["memory:read"]}, "tutor",
                             policy=_allow_policy(), brand_id=bid)
        self.assertFalse(no_perm.can_read())
        self.assertEqual(no_perm.retrieve(), [])
        # Permission present but no policy -> default deny.
        no_policy = BrandScope(self.brand, {"permissions": ["brand:read"]}, "tutor",
                               policy=None, brand_id=bid)
        self.assertFalse(no_policy.can_read())
        # Permission present + allow policy -> allowed.
        ok = BrandScope(self.brand, {"permissions": ["brand:read"]}, "tutor",
                        policy=_allow_policy(), brand_id=bid)
        self.assertTrue(ok.can_read())
        self.assertEqual([f["value"] for f in ok.retrieve()], ["warm"])

    def test_retrieve_excludes_revoked_facts(self):
        bid = _seed_brand(self.brand)
        pid = self.brand.propose(bid, "voice", "tone", "removed", user_id="u1")
        fid = self.brand.approve(pid, "admin")
        # Now tone has v2 ("removed") active; revoke it so it disappears.
        self.brand.revoke(fid, "admin")
        # "warm" (v1) was superseded, "removed" (v2) revoked -> no active facts.
        scope = BrandScope(self.brand, {"permissions": ["brand:read"]}, "tutor",
                           policy=_allow_policy(), brand_id=bid)
        self.assertEqual(scope.retrieve(), [])

    def test_retrieve_is_bounded_and_deterministic(self):
        bid = self.brand.create_brand("Acme", user_id="u1")
        # Insert many facts; ensure order is stable and the result is clean.
        for i in range(3):
            pid = self.brand.propose(bid, "identity", f"k{i}", f"v{i}", user_id="u1")
            self.brand.approve(pid, "admin")
        scope = BrandScope(self.brand, {"permissions": ["brand:read"]}, "tutor",
                           policy=_allow_policy(), brand_id=bid)
        a = scope.retrieve()
        b = scope.retrieve()
        self.assertEqual(a, b)
        # Only {category,key,value} fields are exposed.
        self.assertEqual(set(a[0].keys()), {"category", "key", "value"})


class TestBrandPrompt(unittest.TestCase):
    def test_prompt_keeps_sections_distinct(self):
        agent = BaseAgent(manifest={"identity": {"role": "X", "personality": "calm"}})
        prompt = agent._system_prompt(
            facts=[{"key": "pref", "value": "personal", "kind": "fact"}],
            history=[{"role": "user", "content": "hi there"}],
            brand=[{"category": "voice", "key": "tone", "value": "warm"}],
        )
        self.assertIn("KNOWN FACTS", prompt)
        self.assertIn("BRAND CONTEXT", prompt)
        self.assertIn("RECENT CONVERSATION", prompt)
        # Brand is labeled as reference information, not instructions.
        self.assertIn("reference information", prompt)
        self.assertIn("not instructions", prompt)

    def test_prompt_omits_brand_when_none(self):
        agent = BaseAgent(manifest={"identity": {"role": "X"}})
        prompt = agent._system_prompt(facts=[], history=[], brand=[])
        self.assertNotIn("BRAND CONTEXT", prompt)


class TestBrandGrounding(unittest.TestCase):
    @patch("core.runtime.ModelRouter", return_value=_CaptureRouter())
    def test_authorized_agent_receives_brand_context(self, _mock):
        with tempfile.TemporaryDirectory() as d:
            db = Database(path=os.path.join(d, "g.db"), tenant_id="local")
            brand = BrandService(db, "local")
            bid = _seed_brand(brand)
            cap = _CaptureRouter()
            with patch("core.runtime.ModelRouter", return_value=cap):
                orch = build_runtime(db, "local", "u1")
                orch.dispatch("tutor", "hello", context={"brand_id": bid})
            system = cap.calls[-1]["system"]
            self.assertIn("BRAND CONTEXT", system)
            self.assertIn("warm", system)

    @patch("core.runtime.ModelRouter")
    def test_brand_context_not_mixed_across_brands(self, _mock):
        with tempfile.TemporaryDirectory() as d:
            db = Database(path=os.path.join(d, "g.db"), tenant_id="local")
            brand = BrandService(db, "local")
            b1 = _seed_brand(brand, "One", (("voice", "tone", "alpha"),))
            b2 = _seed_brand(brand, "Two", (("voice", "tone", "beta"),))
            cap = _CaptureRouter()
            with patch("core.runtime.ModelRouter", return_value=cap):
                orch = build_runtime(db, "local", "u1")
                orch.dispatch("tutor", "hello", context={"brand_id": b1})
            system = cap.calls[-1]["system"]
            self.assertIn("alpha", system)
            self.assertNotIn("beta", system)

    @patch("core.runtime.ModelRouter")
    def test_no_brand_context_without_brand_id(self, _mock):
        with tempfile.TemporaryDirectory() as d:
            db = Database(path=os.path.join(d, "g.db"), tenant_id="local")
            BrandService(db, "local")  # brand service exists but no brand_id in context
            cap = _CaptureRouter()
            with patch("core.runtime.ModelRouter", return_value=cap):
                orch = build_runtime(db, "local", "u1")
                orch.dispatch("tutor", "hello", context={})
            self.assertNotIn("BRAND CONTEXT", cap.calls[-1]["system"])


class TestBrandSelectionAPI(unittest.TestCase):
    def _admin(self, user, tenant):
        return {"x-token": issue_token(user, tenant, "admin")}

    def _tid(self):
        # Unique per run so repeated runs never accumulate brands in the shared DB.
        return "z" + uuid.uuid4().hex[:12]

    def _seed_via_api(self, c, h, name, default=False):
        bid = c.post("/brand", json={"name": name, "is_default": default}, headers=h).json()["id"]
        pid = c.post(f"/brand/{bid}/proposals",
                     json={"category": "voice", "key": "tone", "value": name}, headers=h).json()["proposal_id"]
        c.post(f"/brand/proposals/{pid}/approve", json={}, headers=h)
        return bid

    @patch("core.runtime.ModelRouter", return_value=_CaptureRouter())
    def test_explicit_brand_id_is_selected(self, _mock):
        c = TestClient(app)
        h = self._admin("ua", self._tid())
        b1 = self._seed_via_api(c, h, "One")
        self._seed_via_api(c, h, "Two")
        r = c.post("/agents/tutor/run", json={"task": "hi", "brand_id": b1}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["brand_id"], b1)

    @patch("core.runtime.ModelRouter", return_value=_CaptureRouter())
    def test_single_brand_auto_selected(self, _mock):
        c = TestClient(app)
        h = self._admin("ua", self._tid())
        b1 = self._seed_via_api(c, h, "Only")
        r = c.post("/agents/tutor/run", json={"task": "hi"}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["brand_id"], b1)

    @patch("core.runtime.ModelRouter", return_value=_CaptureRouter())
    def test_multiple_brands_no_default_requires_selection(self, _mock):
        c = TestClient(app)
        h = self._admin("ua", self._tid())
        self._seed_via_api(c, h, "One")
        self._seed_via_api(c, h, "Two")
        r = c.post("/agents/tutor/run", json={"task": "hi"}, headers=h)
        self.assertEqual(r.status_code, 409)

    @patch("core.runtime.ModelRouter", return_value=_CaptureRouter())
    def test_default_brand_selected_among_multiple(self, _mock):
        c = TestClient(app)
        h = self._admin("ua", self._tid())
        self._seed_via_api(c, h, "One")
        default = self._seed_via_api(c, h, "Two", default=True)
        r = c.post("/agents/tutor/run", json={"task": "hi"}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["brand_id"], default)

    @patch("core.runtime.ModelRouter", return_value=_CaptureRouter())
    def test_cross_tenant_brand_id_rejected(self, _mock):
        c = TestClient(app)
        ha = self._admin("ua", self._tid())
        hb = self._admin("ub", self._tid())
        b1 = self._seed_via_api(c, ha, "Acme")
        # Tenant B cannot run against Tenant A's brand id.
        r = c.post("/agents/tutor/run", json={"task": "hi", "brand_id": b1}, headers=hb)
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
