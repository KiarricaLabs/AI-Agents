"""Assemble the M8 agent runtime from existing services.

Single source of truth for wiring the six agents to real local services
(Ollama ModelRouter, MemoryService, ToolRegistry, manifests, policy) without
duplicating orchestration. Local-only; no cloud fallback.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import BASE_DIR
from agents.registry import AgentRegistry
from core.memory import MemoryService
from core.brand import BrandService
from core.model_router import ModelRouter
from core.orchestrator import Orchestrator
from core.policy import PolicyEngine
from core.tools import build_registry

AGENTS_DIR = Path(BASE_DIR) / "agents"


def load_registry() -> AgentRegistry:
    reg = AgentRegistry(str(AGENTS_DIR))
    reg.load()
    return reg


def _manifests(reg: AgentRegistry) -> Dict[str, Dict[str, Any]]:
    return {name: reg.get(name) for name in reg.list()}


def build_local_policy(reg: AgentRegistry) -> PolicyEngine:
    """Manifest-derived, default-deny policy for local mode.

    Grants exactly what each manifest declares: dispatch, its tools, and its
    goal permissions. Anything not declared is denied. This is a convenience
    for local single-user operation and is NOT a substitute for an
    admin-controlled policy in a shared deployment.
    """
    rules: List[Dict[str, Any]] = []
    for name, manifest in _manifests(reg).items():
        rules.append({"subject": "system", "action": "dispatch", "resource": name, "effect": "allow"})
        for tool in manifest.get("tools", []) or []:
            rules.append({"subject": name, "action": "tool", "resource": tool, "effect": "allow"})
        perms = set(manifest.get("permissions", []) or [])
        if "goal:propose" in perms:
            rules.append({"subject": name, "action": "goal", "resource": "propose", "effect": "allow"})
        if "goals:all" in perms:
            rules.append({"subject": name, "action": "goal", "resource": "read_all", "effect": "allow"})
        if "brand:read" in perms:
            rules.append({"subject": name, "action": "brand", "resource": "read", "effect": "allow"})
    return PolicyEngine.from_dict({"rules": rules})


def available_agents(reg: Optional[AgentRegistry] = None) -> List[Dict[str, Any]]:
    reg = reg or load_registry()
    out: List[Dict[str, Any]] = []
    for name in sorted(reg.list()):
        m = reg.get(name)
        identity = m.get("identity", {})
        model_cfg = m.get("model", {}) or {}
        model_name = model_cfg.get("model", "") if isinstance(model_cfg, dict) else str(model_cfg or "")
        out.append({
            "name": name,
            "display_name": identity.get("display_name", name),
            "archetype": identity.get("archetype", ""),
            "role": identity.get("role", name),
            "personality": identity.get("personality", ""),
            "responsibilities": identity.get("responsibilities", ""),
            "capabilities": m.get("capabilities", []),
            "tools": m.get("tools", []),
            "memory": m.get("memory", {}),
            "model": model_name,
        })
    return out


def build_runtime(db, tenant_id: str, user_id: str, policy=None) -> Orchestrator:
    """Return a fully wired Orchestrator for tenant/user, using real services."""
    reg = load_registry()
    memory = MemoryService(db=db, tenant_id=tenant_id)
    brand = BrandService(db=db, tenant_id=tenant_id)
    router = ModelRouter()                       # Ollama only (local)
    tools = build_registry(db=db, tenant_id=tenant_id)
    return Orchestrator(
        registry=reg,
        policy=policy if policy is not None else build_local_policy(reg),
        router=router,
        memory=memory,
        brand=brand,
        user_id=user_id,
        tools=tools,
    )
