"""Owner-scoped feedback and explicit preference lessons."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

ALLOWED_SCOPES = {"task", "brand", "agent", "team"}
ALLOWED_RATINGS = {"approved", "thumbs_up", "thumbs_down", "needs_changes"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FeedbackService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def submit(self, scope_type: str, scope_id: Optional[str], rating: str,
               feedback: str, *, agent_id: Optional[str] = None,
               task_type: Optional[str] = None,
               output_snapshot: Optional[Dict[str, Any]] = None,
               lesson: Optional[str] = None) -> Dict[str, Any]:
        scope_type = (scope_type or "").strip().lower()
        rating = (rating or "").strip().lower()
        feedback = (feedback or "").strip()
        if scope_type not in ALLOWED_SCOPES:
            raise ValueError("invalid feedback scope")
        if not (scope_id or "").strip() and scope_type != "team":
            raise ValueError("scope_id is required for this feedback scope")
        if rating not in ALLOWED_RATINGS:
            raise ValueError("invalid feedback rating")
        if not feedback:
            raise ValueError("feedback is required")
        if lesson is not None and not lesson.strip():
            raise ValueError("lesson cannot be blank")
        fid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO agent_feedback "
            "(id,tenant_id,user_id,scope_type,scope_id,agent_id,task_type,rating,"
            "feedback,output_snapshot,lesson,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, self.tenant_id, self.user_id, scope_type,
             (scope_id or "").strip() or None, agent_id, task_type, rating,
             feedback, json.dumps(output_snapshot) if output_snapshot is not None else None,
             lesson.strip() if lesson else None, "recorded", _now()))
        return self.get(fid)

    def get(self, feedback_id: str) -> Dict[str, Any]:
        rows = self.db.query(
            "SELECT * FROM agent_feedback WHERE id=? AND tenant_id=? AND user_id=?",
            (feedback_id, self.tenant_id, self.user_id))
        if not rows:
            raise ValueError("feedback not found")
        row = dict(rows[0])
        if row.get("output_snapshot"):
            row["output_snapshot"] = json.loads(row["output_snapshot"])
        return row

    def list(self, scope_type: Optional[str] = None,
             scope_id: Optional[str] = None) -> list:
        clauses = ["tenant_id=?", "user_id=?"]
        params = [self.tenant_id, self.user_id]
        if scope_type:
            if scope_type not in ALLOWED_SCOPES:
                raise ValueError("invalid feedback scope")
            clauses.append("scope_type=?")
            params.append(scope_type)
        if scope_id:
            clauses.append("scope_id=?")
            params.append(scope_id)
        rows = self.db.query(
            "SELECT * FROM agent_feedback WHERE " + " AND ".join(clauses) +
            " ORDER BY created_at DESC", tuple(params))
        result = []
        for row in rows:
            item = dict(row)
            if item.get("output_snapshot"):
                item["output_snapshot"] = json.loads(item["output_snapshot"])
            result.append(item)
        return result

    def approve_lesson(self, feedback_id: str) -> Dict[str, Any]:
        self.get(feedback_id)
        self.db.execute(
            "UPDATE agent_feedback SET status='approved', approved_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=? AND lesson IS NOT NULL",
            (_now(), feedback_id, self.tenant_id, self.user_id))
        return self.get(feedback_id)

    def approved_lessons(self, scope_type: Optional[str] = None,
                         scope_id: Optional[str] = None) -> list:
        return [
            row for row in self.list(scope_type, scope_id)
            if row["status"] == "approved" and row.get("lesson")
        ]

    def preference_lessons(self) -> list:
        """Return approved lesson strings for the preference profile (C1)."""
        out = []
        for scope in (None, "team"):
            for r in self.approved_lessons(scope):
                l = r.get("lesson")
                if l and l not in out:
                    out.append(l)
        return out

    def lessons_for(self, agent_id: str, brand_id: Optional[str] = None,
                    task_id: Optional[str] = None) -> list:
        """Return approved lessons applicable to one grounded agent run."""
        rows = self.approved_lessons("team")
        rows += self.approved_lessons("agent", agent_id)
        if brand_id:
            rows += self.approved_lessons("brand", brand_id)
        if task_id:
            rows += self.approved_lessons("task", task_id)
        return rows
