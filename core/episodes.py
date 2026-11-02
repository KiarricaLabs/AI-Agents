"""Episode service with checkpointing and recovery."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable

from storage.database import Database

SECRET_KEYS = {"password", "secret", "token", "api_key"}


class EpisodeNotFound(ValueError):
    pass


class EpisodeNotCompleted(ValueError):
    pass


class MissingCompletionEvidence(ValueError):
    pass


class GoalNotFound(ValueError):
    pass


class StaleGoalVersion(ValueError):
    pass


class GoalCompletionConflict(ValueError):
    pass


class EpisodeAlreadyApplied(ValueError):
    pass


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
        if not t or t["status"] != "running":
            # Only running -> done is a valid transition. Already-done or
            # cancelled episodes can never complete again (no duplicate event).
            return False
        now = _now()
        self.db.execute(
            "UPDATE episodes SET status='done', progress=1.0, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=? AND status='running'",
            (now, episode_id, self.tenant_id, self.user_id))
        # Verify the transition actually happened (guards the narrow race where
        # a concurrent cancel/complete won); only then record the completion event.
        after = self._get(episode_id)
        if not after or after["status"] != "done":
            return False
        self._event(episode_id, "done", "completed", evidence=evidence, progress=1.0)
        return True

    # ---------------- M10 Phase D3: evidence-backed goal progress application ---
    def _completion_evidence(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Persisted evidence of the completed episode (immutable; read-only)."""
        rows = self.db.query(
            "SELECT evidence_json FROM episode_events WHERE tenant_id=? AND episode_id=? "
            "AND status='done' ORDER BY created_at DESC LIMIT 1",
            (self.tenant_id, episode_id))
        if not rows or not rows[0]["evidence_json"]:
            return None
        try:
            return json.loads(rows[0]["evidence_json"])
        except Exception:
            return None

    def _applied_result(self, ep: Dict[str, Any]) -> Dict[str, Any]:
        return {"applied": True, "already_applied": True, "episode_id": ep["id"],
                "work_type": ep.get("work_type"), "work_id": ep.get("work_id"),
                "applied_at": ep.get("applied_at"), "applied_by": ep.get("applied_by")}

    def apply_completed_episode(self, episode_id: str, approver_user_id: str) -> Dict[str, Any]:
        """Human-controlled, evidence-backed application of a completed execution
        Episode to its referenced goal. Uses ONLY the persisted episode evidence
        and progress; never accepts replacement evidence/progress. Atomic; one
        application per episode; version-guarded goal update; no client/"
        conversation-derived proof."""
        ep = self._get(episode_id)
        if not ep:
            raise EpisodeNotFound("episode not found")
        if ep["status"] != "done":
            raise EpisodeNotCompleted("episode is not completed")
        if ep.get("applied_at"):
            return self._applied_result(ep)  # idempotent: already applied

        evidence = self._completion_evidence(episode_id)
        if not evidence or not (str(evidence.get("summary") or "").strip()):
            raise MissingCompletionEvidence("completion evidence is missing")

        wt, wid = ep.get("work_type"), ep.get("work_id")
        if wt == "assignment":
            rows = self.db.query(
                "SELECT goal_id FROM assignments WHERE id=? AND tenant_id=? AND user_id=?",
                (wid, self.tenant_id, self.user_id))
            if not rows:
                raise GoalNotFound("assigned goal not found")
            gid = rows[0]["goal_id"]
        elif wt == "goal":
            rows = self.db.query(
                "SELECT id, progress, status, version FROM goals "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (wid, self.tenant_id, self.user_id))
            if not rows:
                raise GoalNotFound("goal not found")
            gid = wid
        else:
            raise EpisodeNotCompleted("episode is not linked to an executable goal/assignment")

        goal = self.db.query(
            "SELECT * FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
            (gid, self.tenant_id, self.user_id))[0]

        # Deterministic progress mapping (episode fraction 0..1 -> goal 0..100).
        percent = min(100, int(round(float(ep.get("progress") or 0) * 100)))
        new_progress = max(int(goal["progress"] or 0), percent)  # never reduce
        cur_status = goal["status"]
        if cur_status == "cancelled":
            raise GoalCompletionConflict("cannot apply execution to a cancelled goal")
        if float(ep.get("progress") or 0) >= 1.0:
            if cur_status == "in_progress":
                new_status = "done"
            elif cur_status == "open":
                # Preserve existing transition protection (open->done is disallowed).
                raise GoalCompletionConflict(
                    "goal must be in_progress before a completed execution can mark it done")
            else:  # already done
                new_status = "done"
        else:
            new_status = cur_status  # progress-only
        if new_progress == 100 and new_status != "done":
            raise GoalCompletionConflict("completed execution cannot be applied without completing the goal")

        now = _now()
        summary = str(evidence.get("summary"))[:120]
        event_status = new_status if new_status != cur_status else "progress_update"
        try:
            with self.db.transaction() as c:
                ap = c.execute(
                    "UPDATE episodes SET applied_at=?, applied_by=? "
                    "WHERE id=? AND tenant_id=? AND user_id=? AND applied_at IS NULL",
                    (now, approver_user_id, episode_id, self.tenant_id, self.user_id))
                if ap.rowcount == 0:
                    raise EpisodeAlreadyApplied("episode already applied")
                g = c.execute(
                    "UPDATE goals SET progress=?, status=?, updated_at=?, version=version+1 "
                    "WHERE id=? AND tenant_id=? AND user_id=? AND version=?",
                    (new_progress, new_status, now, gid, self.tenant_id, self.user_id,
                     int(goal["version"])))
                if g.rowcount == 0:
                    raise StaleGoalVersion("goal changed concurrently; re-review required")
                c.execute(
                    "INSERT INTO goal_events (id,tenant_id,goal_id,status,detail,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), self.tenant_id, gid, event_status,
                     f"progress={new_progress} status={new_status} evidence={summary}", now))
        except EpisodeAlreadyApplied:
            ep2 = self._get(episode_id)
            return self._applied_result(ep2 or ep)
        return {"applied": True, "already_applied": False, "episode_id": episode_id,
                "work_type": wt, "work_id": wid, "goal_id": gid,
                "goal_progress": new_progress, "goal_status": new_status,
                "applied_at": now, "applied_by": approver_user_id,
                "evidence_summary": summary}

    def _latest_evidence_summary(self, episode_id: str) -> Optional[str]:
        """Most recent persisted evidence summary (sanitized string only; never
        returns raw evidence dicts or secret-bearing content)."""
        rows = self.db.query(
            "SELECT evidence_json FROM episode_events WHERE tenant_id=? AND episode_id=? "
            "AND evidence_json IS NOT NULL ORDER BY created_at DESC LIMIT 1",
            (self.tenant_id, episode_id))
        if not rows or not rows[0]["evidence_json"]:
            return None
        try:
            summary = str(json.loads(rows[0]["evidence_json"]).get("summary") or "")
            return summary[:200] or None
        except Exception:
            return None

    def execution_summary(self, work_type: str, work_id: str) -> Dict[str, Any]:
        """Read-only execution summary for a goal or assignment: active and
        completed episodes with progress, latest evidence summary, and apply
        state. Sanitized; no raw evidence/credentials exposed."""
        if work_type not in {"goal", "assignment"}:
            raise ValueError("unsupported work type")
        rows = self.db.query(
            "SELECT * FROM episodes WHERE tenant_id=? AND user_id=? AND work_type=? "
            "AND work_id=? ORDER BY created_at ASC",
            (self.tenant_id, self.user_id, work_type, work_id))
        items = []
        for r in rows:
            items.append({
                "episode_id": r["id"],
                "agent_id": r["agent_id"],
                "status": r["status"],
                "progress": r.get("progress"),
                "work_type": r.get("work_type"),
                "work_id": r.get("work_id"),
                "evidence_summary": self._latest_evidence_summary(r["id"]),
                "applied_at": r.get("applied_at"),
                "applied_by": r.get("applied_by"),
                "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at"),
            })
        return {"work_type": work_type, "work_id": work_id, "episodes": items}