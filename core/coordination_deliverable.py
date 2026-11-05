"""T2-C-5 — CoordinationDeliverableService: immutable versioned review.

Adds durable versioning + human review records on top of the T2-C-4
``coordination_deliverables`` row. The frozen snapshot (T2-C-3) and the
step output / execution lifecycle (T2-C-4) are reused as-is; this only records
which exact aggregated content was reviewed at each human decision, preserves
an immutable, ordered provenance chain, and refuses to silently overwrite or
re-write history.

Lifecycle (server-side version numbers only)
- Initial aggregation  -> version 1, status 'pending'.
- Re-aggregation while a pending version exists (no rework) -> the SAME pending
  version is reused; nothing is duplicated or overwritten.
- Re-aggregation after a revision_requested decision -> NEW pending version with
  ``revision_of`` = previous version id.
- review decision accepted      -> version 'approved'
- review decision rejected      -> version 'rejected'   (terminal, no reopen here)
- review decision revision      -> version 'revision_requested' (non-terminal)
- Every decision appends a coordination_deliverable_approvals row.
- A repeated identical decision on the same version is idempotent (returns the
  recorded state). A conflicting decision on an already-decided version is
  rejected (CoordinationDeliverableVersionConflict), never silently changed.

Writes accept an open transaction cursor so the caller can commit version
creation, the approval row, and the run-state transition atomically. Reads are
owner-scoped (tenant_id AND user_id).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now():
    return datetime.now(timezone.utc).isoformat()


# Version status lifecycle
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
REVISION_REQUESTED = "revision_requested"
_DECIDED = {APPROVED, REJECTED}  # terminal for a version


class CoordinationDeliverableVersionNotFound(ValueError):
    pass


class CoordinationDeliverableVersionConflict(ValueError):
    pass


class CoordinationDeliverablePermissionError(PermissionError):
    pass


class CoordinationDeliverableService:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ------------------------------------------------------------------ reads
    def latest_version(self, deliverable_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_deliverable_versions "
            "WHERE tenant_id=? AND user_id=? AND deliverable_id=? "
            "ORDER BY version DESC LIMIT 1",
            (self.tenant_id, self.user_id, deliverable_id))
        return rows[0] if rows else None

    def list_versions(self, deliverable_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_deliverable_versions "
            "WHERE tenant_id=? AND user_id=? AND deliverable_id=? ORDER BY version ASC",
            (self.tenant_id, self.user_id, deliverable_id))
        return [self._decode(v) for v in rows]

    def get_version(self, version_id: str, deliverable_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_deliverable_versions "
            "WHERE id=? AND deliverable_id=? AND tenant_id=? AND user_id=?",
            (version_id, deliverable_id, self.tenant_id, self.user_id))
        if not rows:
            return None
        v = self._decode(rows[0])
        v["approvals"] = self.approvals(version_id)
        return v

    def approvals(self, version_id: str) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM coordination_deliverable_approvals "
            "WHERE version_id=? AND tenant_id=? AND user_id=? ORDER BY created_at ASC",
            (version_id, self.tenant_id, self.user_id))

    @staticmethod
    def _decode(v: Dict[str, Any]) -> Dict[str, Any]:
        content = {}
        try:
            content = json.loads(v["content_json"]) if v["content_json"] else {}
        except Exception:
            content = {}
        return {
            "version_id": v["id"],
            "deliverable_id": v["deliverable_id"],
            "execution_id": v["execution_id"],
            "version": v["version"],
            "content": content,
            "status": v["status"],
            "review_note": v["review_note"],
            "revision_of": v["revision_of"],
            "created_at": v["created_at"],
            "updated_at": v["updated_at"],
        }

    # ------------------------------------------------------------- writes (cursor)
    def ensure_pending(self, c, *, deliverable_id: str, execution_id: str,
                       content: Dict[str, Any], now: str) -> Dict[str, Any]:
        """Create or reuse the pending version. Runs on cursor ``c``.

        - If no version exists                     -> version 1 (pending, revision_of None).
        - If the latest version is 'pending'       -> reuse it (no duplicate, no change).
        - If the latest version is revision_requested -> NEW pending version with
          ``revision_of`` = previous version id (rework re-aggregation).
        - If the latest version is approved/rejected -> conflict (terminal; cannot
          silently re-open or overwrite without an explicit reopen decision).
        """
        c.row_factory = sqlite3.Row
        latest_rows = list(c.execute(
            "SELECT * FROM coordination_deliverable_versions "
            "WHERE tenant_id=? AND user_id=? AND deliverable_id=? "
            "ORDER BY version DESC LIMIT 1",
            (self.tenant_id, self.user_id, deliverable_id)))
        latest = dict(latest_rows[0]) if latest_rows else None

        if latest is None:
            return self._create_version(c, deliverable_id=deliverable_id,
                                        execution_id=execution_id, content=content,
                                        now=now, revision_of=None)
        if latest["status"] == PENDING:
            return self._decode(latest)
        if latest["status"] == REVISION_REQUESTED:
            return self._create_version(c, deliverable_id=deliverable_id,
                                        execution_id=execution_id, content=content,
                                        now=now, revision_of=latest["id"])
        raise CoordinationDeliverableVersionConflict(
            f"cannot re-aggregate a {latest['status']} deliverable; reopen explicitly")

    def _create_version(self, c, *, deliverable_id: str, execution_id: str,
                        content: Dict[str, Any], now: str,
                        revision_of: Optional[str]) -> Dict[str, Any]:
        # Server-side version number: next integer after the current max.
        mx = c.execute(
            "SELECT COALESCE(MAX(version),0) AS v FROM coordination_deliverable_versions "
            "WHERE tenant_id=? AND user_id=? AND deliverable_id=?",
            (self.tenant_id, self.user_id, deliverable_id)).fetchone()
        version = int(mx[0]) + 1
        vid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO coordination_deliverable_versions "
            "(id, tenant_id, user_id, execution_id, deliverable_id, version, "
            " content_json, status, review_note, revision_of, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, self.tenant_id, self.user_id, execution_id, deliverable_id, version,
             json.dumps(content), PENDING, None, revision_of, now, now))
        return self._decode({"id": vid, "tenant_id": self.tenant_id,
                             "user_id": self.user_id, "execution_id": execution_id,
                             "deliverable_id": deliverable_id, "version": version,
                             "content_json": json.dumps(content), "status": PENDING,
                             "review_note": None, "revision_of": revision_of,
                             "created_at": now, "updated_at": now})

    def record_decision(self, c, *, version_id: str, decision: str,
                        approver_user_id: str, note: Optional[str],
                        now: str) -> Dict[str, Any]:
        """Record a human decision on the pending version (cursor). Idempotent for
        the identical decision; a conflicting decision is rejected."""
        if approver_user_id != self.user_id:
            raise CoordinationDeliverablePermissionError(
                "only the owner may decide on a deliverable version")
        if decision not in (APPROVED, REJECTED, REVISION_REQUESTED):
            raise CoordinationDeliverableVersionConflict(f"unknown decision: {decision}")
        c.row_factory = sqlite3.Row
        rows = list(c.execute(
            "SELECT * FROM coordination_deliverable_versions "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (version_id, self.tenant_id, self.user_id)))
        if not rows:
            raise CoordinationDeliverableVersionNotFound("version not found")
        v = dict(rows[0])

        existing = list(c.execute(
            "SELECT decision FROM coordination_deliverable_approvals "
            "WHERE version_id=? AND tenant_id=? AND user_id=?",
            (version_id, self.tenant_id, self.user_id)))
        if existing:
            prior = existing[0]["decision"]
            if prior == decision:
                return self._decode(v)  # idempotent
            raise CoordinationDeliverableVersionConflict(
                f"version {v['version']} already decided ({prior}); cannot change to {decision}")

        c.execute(
            "UPDATE coordination_deliverable_versions SET status=?, review_note=?, "
            "updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
            (decision, (note or "")[:400] or None, now, version_id,
             self.tenant_id, self.user_id))
        c.execute(
            "INSERT INTO coordination_deliverable_approvals "
            "(id, tenant_id, user_id, version_id, decision, note, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, self.user_id, version_id,
             decision, (note or "")[:400] or None, now))
        updated = self._decode(dict(list(c.execute(
            "SELECT * FROM coordination_deliverable_versions WHERE id=? "
            "AND tenant_id=? AND user_id=?", (version_id, self.tenant_id, self.user_id)))[0]))
        updated["approvals"] = [{"decision": decision, "user_id": approver_user_id,
                                 "note": (note or "")[:400] or None, "created_at": now}]
        return updated
