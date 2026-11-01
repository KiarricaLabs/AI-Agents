"""Declarative JSON policy engine. Default deny."""
from __future__ import annotations

import json
from typing import Dict, Any, List


class PolicyEngine:
    def __init__(self, policy: Dict[str, Any]):
        self.policy = policy or {}

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise ValueError("invalid policy")
        return cls(d)

    def allow(self, subject: str, action: str, resource: str) -> bool:
        rules = self.policy.get("rules", [])
        for r in rules:
            if r.get("subject") == subject and r.get("action") == action and r.get("resource") == resource:
                return r.get("effect", "deny") == "allow"
        return False  # default deny