"""Approval-gated outward action executor.

The initial implementation is deliberately a local stub. It records what
would happen and never contacts an external service.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionExecutor:
    ALLOWED_TYPES = {"email", "dm", "ig_post"}

    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def execute(self, action_id: str):
        rows = self.db.query(
            "SELECT * FROM pending_actions WHERE id=? AND tenant_id=? AND user_id=?",
            (action_id, self.tenant_id, self.user_id))
        if not rows:
            raise ValueError("action not found")
        action = rows[0]
        if action["status"] != "approved":
            raise ValueError("action must be approved before execution")
        if action["type"] not in self.ALLOWED_TYPES:
            raise ValueError(f"unsupported action type: {action['type']}")
        payload = json.loads(action["payload"])
        result = {
            "performed": False,
            "stub": True,
            "message": f"Would execute {action['type']} action. No external service was contacted.",
            "type": action["type"],
            "payload": payload,
        }
        now = _now()
        self.db.execute(
            "UPDATE pending_actions SET status='executed', result=?, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (json.dumps(result), now, action_id, self.tenant_id, self.user_id))
        self.db.execute(
            "INSERT INTO activity_log "
            "(id,tenant_id,user_id,timestamp,agent,event,details) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, self.user_id, now, "executor",
             "action_executed_stub", json.dumps({"action_id": action_id, "type": action["type"]})))
        return result
