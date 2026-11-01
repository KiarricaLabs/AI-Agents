"""TaskService with retry safety, cancellation, tenant/user ownership."""
from __future__ import annotations

import json
import uuid
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable

from storage.database import Database

SECRET_KEYS = {"password", "secret", "token", "api_key", "master_key"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _valid_payload(payload):
    if not isinstance(payload, dict):
        return False
    for k in payload:
        if k.lower() in SECRET_KEYS:
            return False
    return True


class TaskService:
    def __init__(self, db: Database, tenant_id: str, user_id: str, executor: Optional[Callable] = None, policy=None):
        self.policy = policy
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.executor = executor
        self._lock = threading.Lock()

    def _event(self, task_id, status, detail=None):
        self.db.execute(
            "INSERT INTO task_events (id,tenant_id,task_id,status,detail,created_at) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, task_id, status, detail, _now()))

    def create(self, agent_id: str, payload: Dict[str, Any]) -> str:
        if not _valid_payload(payload):
            raise ValueError("Invalid or secret-containing payload.")
        tid = str(uuid.uuid4())
        now = _now()
        self.db.execute(
            "INSERT INTO tasks (id,tenant_id,user_id,agent_id,status,payload_json,attempts,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, self.tenant_id, self.user_id, agent_id, "queued", json.dumps(payload), 0, now, now))
        self._event(tid, "queued")
        return tid

    def _get(self, task_id: str):
        rows = self.db.query(
            "SELECT * FROM tasks WHERE id=? AND tenant_id=? AND user_id=?",
            (task_id, self.tenant_id, self.user_id))
        return rows[0] if rows else None

    def get(self, task_id: str):
        return self._get(task_id)

    def cancel(self, task_id: str) -> bool:
        t = self._get(task_id)
        if not t:
            return False
        if t["status"] in ("done", "cancelled"):
            return False
        now = _now()
        self.db.execute(
            "UPDATE tasks SET status='cancelled', cancelled_at=?, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
            (now, now, task_id, self.tenant_id, self.user_id))
        self._event(task_id, "cancelled")
        return True

    def run(self, task_id: str) -> Dict[str, Any]:
        from core.tracing import start_span, end_span
        span = start_span("task.run", {"task_id": task_id})
        with self._lock:
            t = self._get(task_id)
            if not t:
                raise ValueError("task not found")
            if t["status"] == "cancelled":
                return {"ok": False, "error": "cancelled"}
            if self.policy is None:
                return {"ok": False, "error": "policy denied"}
            if not self.policy.allow(t["agent_id"], "execute", "task"):
                return {"ok": False, "error": "policy denied"}
            if t["status"] == "done":
                return {"ok": True, "result": json.loads(t["result_json"]) if t["result_json"] else None}
            # mark running
            now = _now()
            self.db.execute(
                "UPDATE tasks SET status='running', attempts=attempts+1, updated_at=? WHERE id=? AND tenant_id=? AND user_id=? AND status IN ('queued','failed')",
                (now, task_id, self.tenant_id, self.user_id))
            # verify it actually transitioned (concurrency guard)
            t2 = self._get(task_id)
            if t2["status"] != "running":
                return {"ok": False, "error": "not runnable"}
            self._event(task_id, "running")

        # execute
        try:
            payload = json.loads(t["payload_json"]) if t["payload_json"] else {}
            if self.executor:
                result = self.executor(t["agent_id"], payload)
            else:
                result = {"ok": True}
            # check cancellation during execution
            t3 = self._get(task_id)
            if t3 and t3["status"] == "cancelled":
                self._event(task_id, "cancelled")
                return {"ok": False, "error": "cancelled"}
            now = _now()
            self.db.execute(
                "UPDATE tasks SET status='done', result_json=?, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
                (json.dumps(result), now, task_id, self.tenant_id, self.user_id))
            self._event(task_id, "done")
            return {"ok": True, "result": result}
        except Exception as e:
            now = _now()
            self.db.execute(
                "UPDATE tasks SET status='failed', error=?, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
                (str(e)[:200], now, task_id, self.tenant_id, self.user_id))
            self._event(task_id, "failed", str(e)[:200])
            return {"ok": False, "error": "execution failed"}

    def retry(self, task_id: str):
        t = self._get(task_id)
        if not t or t["status"] not in ("failed",):
            return False
        now = _now()
        self.db.execute(
            "UPDATE tasks SET status='queued', error=NULL, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
            (now, task_id, self.tenant_id, self.user_id))
        self._event(task_id, "queued", "retry")
        return True

    def list_events(self, task_id: str):
        return self.db.query(
            "SELECT * FROM task_events WHERE tenant_id=? AND task_id=? ORDER BY created_at",
            (self.tenant_id, task_id))