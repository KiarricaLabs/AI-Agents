"""Privacy-bounded memory analytics (aggregates only)."""
from __future__ import annotations
from typing import Dict, Any
from storage.database import Database


class MemoryAnalytics:
    def __init__(self, db: Database, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    def usage_stats(self, user_id: str) -> Dict[str, Any]:
        profile = self.db.query("SELECT COUNT(*) as c FROM memory_items WHERE tenant_id=? AND user_id=?", (self.tenant_id, user_id))
        conv = self.db.query("SELECT COUNT(*) as c FROM conversation_memory WHERE tenant_id=? AND user_id=?", (self.tenant_id, user_id))
        priv = self.db.query("SELECT COUNT(*) as c FROM agent_private_memory WHERE tenant_id=? AND user_id=?", (self.tenant_id, user_id))
        return {
            "profile_count": profile[0]["c"] if profile else 0,
            "conversation_count": conv[0]["c"] if conv else 0,
            "private_count": priv[0]["c"] if priv else 0,
        }

    def proposal_rates(self, user_id: str) -> Dict[str, Any]:
        rows = self.db.query("SELECT status, COUNT(*) as c FROM memory_proposals WHERE tenant_id=? AND user_id=? GROUP BY status",
                             (self.tenant_id, user_id))
        rates = {r["status"]: r["c"] for r in rows}
        total = sum(rates.values())
        approved = rates.get("approved", 0) + rates.get("edited", 0)
        rejected = rates.get("rejected", 0)
        return {"total": total, "approved": approved, "rejected": rejected,
                "approval_rate": (approved / total) if total else 0.0}

    def confidence_trend(self, user_id: str) -> Dict[str, Any]:
        rows = self.db.query("SELECT AVG(confidence) as avg_conf FROM memory_proposals WHERE tenant_id=? AND user_id=?",
                             (self.tenant_id, user_id))
        avg = rows[0]["avg_conf"] if rows and rows[0]["avg_conf"] is not None else 0.0
        return {"avg_confidence": avg}

    def lifecycle_stats(self, user_id: str) -> Dict[str, Any]:
        rows = self.db.query("SELECT status, COUNT(*) as c FROM memory_proposals WHERE tenant_id=? AND user_id=? GROUP BY status",
                             (self.tenant_id, user_id))
        return {r["status"]: r["c"] for r in rows}