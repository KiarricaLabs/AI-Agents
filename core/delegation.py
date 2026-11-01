"""DelegationService with permission intersection and depth limits."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from storage.database import Database

MAX_DEPTH = 3


def _now():
    return datetime.now(timezone.utc).isoformat()


class DelegationService:
    def __init__(self, db: Database, tenant_id: str, manifests: Dict[str, Any]):
        self.db = db
        self.tenant_id = tenant_id
        self.manifests = manifests

    def _perms(self, agent):
        return set(self.manifests.get(agent, {}).get("permissions", []))

    def can_delegate(self, from_agent, to_agent, depth=0):
        if depth >= MAX_DEPTH:
            return False, "depth limit"
        m_from = self.manifests.get(from_agent, {})
        if to_agent not in m_from.get("delegates_to", []):
            return False, "not declared"
        m_to = self.manifests.get(to_agent, {})
        if from_agent not in m_to.get("delegated_from", []):
            return False, "not allowed"
        # circular check
        if from_agent == to_agent:
            return False, "circular"
        eff = self._perms(from_agent) & self._perms(to_agent)
        return True, eff

    def delegate(self, from_agent, to_agent, task, depth=0):
        ok, info = self.can_delegate(from_agent, to_agent, depth)
        outcome = "denied" if not ok else "allowed"
        eff = info if ok else set()
        self.db.execute(
            "INSERT INTO delegation_log (id,tenant_id,from_agent,to_agent,effective_perms,outcome,created_at) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, from_agent, to_agent, json.dumps(sorted(eff)), outcome, _now()))
        if not ok:
            raise PermissionError(info)
        return {"from": from_agent, "to": to_agent, "effective_perms": sorted(eff), "task": task}