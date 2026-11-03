"""Unified coordinated-plan preview (D4.3-A1).

This is the thinnest reusable abstraction between a user objective and a
reviewable team plan. It reuses the existing grounded structured-generation
path (via ``Orchestrator.plan``) and NEVER invokes proposal/execution tools or
persists anything: the return value is a transient plan-review document only.

Owner suggestions are derived deterministically from each agent's manifest
capabilities (which ``work_propose_*`` tools it declares), so a suggestion can
never grant a capability beyond what an agent already has.
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional

from core.tools.work_propose import WORK_TOOL_MAP
from core.runtime import load_registry

# Aisha (strategist) is the initial coordinating agent. Not hard-coded forever:
# the coordinator is a constructor/endpoint default so a future heuristic can
# select the coordinator per objective.
DEFAULT_COORDINATOR = "strategist"

# Preference order when several agents can own a work type. Deterministic and
# capability-gated: an agent is only considered if it declares the matching
# ``work_propose_*`` tool.
_OWNER_PREFERENCE = [
    "workspace_architect", "strategist", "executive_assistant",
    "communications", "tutor", "soundboard",
]


class PlanService:
    def __init__(self, orch, tenant_id: str, user_id: str,
                 coordinator: str = DEFAULT_COORDINATOR):
        self.orch = orch
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.coordinator = coordinator
        self._tool_agents = self._build_owner_map()

    @staticmethod
    def _build_owner_map() -> Dict[str, List[str]]:
        reg = load_registry()
        tool_agents: Dict[str, List[str]] = {}
        for slug in reg.list():
            tools = set(reg.get(slug).get("tools", []) or [])
            for tool in tools:
                tool_agents.setdefault(tool, []).append(slug)
        return tool_agents

    def owner_candidates(self, work_type: str, action: str = "create") -> List[str]:
        tool = WORK_TOOL_MAP.get((work_type, action))
        if not tool:
            return []
        candidates = self._tool_agents.get(tool, [])
        return sorted(
            candidates,
            key=lambda a: _OWNER_PREFERENCE.index(a) if a in _OWNER_PREFERENCE else 99,
        )

    def generate(self, objective: str, context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        result = self.orch.plan(self.coordinator, objective, ctx)
        steps: List[Dict[str, Any]] = []
        for s in result.get("steps") or []:
            wt = s.get("work_type")
            if not wt:
                continue
            candidates = self.owner_candidates(wt, s.get("action", "create"))
            steps.append({
                "work_type": wt,
                "action": s.get("action", "create"),
                "title": s.get("title", ""),
                "reason": s.get("reason", ""),
                "suggested_agent": candidates[0] if candidates else None,
                "agent_options": candidates,
                "project_id": ctx.get("project_id"),
                "workspace_id": ctx.get("workspace_id"),
            })
        plan = {
            "coordinator": self.coordinator,
            "objective": objective,
            "reply": result.get("reply", ""),
            "steps": steps,
            "provider": result.get("provider"),
            "model": result.get("model"),
            "location": result.get("location"),
        }
        if result.get("generation_error"):
            plan["generation_error"] = result["generation_error"]
        return plan
