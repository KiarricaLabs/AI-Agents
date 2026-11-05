"""Phase 3 §5-6 — durable agent-to-agent coordination + traceability.

A tenant/user-scoped ledger of agent-to-agent requests/responses that preserves
provenance (the original human conversation ``thread_id``), keeps a traceable
request/response chain, and enforces a loop/depth guard so agents cannot create
uncontrolled coordination loops. It is durable (SQLite) and human-inspectable.

Guards / invariants:
- ``from_agent`` / ``to_agent`` must be recognized agent slugs.
- A ``send`` whose depth would exceed ``MAX_DEPTH`` is NOT persisted as an open
  request; it is recorded as ``blocked`` so the human can see (and the loop is
  stopped). This is the loop guard.
- Every row carries tenant_id/user_id and the originating ``thread_id`` (the
  original human message is the source of intent).
- Responding requires the responder to be the ``to_agent`` of an open message in
  the same tenant/user scope; a response closes the parent.

This service NEVER triggers execution, approval, plan authorization, or any
consequential action — it only records coordination for human visibility and
control.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.team_goal import AGENT_SLUGS

MAX_DEPTH = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentCommService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def _q(self, sql, params=()) -> List[Dict]:
        return [dict(r) for r in self.db.query(sql, params)]

    def send(self, from_agent, to_agent, content, *, kind="request",
             thread_id=None, parent_id=None, depth_hint=None) -> Dict:
        frm = str(from_agent or "").strip().lower()
        to = str(to_agent or "").strip().lower()
        if frm not in AGENT_SLUGS or to not in AGENT_SLUGS:
            raise ValueError("from_agent and to_agent must be recognized agents")
        content = str(content or "").strip()
        if not content:
            raise ValueError("content is required")

        parent_depth = 0
        if parent_id:
            parent = self._q(
                "SELECT * FROM agent_comm_messages WHERE id=? AND tenant_id=? AND user_id=?",
                (parent_id, self.tenant_id, self.user_id))
            if not parent:
                raise ValueError("parent message not found")
            parent_depth = int(parent[0]["depth"] or 0)

        depth = int(depth_hint) if depth_hint is not None else (parent_depth + 1)
        now = _now()
        mid = "comm-" + uuid.uuid4().hex[:12]

        if depth > MAX_DEPTH:
            # loop guard: record a blocked marker, do not open a new request.
            self.db.execute(
                "INSERT INTO agent_comm_messages (id,tenant_id,user_id,thread_id,parent_id,"
                "from_agent,to_agent,kind,content,depth,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, self.tenant_id, self.user_id, thread_id, parent_id, frm, to,
                 kind, content, depth, "blocked", now, now))
            return {"id": mid, "status": "blocked", "depth": depth,
                    "message": f"agent-to-agent depth limit ({MAX_DEPTH}) exceeded; blocked"}

        self.db.execute(
            "INSERT INTO agent_comm_messages (id,tenant_id,user_id,thread_id,parent_id,"
            "from_agent,to_agent,kind,content,depth,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, self.tenant_id, self.user_id, thread_id, parent_id, frm, to,
             kind, content, depth, "open", now, now))
        return {"id": mid, "status": "open", "depth": depth}

    def respond(self, comm_id: str, from_agent: str, content: str) -> Dict:
        frm = str(from_agent or "").strip().lower()
        if frm not in AGENT_SLUGS:
            raise ValueError("responder must be a recognized agent")
        rows = self._q(
            "SELECT * FROM agent_comm_messages WHERE id=? AND tenant_id=? AND user_id=? "
            "AND status='open'",
            (comm_id, self.tenant_id, self.user_id))
        if not rows:
            raise ValueError("open request not found")
        target = rows[0]
        if target["to_agent"] != frm:
            raise ValueError(f"only {target['to_agent']} may respond to {comm_id}")
        content = str(content or "").strip()
        if not content:
            raise ValueError("content is required")

        now = _now()
        rid = "comm-" + uuid.uuid4().hex[:12]
        child_depth = int(target["depth"] or 0) + 1
        status = "open" if child_depth <= MAX_DEPTH else "blocked"
        self.db.execute(
            "INSERT INTO agent_comm_messages (id,tenant_id,user_id,thread_id,parent_id,"
            "from_agent,to_agent,kind,content,depth,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, self.tenant_id, self.user_id, target["thread_id"], comm_id, frm,
             target["from_agent"], "response", content, child_depth, status, now, now))
        self.db.execute(
            "UPDATE agent_comm_messages SET status='responded', updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (now, comm_id, self.tenant_id, self.user_id))
        return {"id": rid, "parent_id": comm_id, "status": status, "depth": child_depth}

    def list(self, thread_id: Optional[str] = None) -> List[Dict]:
        if thread_id:
            return self._q(
                "SELECT * FROM agent_comm_messages WHERE tenant_id=? AND user_id=? "
                "AND thread_id=? ORDER BY created_at ASC, id ASC",
                (self.tenant_id, self.user_id, thread_id))
        return self._q(
            "SELECT * FROM agent_comm_messages WHERE tenant_id=? AND user_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT 200",
            (self.tenant_id, self.user_id))

    def blocked(self) -> List[Dict]:
        """Loop-guard blocks surfaced to the human (and the Review Center)."""
        return self._q(
            "SELECT * FROM agent_comm_messages WHERE tenant_id=? AND user_id=? "
            "AND status='blocked' ORDER BY created_at DESC",
            (self.tenant_id, self.user_id))

    def mark_resolved(self, comm_id: str) -> Dict:
        """Human/flow resolves a coordination thread entry (no execution)."""
        rows = self._q(
            "SELECT * FROM agent_comm_messages WHERE id=? AND tenant_id=? AND user_id=?",
            (comm_id, self.tenant_id, self.user_id))
        if not rows:
            raise ValueError("message not found")
        self.db.execute(
            "UPDATE agent_comm_messages SET status='resolved', updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (_now(), comm_id, self.tenant_id, self.user_id))
        return {"id": comm_id, "status": "resolved"}
