"""Episode service with checkpointing and recovery."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable

from storage.database import Database

SECRET_KEYS = {"password", "secret", "token", "api_key"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _valid_checkpoint(cp):
    if not isinstance(cp, dict):
        return False
    for k in cp:
        if k.lower() in SECRET_KEYS:
            return False
    return True


class EpisodeService:
    def __init__(self, db: Database, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def start(self, agent_id: str) -> str:
        eid = str(uuid.uuid4())
        now = _now()
        self.db.execute(
            "INSERT INTO episodes (id,tenant_id,user_id,agent_id,status,progress,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (eid, self.tenant_id, self.user_id, agent_id, "running", 0, now, now))
        self._event(eid, "started")
        return eid

    def checkpoint(self, episode_id: str, progress: int, checkpoint: Dict[str, Any]):
        if not _valid_checkpoint(checkpoint):
            raise ValueError("invalid checkpoint")
        t = self._get(episode_id)
        if not t or t["status"] == "cancelled":
            return False
        now = _now()
        self.db.execute(
            "UPDATE episodes SET progress=?, checkpoint_json=?, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
            (progress, json.dumps(checkpoint), now, episode_id, self.tenant_id, self.user_id))
        self._event(episode_id, "checkpoint", f"progress={progress}")
        return True

    def _get(self, eid):
        rows = self.db.query(
            "SELECT * FROM episodes WHERE id=? AND tenant_id=? AND user_id=?",
            (eid, self.tenant_id, self.user_id))
        return rows[0] if rows else None

    def get(self, eid):
        return self._get(eid)

    def cancel(self, eid):
        t = self._get(eid)
        if not t or t["status"] in ("done", "cancelled"):
            return False
        now = _now()
        self.db.execute(
            "UPDATE episodes SET status='cancelled', cancelled_at=?, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
            (now, now, eid, self.tenant_id, self.user_id))
        self._event(eid, "cancelled")
        return True

    def complete(self, eid):
        t = self._get(eid)
        if not t or t["status"] == "cancelled":
            return False
        now = _now()
        self.db.execute(
            "UPDATE episodes SET status='done', updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
            (now, eid, self.tenant_id, self.user_id))
        self._event(eid, "done")
        return True

    def recover(self, eid, runner: Callable):
        t = self._get(eid)
        if not t or t["status"] == "cancelled":
            return False
        if t["status"] == "done":
            return False
        cp = json.loads(t["checkpoint_json"]) if t["checkpoint_json"] else {}
        # resume
        runner(eid, t["progress"], cp)
        return True

    def _event(self, eid, status, detail=None):
        self.db.execute(
            "INSERT INTO episode_events (id,tenant_id,episode_id,status,detail,created_at) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, eid, status, detail, _now()))