"""Manifest- and policy-gated brand access for agents.

Agents may only *read* approved brand facts that BOTH their manifest declares
(`brand:read`) AND the policy authorizes (`brand:read`). Enforcement is
default-deny. Agents never propose, approve, edit, or revoke brand knowledge
through this path (those require separate, explicit grants).

Retrieval is bounded and deterministic so grounding stays lean and reproducible.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.brand import BrandService

# Deterministic relevance ordering for bounded grounding: identity/positioning/
# voice matter most; the rest follow. Unlisted categories sort after, stably.
CATEGORY_PRIORITY = [
    "identity", "mission", "values", "positioning", "voice", "tone",
    "vocabulary", "guidelines", "audience", "products", "services",
    "objectives", "priorities", "decisions", "restrictions",
]

MAX_BRAND_FACTS = 40


class BrandScope:
    """Resolves and bounds the brand facts an agent is allowed to ground on."""

    def __init__(self, brand: BrandService, manifest: Dict[str, Any], agent_id: str,
                 policy=None, brand_id: Optional[str] = None):
        self.brand = brand
        self.manifest = manifest or {}
        self.agent_id = agent_id
        self.policy = policy
        self.brand_id = brand_id

    def can_read(self) -> bool:
        perms = set(self.manifest.get("permissions", []) or [])
        if "brand:read" not in perms:
            return False
        # Default deny: policy must explicitly allow brand read for this agent.
        return self.policy is not None and bool(self.policy.allow(self.agent_id, "brand", "read"))

    def retrieve(self) -> List[Dict[str, Any]]:
        if not self.can_read() or not self.brand_id:
            return []
        # list_facts returns only current approved facts (proposed/rejected/revoked/
        # superseded are excluded) and is tenant-scoped from the BrandService.
        facts = self.brand.list_facts(self.brand_id)
        return self._bounded(facts)

    def _bounded(self, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def rank(f: Dict[str, Any]) -> int:
            cat = f.get("category", "")
            try:
                return CATEGORY_PRIORITY.index(cat)
            except ValueError:
                return len(CATEGORY_PRIORITY)

        ordered = sorted(
            facts,
            key=lambda f: (rank(f), f.get("key", ""), f.get("value", ""), f.get("id", "")),
        )
        # Expose only the fields the prompt needs; never leak internal ids.
        return [
            {"category": f.get("category", ""), "key": f.get("key", ""), "value": f.get("value", "")}
            for f in ordered[:MAX_BRAND_FACTS]
        ]
