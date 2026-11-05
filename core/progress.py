"""Phase 8 §15 — durable team progress ledger.

Human-visible, tenant/user-scoped record of what each agent is doing relative to
a conversation thread. Agents do NOT self-report via an open endpoint: progress
rows are written by the backend during a human-triggered team run and, where an
agent surfaces a blocker, surfaced to the human. Everything is isolated by
tenant/user and ordered chronologically. This is a passive record — it never
starts, stops, or dispatches work itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

STATUSES = {"working", "completed", "blocked", "message"}


def _now():
    return datetime.now(timezone.utc).isoformat()


class ProgressService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant = tenant_id
        self.user = user_id

    def record(self, thread_id: str, agent_id: str, status: str,
               detail: Optional[str] = None) -> Dict[str, Any]:
        if not thread_id or not agent_id:
            raise ValueError("thread_id and agent_id are required")
        status = (status or "working").lower()
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status}")
        pid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO agent_progress (id,tenant_id,user_id,thread_id,agent_id,status,detail,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, self.tenant, self.user, thread_id, agent_id, status, detail, _now()))
        return {"id": pid, "agent_id": agent_id, "status": status, "thread_id": thread_id}

    def list(self, thread_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT id,thread_id,agent_id,status,detail,created_at FROM agent_progress "
            "WHERE tenant_id=? AND user_id=?" + (" AND thread_id=?" if thread_id else "")
            + " ORDER BY created_at DESC, id DESC LIMIT ?",
            (self.tenant, self.user, *( (thread_id,) if thread_id else () ), limit))
        return rows
