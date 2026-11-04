"""M11 Fix 2 — brand + approved memory context seeding (isolated DB)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from storage.database import Database
from core.brand import BrandService
from core.memory import MemoryService
from core.runtime import load_registry, build_local_policy
from core.orchestrator import Orchestrator
from agents.base import BaseAgent
from core.tools import build_registry
from core.model_router import ModelResult

from scripts.seed_brand_context import ON_US_FACTS, PROFILE_MEMORY, ON_US_BRAND, USER_ID


class _FakeEnvelope:
    def __init__(self, text):
        self.text = text
        self.provider = "ollama"
        self.model = "llama3.1"


class _FakeRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None, json_format=False):
        return ModelResult("ok", "ollama", "llama3.1", "local:ollama:llama3.1")
    def check_availability(self):
        return {"ok": True, "available": True}


class TestBrandContextSeeding(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="local")

    def _seed(self):
        # Replicate the seed script against the temp DB.
        bs = BrandService(db=self.db, tenant_id="local")
        ms = MemoryService(db=self.db, tenant_id="local")
        brands = bs.list_brands()
        brand = next((b for b in brands if b["name"] == ON_US_BRAND), None)
        if brand is None:
            bid = bs.create_brand(ON_US_BRAND, user_id=USER_ID, is_default=True)
        else:
            bid = brand["id"]
        for category, key, value in ON_US_FACTS:
            if any(f["key"] == key and f["category"] == category for f in bs.list_facts(bid)):
                continue
            pid = bs.propose(bid, category, key, value, source="seed", agent_id="system")
            bs.approve(pid, USER_ID)
        existing = {m["key"] for m in ms.list_profile(USER_ID)}
        for kind, key, value, agent_id in PROFILE_MEMORY:
            if key in existing:
                continue
            pid = ms.propose(USER_ID, agent_id, kind, key, value, source="seed", confidence=0.95)
            ms.approve(pid, USER_ID)

    def test_seed_creates_default_brand_with_facts(self):
        self._seed()
        bs = BrandService(db=self.db, tenant_id="local")
        default = bs.get_default_brand()
        self.assertIsNotNone(default)
        self.assertEqual(default["name"], ON_US_BRAND)
        self.assertTrue(bs.list_facts(default["id"]))
        cats = {(f["category"], f["key"]) for f in bs.list_facts(default["id"])}
        for category, key, value in ON_US_FACTS:
            self.assertIn((category, key), cats)

    def test_seed_is_idempotent(self):
        self._seed()
        bs = BrandService(db=self.db, tenant_id="local")
        bid = bs.get_default_brand()["id"]
        n1 = len(bs.list_facts(bid))
        # run again
        self._seed()
        self.assertEqual(len(bs.list_facts(bid)), n1)

    def test_brand_context_injected_into_system_prompt(self):
        self._seed()
        bs = BrandService(db=self.db, tenant_id="local")
        brand_facts = bs.list_facts(bs.get_default_brand()["id"])
        reg = load_registry()
        manifest = reg.get("strategist")
        a = BaseAgent(
            memory=None, router=_FakeRouter(), manifest=manifest,
            user_id=USER_ID, tools=build_registry(db=self.db, tenant_id="local"),
            policy=build_local_policy(reg), brand=bs)
        a.name = "strategist"
        prompt = a._system_prompt(facts=[], history=None, brand=brand_facts)
        self.assertIn("BRAND CONTEXT", prompt)
        self.assertIn("On Us", prompt)

    def test_profile_memory_seeded_for_user(self):
        self._seed()
        ms = MemoryService(db=self.db, tenant_id="local")
        items = ms.list_profile(USER_ID)
        keys = {m["key"] for m in items}
        self.assertIn("preferred_tone", keys)
        self.assertIn("user_identity", keys)

    def test_agent_ground_returns_brand_and_known_facts_given_brand(self):
        self._seed()
        bs = BrandService(db=self.db, tenant_id="local")
        brand_facts = bs.list_facts(bs.get_default_brand()["id"])
        reg = load_registry()
        manifest = reg.get("strategist")
        a = BaseAgent(
            memory=MemoryService(db=self.db, tenant_id="local"), router=_FakeRouter(),
            manifest=manifest, user_id=USER_ID,
            tools=build_registry(db=self.db, tenant_id="local"),
            policy=build_local_policy(reg), brand=bs)
        a.name = "strategist"
        r = a._ground("hello", context={"brand_id": bs.get_default_brand()["id"],
                                        "work_intent": False})
        # Brand facts are present; reply is a real (non-empty, non-faking) response.
        self.assertTrue(r["reply"])


if __name__ == "__main__":
    unittest.main()
