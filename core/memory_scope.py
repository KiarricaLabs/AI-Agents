"""Manifest-scoped memory access for agents.

Enforces each agent's manifest `memory.read`/`write` and `permissions`,
grounds retrieval in tenant/user isolation, and audits retrievals without
leaking memory contents. Agents may only *propose* shared profile memory —
never approve, reject, or revoke.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.memory import MemoryService


class ScopedMemory:
    def __init__(self, memory: MemoryService, manifest: Dict[str, Any], agent_id: str, user_id: str,
                 policy=None):
        self.memory = memory
        self.manifest = manifest or {}
        self.agent_id = agent_id
        self.user_id = user_id
        self.policy = policy

    def read_categories(self) -> List[str]:
        return list(self.manifest.get("memory", {}).get("read", []) or [])

    def write_categories(self) -> List[str]:
        return list(self.manifest.get("memory", {}).get("write", []) or [])

    def permissions(self) -> List[str]:
        return list(self.manifest.get("permissions", []) or [])

    def can_propose(self) -> bool:
        # "memory:propose" is the exclusive gate for shared profile-memory proposals.
        return "memory:propose" in self.permissions()

    def retrieve(self) -> List[Dict[str, Any]]:
        """Return manifest-authorized, tenant/user-scoped facts (no internals)."""
        facts: List[Dict[str, Any]] = []
        used: List[str] = []
        for category in self.read_categories():
            if category == "profile":
                for row in self.memory.list_profile(self.user_id):
                    facts.append(self._clean(row, "profile"))
                used.append("profile")
            elif category == "notes":
                for row in self.memory.get_private(self.agent_id, self.user_id):
                    facts.append(self._clean(row, "notes"))
                used.append("notes")
            elif category == "goals":
                for row in self._goal_rows():
                    facts.append(self._clean_goal(row))
                used.append("goals")
            # any other categories are deferred/unknown and skipped safely.
        self.memory.record_retrieval(self.user_id, self.agent_id, used)
        return facts

    def _goal_rows(self) -> List[Dict[str, Any]]:
        from core.workspace import GoalService
        gs = GoalService(self.memory.db, self.memory.tenant_id, self.user_id)
        if self._can_read_all_goals():
            return gs.list_all()
        return gs.list_assigned(self.agent_id)

    def _can_read_all_goals(self) -> bool:
        if "goals:all" not in self.permissions():
            return False
        return self.policy is not None and bool(self.policy.allow(self.agent_id, "goal", "read_all"))

    def propose(
        self,
        kind: str,
        key: str,
        value: str,
        reason: Optional[str] = None,
        context: Optional[str] = None,
        source: str = "conversation",
        confidence: float = 0.5,
        expires_at: Optional[str] = None,
    ) -> str:
        if not self.can_propose():
            raise PermissionError(
                f"Agent '{self.agent_id}' lacks 'memory:propose' permission."
            )
        return self.memory.propose(
            user_id=self.user_id,
            agent_id=self.agent_id,
            kind=kind,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            expires_at=expires_at,
            reason=reason,
            context=context,
        )

    @staticmethod
    def _clean(row: Dict[str, Any], category: str) -> Dict[str, Any]:
        return {
            "category": category,
            "kind": row.get("kind", ""),
            "key": row.get("key", ""),
            "value": row.get("value", ""),
        }

    @staticmethod
    def _clean_goal(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "category": "goals",
            "kind": "goal",
            "key": f"goal:{row.get('title', '')}",
            "value": (f"priority={row.get('priority', 0)} "
                      f"status={row.get('status', 'open')} "
                      f"progress={row.get('progress', 0)}%"),
        }

    @staticmethod
    def format_facts(facts: List[Dict[str, Any]]) -> List[str]:
        return [f"{f['key']}: {f['value']}" for f in facts if f.get("key")]
