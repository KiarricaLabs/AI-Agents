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

    def _event(self, eid, status, detail=None, evidence=None, progress=None):
        self.db.execute(
            "INSERT INTO episode_events "
            "(id,tenant_id,episode_id,status,detail,evidence_json,progress,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, eid, status, detail,
             json.dumps(evidence) if evidence is not None else None, progress, _now()))

    # ---------------- M10 Phase D2: execution gating (lifecycle tracking only) ---
    def start_for_work(self, work_type: str, work_id: str, agent_id: str) -> dict:
        """Start a tracked execution Episode for an approved work record. Caller
        must already have authorized (human) and revalidated ownership. Returns
        the existing ACTIVE episode idempotently; the partial unique index
        provides DB-level protection against concurrent duplicate starts."""
        import sqlite3

        existing = self.db.query(
            "SELECT * FROM episodes WHERE tenant_id=? AND user_id=? AND work_type=? "
            "AND work_id=? AND agent_id=? AND status='running'",
            (self.tenant_id, self.user_id, work_type, work_id, agent_id))
        if existing:
            return {"episode_id": existing[0]["id"], "status": existing[0]["status"],
                    "already_active": True}
        eid = str(uuid.uuid4())
        now = _now()
        try:
            with self.db.transaction() as c:
                c.execute(
                    "INSERT INTO episodes "
                    "(id,tenant_id,user_id,agent_id,status,progress,work_type,work_id,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (eid, self.tenant_id, self.user_id, agent_id, "running", 0,
                     work_type, work_id, now, now))
                c.execute(
                    "INSERT INTO episode_events "
                    "(id,tenant_id,episode_id,status,detail,evidence_json,progress,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), self.tenant_id, eid, "started",
                     f"execution of {work_type} {work_id}", None, 0, now))
        except sqlite3.IntegrityError:
            # A concurrent start won the race for the same active key.
            found = self.db.query(
                "SELECT * FROM episodes WHERE tenant_id=? AND user_id=? AND work_type=? "
                "AND work_id=? AND agent_id=? AND status='running'",
                (self.tenant_id, self.user_id, work_type, work_id, agent_id))
            if found:
                return {"episode_id": found[0]["id"], "status": found[0]["status"],
                        "already_active": True}
            raise
        return {"episode_id": eid, "status": "running", "already_active": False}

    @staticmethod
    def _validate_progress(p):
        # Episode progress is stored on a 0..1 fraction to match the existing
        # Activity UI/tests (which render progress * 100).
        if isinstance(p, bool) or not isinstance(p, (int, float)) or p < 0 or p > 1:
            raise ValueError("progress must be a number 0..1")

    @classmethod
    def _validate_evidence(cls, ev):
        if not isinstance(ev, dict) or not ev:
            raise ValueError("evidence is required")
        summary = ev.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("evidence.summary is required")
        cls._reject_secret(ev, "evidence")

    @staticmethod
    def _reject_secret(obj, path="evidence"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                low = str(k).casefold()
                if any(t in low for t in SECRET_KEYS):
                    raise ValueError("evidence contains a sensitive field")
                EpisodeService._reject_secret(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for x in obj:
                EpisodeService._reject_secret(x, path)

    def checkpoint_with_evidence(self, episode_id: str, progress: int, evidence: dict) -> bool:
        """Record real progress only with structured, validated evidence."""
        self._validate_progress(progress)
        self._validate_evidence(evidence)
        t = self._get(episode_id)
        if not t or t["status"] == "cancelled":
            return False
        if t["status"] == "done":
            return False
        now = _now()
        self.db.execute(
            "UPDATE episodes SET progress=?, checkpoint_json=?, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=? AND status='running'",
            (progress, json.dumps(evidence), now, episode_id, self.tenant_id, self.user_id))
        self._event(episode_id, "checkpoint", f"progress={progress}",
                    evidence=evidence, progress=progress)
        return True

    def complete_with_evidence(self, episode_id: str, evidence: dict) -> bool:
        """Complete an Episode only with validated evidence. Lifecycle tracking
        only; does NOT mutate the referenced goal."""
        self._validate_evidence(evidence)
        t = self._get(episode_id)
        if not t or t["status"] == "cancelled":
            return False
        now = _now()
        self.db.execute(
            "UPDATE episodes SET status='done', progress=1.0, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=? AND status='running'",
            (now, episode_id, self.tenant_id, self.user_id))
        self._event(episode_id, "done", "completed", evidence=evidence, progress=1.0)
        return True