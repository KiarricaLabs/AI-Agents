"""MemoryService - controlled interface for personal intelligence memory."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from storage.database import Database

SENSITIVE_KEYWORDS = ["password", "secret", "token", "api_key", "ssn"]
TEMPORARY_KEYWORDS = ["today", "right now", "just", "temporary"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _is_sensitive(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SENSITIVE_KEYWORDS)


def _is_temporary(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in TEMPORARY_KEYWORDS)


class MemoryService:
    def __init__(self, db: Database, tenant_id: str = None):
        self.db = db
        self.tenant_id = tenant_id or db.default_tenant

    def _audit(self, user_id, agent_id, action, target_id=None, detail=None):
        self.db.execute(
            "INSERT INTO memory_audit (id,tenant_id,user_id,agent_id,action,target_id,detail,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, user_id, agent_id, action, target_id, detail, _now()))

    def record_retrieval(self, user_id: str, agent_id: str, categories: List[str]):
        """Audit a memory retrieval without recording any memory contents."""
        cats = ",".join(categories or [])
        self._audit(user_id, agent_id, "retrieve", None, f"categories={cats}")

    # --- Profile memory (shared, approved only) ---
    def list_profile(self, user_id: str, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM memory_items WHERE tenant_id=? AND user_id=? AND kind='profile'",
            (self.tenant_id, user_id))
        return rows

    # --- Conversation memory (episodic, never auto-promoted) ---
    def add_conversation(self, user_id: str, content: str, role: str = "user", thread_id: Optional[str] = None, turn_id: Optional[str] = None):
        self.db.execute(
            "INSERT INTO conversation_memory (id,tenant_id,user_id,thread_id,role,content,created_at,turn_id) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, user_id, thread_id, role, content, _now(), turn_id))

    def add_conversation_pair(self, user_id: str, thread_id: str, user_content: str, assistant_content: str, turn_id: Optional[str] = None):
        """Atomically persist user+assistant messages for one turn."""
        with self.db.transaction_immediate() as c:
            c.row_factory = __import__("sqlite3").Row
            # check existing
            if turn_id:
                rows = c.execute(
                    "SELECT role, content FROM conversation_memory WHERE tenant_id=? AND user_id=? AND thread_id=? AND turn_id=?",
                    (self.tenant_id, user_id, thread_id, turn_id)).fetchall()
                if rows:
                    # validate exact pair
                    existing = {(r["role"], r["content"]) for r in rows}
                    expected = {("user", user_content), ("assistant", assistant_content)}
                    if existing != expected:
                        raise RuntimeError("conflicting conversation pair for turn_id")
                    if len(rows) != 2:
                        raise RuntimeError("partial conversation pair for turn_id")
                    return
            now = _now()
            c.execute(
                "INSERT INTO conversation_memory (id,tenant_id,user_id,thread_id,role,content,created_at,turn_id) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, user_id, thread_id, "user", user_content, now, turn_id))
            c.execute(
                "INSERT INTO conversation_memory (id,tenant_id,user_id,thread_id,role,content,created_at,turn_id) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, user_id, thread_id, "assistant", assistant_content, now, turn_id))
            # touch thread
            c.execute(
                "UPDATE conversation_threads SET updated_at=? WHERE thread_id=? AND tenant_id=? AND user_id=?",
                (now, thread_id, self.tenant_id, user_id))

    def list_conversation(self, user_id: str, thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
        # Deterministic chronological order; `id` breaks ties on equal timestamps.
        order = " ORDER BY created_at ASC, id ASC"
        if thread_id:
            return self.db.query(
                "SELECT * FROM conversation_memory WHERE tenant_id=? AND user_id=? AND thread_id=?" + order,
                (self.tenant_id, user_id, thread_id))
        return self.db.query(
            "SELECT * FROM conversation_memory WHERE tenant_id=? AND user_id=?" + order,
            (self.tenant_id, user_id))

    # --- Conversation thread metadata (persistent, agent-associated) ---
    def get_or_create_thread(self, user_id: str, thread_id: str, agent_id: Optional[str], first_message: str):
        """Create a thread record on first use (auto-title from the first user
        message). Idempotent: existing rows are returned untouched so a manual
        rename is never overwritten."""
        rows = self.db.query(
            "SELECT * FROM conversation_threads WHERE thread_id=? AND tenant_id=? AND user_id=?",
            (thread_id, self.tenant_id, user_id))
        if rows:
            return rows[0]
        title = (first_message or "New conversation").strip().replace("\n", " ")
        if len(title) > 60:
            title = title[:60].rstrip() + "…"
        now = _now()
        self.db.execute(
            "INSERT INTO conversation_threads "
            "(thread_id,tenant_id,user_id,agent_id,title,is_renamed,created_at,updated_at) "
            "VALUES (?,?,?,?,?,0,?,?)",
            (thread_id, self.tenant_id, user_id, agent_id, title, now, now))
        return self.db.query(
            "SELECT * FROM conversation_threads WHERE thread_id=? AND tenant_id=? AND user_id=?",
            (thread_id, self.tenant_id, user_id))[0]

    def touch_thread(self, user_id: str, thread_id: str):
        """Bump last-activity on a resumed thread without changing its title."""
        self.db.execute(
            "UPDATE conversation_threads SET updated_at=? "
            "WHERE thread_id=? AND tenant_id=? AND user_id=?",
            (_now(), thread_id, self.tenant_id, user_id))

    def rename_thread(self, user_id: str, thread_id: str, title: str):
        """Rename an owned thread. Returns True on success; False when no owned
        thread matches (foreign or nonexistent). Never creates a thread as a side
        effect of renaming. Ownership comes from the authenticated identity only,
        so a foreign/nonexistent thread returns False and the API responds 404
        without revealing whether another user's thread exists."""
        display = (title or "").strip()[:60]
        if not display:
            display = "Conversation"
        rows = self.db.query(
            "SELECT thread_id FROM conversation_threads WHERE thread_id=? AND tenant_id=? AND user_id=?",
            (thread_id, self.tenant_id, user_id))
        if not rows:
            return False
        now = _now()
        self.db.execute(
            "UPDATE conversation_threads SET title=?, is_renamed=1, updated_at=? "
            "WHERE thread_id=? AND tenant_id=? AND user_id=?",
            (display, now, thread_id, self.tenant_id, user_id))
        return True

    def list_threads(self, user_id: str) -> List[Dict[str, Any]]:
        """The conversation browser: every thread the user has, joined with persisted
        metadata. Threads that predate thread metadata surface with agent_id=None
        (displayed as 'Agent unknown') and an auto-derived title."""
        rows = self.db.query(
            "SELECT t.thread_id,"
            "       ct.agent_id AS agent_id,"
            "       ct.title    AS meta_title,"
            "       ct.is_renamed AS is_renamed,"
            "       COUNT(t.id) AS message_count,"
            "       MAX(t.created_at) AS last_activity "
            "FROM conversation_memory t "
            "LEFT JOIN conversation_threads ct "
            "  ON ct.thread_id = t.thread_id AND ct.tenant_id = t.tenant_id AND ct.user_id = t.user_id "
            "WHERE t.tenant_id = ? AND t.user_id = ? AND t.thread_id IS NOT NULL "
            "GROUP BY t.thread_id ORDER BY last_activity DESC",
            (self.tenant_id, user_id))
        out = []
        for r in rows:
            if r["meta_title"]:
                title = r["meta_title"]
            else:
                sub = self.db.query(
                    "SELECT content FROM conversation_memory WHERE tenant_id=? AND user_id=? "
                    "AND thread_id=? AND role='user' ORDER BY created_at ASC, id ASC LIMIT 1",
                    (self.tenant_id, user_id, r["thread_id"]))
                title = (sub[0]["content"] if sub else "Untitled conversation").strip().replace("\n", " ")
                if len(title) > 60:
                    title = title[:60].rstrip() + "…"
            out.append({
                "thread_id": r["thread_id"],
                "agent_id": r["agent_id"],
                "title": title,
                "is_renamed": bool(r["is_renamed"]),
                "last_activity": r["last_activity"],
                "message_count": r["message_count"],
            })
        return out

    # --- Agent-private memory ---
    def set_private(self, agent_id: str, user_id: str, key: str, value: str, kind: str = "note"):
        # upsert
        existing = self.db.query(
            "SELECT id FROM agent_private_memory WHERE tenant_id=? AND agent_id=? AND user_id=? AND key=?",
            (self.tenant_id, agent_id, user_id, key))
        if existing:
            self.db.execute(
                "UPDATE agent_private_memory SET value=?, updated_at=? WHERE id=?",
                (value, _now(), existing[0]["id"]))
        else:
            self.db.execute(
                "INSERT INTO agent_private_memory (id,tenant_id,agent_id,user_id,kind,key,value,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, agent_id, user_id, kind, key, value, _now(), _now()))

    def get_private(self, agent_id: str, user_id: str, key: Optional[str] = None) -> List[Dict[str, Any]]:
        if key:
            return self.db.query(
                "SELECT * FROM agent_private_memory WHERE tenant_id=? AND agent_id=? AND user_id=? AND key=?",
                (self.tenant_id, agent_id, user_id, key))
        return self.db.query(
            "SELECT * FROM agent_private_memory WHERE tenant_id=? AND agent_id=? AND user_id=?",
            (self.tenant_id, agent_id, user_id))

    def read_private(self, requester_agent: str, owner_agent: str, user_id: str, permission: bool = False):
        if requester_agent != owner_agent and not permission:
            raise PermissionError("Agent private memory access denied.")
        return self.get_private(owner_agent, user_id)

    # --- Proposals ---
    def propose(self, user_id: str, agent_id: str, kind: str, key: str, value: str,
                source: str = "conversation", confidence: float = 0.5,
                expires_at: Optional[str] = None,
                reason: Optional[str] = None, context: Optional[str] = None) -> str:
        if _is_sensitive(f"{key} {value} {reason or ''} {context or ''}"):
            raise ValueError("Sensitive content cannot be proposed as profile memory.")
        if _is_temporary(f"{key} {value}") and confidence < 0.9:
            raise ValueError("Temporary content requires high confidence.")
        if confidence < 0.3:
            raise ValueError("Confidence too low to propose.")
        pid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO memory_proposals (id,tenant_id,user_id,agent_id,kind,key,value,source,reason,context,confidence,status,expires_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, self.tenant_id, user_id, agent_id, kind, key, value, source, reason, context,
             confidence, "proposed", expires_at, _now()))
        self._audit(user_id, agent_id, "propose", pid, f"{kind}:{key}")
        return pid

    def approve(self, proposal_id: str, user_id: str, edited_value: Optional[str] = None):
        rows = self.db.query(
            "SELECT * FROM memory_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (proposal_id, self.tenant_id, user_id))
        if not rows:
            raise ValueError("proposal not found")
        p = rows[0]
        value = edited_value if edited_value is not None else p["value"]
        # promote to profile memory
        self.db.execute(
            "INSERT INTO memory_items (id,tenant_id,user_id,owner,kind,key,value,source,confidence,expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, user_id, "user", "profile", p["key"], value,
             p["source"], p["confidence"], p["expires_at"], _now(), _now()))
        status = "edited" if edited_value is not None else "approved"
        self.db.execute(
            "UPDATE memory_proposals SET status=?, decided_at=? WHERE id=?",
            (status, _now(), proposal_id))
        self._audit(user_id, p["agent_id"], status, proposal_id, p["key"])

    def reject(self, proposal_id: str, user_id: str):
        rows = self.db.query(
            "SELECT * FROM memory_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (proposal_id, self.tenant_id, user_id))
        if not rows:
            raise ValueError("proposal not found")
        self.db.execute(
            "UPDATE memory_proposals SET status='rejected', decided_at=? WHERE id=?",
            (_now(), proposal_id))
        self._audit(user_id, rows[0]["agent_id"], "reject", proposal_id, rows[0]["key"])

    def revoke(self, memory_item_id: str, user_id: str):
        rows = self.db.query(
            "SELECT * FROM memory_items WHERE id=? AND tenant_id=? AND user_id=?",
            (memory_item_id, self.tenant_id, user_id))
        if not rows:
            raise ValueError("memory item not found")
        self.db.execute("DELETE FROM memory_items WHERE id=?", (memory_item_id,))
        self._audit(user_id, None, "revoke", memory_item_id, rows[0]["key"])

    def expire_proposals(self):
        now = _now()
        rows = self.db.query(
            "SELECT id FROM memory_proposals WHERE tenant_id=? AND status='proposed' AND expires_at IS NOT NULL AND expires_at < ?",
            (self.tenant_id, now))
        for r in rows:
            self.db.execute(
                "UPDATE memory_proposals SET status='expired', decided_at=? WHERE id=?",
                (now, r["id"]))
        return len(rows)

    def list_proposals(self, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status:
            return self.db.query(
                "SELECT * FROM memory_proposals WHERE tenant_id=? AND user_id=? AND status=?",
                (self.tenant_id, user_id, status))
        return self.db.query(
            "SELECT * FROM memory_proposals WHERE tenant_id=? AND user_id=?",
            (self.tenant_id, user_id))

    def audit_history(self, user_id: str) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM memory_audit WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC",
            (self.tenant_id, user_id))