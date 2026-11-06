from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from storage.database import Database


def _now():
    return datetime.now(timezone.utc).isoformat()


class WorkspaceService:
    def __init__(self, db, tenant_id, user_id):
        self.db = db; self.tenant_id = tenant_id; self.user_id = user_id
    def create(self, name):
        wid = str(uuid.uuid4())
        self.db.execute("INSERT INTO workspaces (id,tenant_id,user_id,name,created_at) VALUES (?,?,?,?,?)",
                        (wid, self.tenant_id, self.user_id, name, _now()))
        return wid
    def list(self):
        return self.db.query("SELECT * FROM workspaces WHERE tenant_id=? AND user_id=? AND is_synthetic != 1",
                             (self.tenant_id, self.user_id))


class ProjectService:
    def __init__(self, db, tenant_id, user_id):
        self.db = db; self.tenant_id = tenant_id; self.user_id = user_id
    def create(self, workspace_id, name):
        pid = str(uuid.uuid4())
        self.db.execute("INSERT INTO projects (id,tenant_id,workspace_id,user_id,name,created_at) VALUES (?,?,?,?,?,?)",
                        (pid, self.tenant_id, workspace_id, self.user_id, name, _now()))
        return pid
    def list(self, workspace_id=None):
        if workspace_id:
            return self.db.query("SELECT * FROM projects WHERE tenant_id=? AND user_id=? AND workspace_id=? AND is_synthetic != 1",
                                 (self.tenant_id, self.user_id, workspace_id))
        return self.db.query("SELECT * FROM projects WHERE tenant_id=? AND user_id=? AND is_synthetic != 1",
                             (self.tenant_id, self.user_id))


GOAL_STATUS_TRANSITIONS = {
    "open": {"in_progress", "cancelled"},
    "in_progress": {"done", "cancelled", "open"},
    "done": set(),
    "cancelled": set(),
}
GOAL_PATCH_KEYS = {"title", "priority", "status", "progress"}
_GOAL_SENSITIVE = ("password", "secret", "token", "api_key", "api-key",
                   "master_key", "private_key", "client_secret")


def _goal_has_secret(text):
    low = str(text or "").lower()
    return any(p in low for p in _GOAL_SENSITIVE)


class GoalService:
    def __init__(self, db, tenant_id, user_id, policy=None):
        self.db = db; self.tenant_id = tenant_id; self.user_id = user_id; self.policy = policy

    def _get(self, goal_id):
        rows = self.db.query(
            "SELECT * FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
            (goal_id, self.tenant_id, self.user_id))
        return rows[0] if rows else None

    def _event(self, goal_id, status, detail=None):
        self.db.execute(
            "INSERT INTO goal_events (id,tenant_id,goal_id,status,detail,created_at) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, goal_id, status, detail, _now()))

    def create(self, project_id, title, priority=0):
        if _goal_has_secret(title):
            raise ValueError("goal title contains a secret")
        gid = str(uuid.uuid4())
        now = _now()
        self.db.execute(
            "INSERT INTO goals (id,tenant_id,project_id,user_id,title,priority,status,progress,updated_at,version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (gid, self.tenant_id, project_id, self.user_id, title, priority, "open", 0, now, 0, now))
        self._event(gid, "created", f"title={title}")
        return gid

    def get(self, goal_id):
        return self._get(goal_id)

    def list(self, project_id=None):
        if project_id:
            return self.db.query("SELECT * FROM goals WHERE tenant_id=? AND user_id=? AND project_id=? AND is_synthetic != 1 ORDER BY priority DESC",
                                 (self.tenant_id, self.user_id, project_id))
        return self.db.query("SELECT * FROM goals WHERE tenant_id=? AND user_id=? AND is_synthetic != 1 ORDER BY priority DESC",
                             (self.tenant_id, self.user_id))

    def list_all(self):
        return self.list()

    def list_assigned(self, agent_id):
        return self.db.query(
            "SELECT g.* FROM goals g JOIN assignments a ON a.goal_id=g.id AND a.tenant_id=g.tenant_id AND a.user_id=g.user_id "
            "WHERE g.tenant_id=? AND g.user_id=? AND a.agent_id=? ORDER BY g.priority DESC",
            (self.tenant_id, self.user_id, agent_id))

    # --- goal update proposals (approval-gated) ---
    def propose_update(self, goal_id, agent_id, patch, reason=None, context=None,
                       confidence=0.5, manifest=None, policy=None):
        pol = policy if policy is not None else self.policy
        perms = set((manifest or {}).get("permissions", []) or [])
        if "goal:propose" not in perms:
            raise PermissionError("agent lacks 'goal:propose' permission")
        if pol is None or not pol.allow(agent_id, "goal", "propose"):
            raise PermissionError("policy denies goal proposal")
        goal = self._get(goal_id)
        if goal is None:
            raise ValueError("goal not found")
        if _goal_has_secret(reason) or _goal_has_secret(context):
            raise ValueError("proposal contains a secret")
        patch = self._validate_patch(patch)
        pid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO goal_update_proposals (id,tenant_id,user_id,goal_id,agent_id,proposed_json,reason,context,confidence,base_version,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, self.tenant_id, self.user_id, goal_id, agent_id, json.dumps(patch), reason, context, confidence, goal["version"], "proposed", _now()))
        return pid

    def _validate_patch(self, patch):
        if not isinstance(patch, dict):
            raise ValueError("patch must be a dict")
        out = {}
        for k, v in patch.items():
            if k not in GOAL_PATCH_KEYS:
                raise ValueError(f"invalid patch key: {k}")
            out[k] = v
        if not out:
            raise ValueError("empty patch")
        if "title" in out and (not isinstance(out["title"], str) or _goal_has_secret(out["title"])):
            raise ValueError("invalid goal title")
        if "priority" in out and (not isinstance(out["priority"], int) or isinstance(out["priority"], bool)):
            raise ValueError("priority must be an int")
        if "progress" in out:
            p = out["progress"]
            if not isinstance(p, int) or isinstance(p, bool) or p < 0 or p > 100:
                raise ValueError("progress must be an int 0..100")
        if "status" in out and out["status"] not in GOAL_STATUS_TRANSITIONS:
            raise ValueError("invalid goal status")
        return out

    def _compute_update(self, goal, patch):
        title = patch.get("title", goal["title"])
        priority = patch.get("priority", goal["priority"])
        status = patch.get("status", goal["status"])
        progress = patch.get("progress", goal["progress"])
        if status != goal["status"]:
            allowed = GOAL_STATUS_TRANSITIONS.get(goal["status"], set())
            if status not in allowed:
                raise ValueError(f"invalid transition {goal['status']}->{status}")
        if progress < 0 or progress > 100:
            raise ValueError("progress out of range")
        if status == "done" and progress != 100:
            raise ValueError("done requires progress=100")
        if progress == 100 and status != "done":
            raise ValueError("progress=100 requires status=done")
        return title, priority, status, progress

    def approve_update(self, proposal_id, user_id):
        # Ownership/state/staleness pre-check on the autocommit path so a
        # 'stale' mark persists (independent of the atomic-apply transaction).
        rows = self.db.query(
            "SELECT * FROM goal_update_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (proposal_id, self.tenant_id, self.user_id))
        if not rows:
            raise ValueError("proposal not found")
        prow = rows[0]
        if prow["status"] != "proposed":
            raise ValueError("proposal already decided")
        grows = self.db.query(
            "SELECT * FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
            (prow["goal_id"], self.tenant_id, self.user_id))
        if not grows:
            raise ValueError("goal not found")
        grow = grows[0]
        if prow["base_version"] != grow["version"]:
            self.db.execute(
                "UPDATE goal_update_proposals SET status='stale', decided_at=? WHERE id=?",
                (_now(), proposal_id))
            raise ValueError("goal changed since proposal; re-review required")

        patch = json.loads(prow["proposed_json"])
        title, priority, status, progress = self._compute_update(grow, patch)

        # Atomic apply inside one transaction; the version guard prevents any
        # lost update against a concurrent external writer.
        with self.db.transaction() as c:
            c.row_factory = sqlite3.Row
            now = _now()
            cur = c.execute(
                "UPDATE goals SET title=?, priority=?, status=?, progress=?, updated_at=?, version=version+1 "
                "WHERE id=? AND tenant_id=? AND version=?",
                (title, priority, status, progress, now, grow["id"], self.tenant_id, prow["base_version"]))
            if cur.rowcount == 0:
                raise ValueError("goal changed concurrently; re-review required")
            c.execute(
                "INSERT INTO goal_events (id,tenant_id,goal_id,status,detail,created_at) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, grow["id"], "updated",
                 f"title={title} status={status} progress={progress}", now))
            c.execute("UPDATE goal_update_proposals SET status='approved', decided_at=? WHERE id=?", (now, proposal_id))
        return True

    def reject_update(self, proposal_id, user_id, reason=None):
        rows = self.db.query(
            "SELECT * FROM goal_update_proposals WHERE id=? AND tenant_id=? AND user_id=? AND status='proposed'",
            (proposal_id, self.tenant_id, self.user_id))
        if not rows:
            raise ValueError("proposal not found or already decided")
        self.db.execute("UPDATE goal_update_proposals SET status='rejected', decided_at=? WHERE id=?", (_now(), proposal_id))
        return True

    def expire_stale(self):
        rows = self.db.query(
            "SELECT p.id AS pid FROM goal_update_proposals p JOIN goals g ON g.id=p.goal_id AND g.tenant_id=p.tenant_id "
            "WHERE p.tenant_id=? AND p.user_id=? AND p.status='proposed' AND p.base_version != g.version",
            (self.tenant_id, self.user_id))
        for r in rows:
            self.db.execute("UPDATE goal_update_proposals SET status='stale', decided_at=? WHERE id=?", (_now(), r["pid"]))
        return len(rows)

    def list_proposals(self, status=None):
        if status:
            return self.db.query("SELECT * FROM goal_update_proposals WHERE tenant_id=? AND user_id=? AND status=?",
                                 (self.tenant_id, self.user_id, status))
        return self.db.query("SELECT * FROM goal_update_proposals WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC",
                             (self.tenant_id, self.user_id))

    def list_events(self, goal_id):
        return self.db.query("SELECT * FROM goal_events WHERE tenant_id=? AND goal_id=? ORDER BY created_at",
                             (self.tenant_id, goal_id))


class AssignmentService:
    def __init__(self, db, tenant_id, user_id):
        self.db = db; self.tenant_id = tenant_id; self.user_id = user_id
    def assign(self, goal_id, agent_id, priority=0):
        # prevent duplicate
        existing = self.db.query("SELECT id FROM assignments WHERE tenant_id=? AND goal_id=? AND agent_id=?",
                                 (self.tenant_id, goal_id, agent_id))
        if existing:
            raise ValueError("duplicate assignment")
        aid = str(uuid.uuid4())
        self.db.execute("INSERT INTO assignments (id,tenant_id,goal_id,user_id,agent_id,priority,created_at) VALUES (?,?,?,?,?,?,?)",
                        (aid, self.tenant_id, goal_id, self.user_id, agent_id, priority, _now()))
        return aid
    def list(self, goal_id=None):
        if goal_id:
            return self.db.query("SELECT * FROM assignments WHERE tenant_id=? AND user_id=? AND goal_id=? AND is_synthetic != 1 ORDER BY priority DESC",
                                 (self.tenant_id, self.user_id, goal_id))
        return self.db.query("SELECT * FROM assignments WHERE tenant_id=? AND user_id=? AND is_synthetic != 1 ORDER BY priority DESC",
                             (self.tenant_id, self.user_id))


class DeliverableService:
    def __init__(self, db, tenant_id, user_id):
        self.db = db; self.tenant_id = tenant_id; self.user_id = user_id
    def create(self, project_id, title):
        did = str(uuid.uuid4())
        self.db.execute("INSERT INTO deliverables (id,tenant_id,project_id,user_id,title,created_at) VALUES (?,?,?,?,?,?)",
                        (did, self.tenant_id, project_id, self.user_id, title, _now()))
        return did
    def add_version(self, deliverable_id, content):
        versions = self.db.query("SELECT MAX(version) as mv FROM deliverable_versions WHERE tenant_id=? AND deliverable_id=?",
                                 (self.tenant_id, deliverable_id))
        mv = (versions[0]["mv"] or 0) + 1
        # Link the new version to its immediate predecessor as `revision_of`
        # (the highest existing version id), preserving a traceable revision chain.
        prev = self.db.query(
            "SELECT id FROM deliverable_versions WHERE tenant_id=? AND deliverable_id=? "
            "AND version=?", (self.tenant_id, deliverable_id, mv - 1))
        prev_id = prev[0]["id"] if prev else None
        vid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO deliverable_versions (id,tenant_id,deliverable_id,version,content,status,revision_of,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (vid, self.tenant_id, deliverable_id, mv, content, "draft", prev_id, _now()))
        return vid, mv
    def approve(self, version_id, user_id):
        # agent cannot approve own? agent identity not passed; assume user only
        rows = self.db.query("SELECT * FROM deliverable_versions WHERE id=? AND tenant_id=?", (version_id, self.tenant_id))
        if not rows:
            raise ValueError("version not found")
        v = rows[0]
        if v["status"] == "approved":
            raise ValueError("already approved")
        self.db.execute("UPDATE deliverable_versions SET status='approved' WHERE id=?", (version_id,))
        self.db.execute("INSERT INTO deliverable_approvals (id,tenant_id,version_id,user_id,decision,created_at) VALUES (?,?,?,?,?,?)",
                        (str(uuid.uuid4()), self.tenant_id, version_id, user_id, "approved", _now()))
    def reject(self, version_id, user_id, reason=""):
        """Permanently decline a deliverable version (not a revision request).
        The version is marked rejected and the decision is recorded. The task is
        NOT set to ready-for-review via this path."""
        self.db.execute("UPDATE deliverable_versions SET status='rejected' WHERE id=?", (version_id,))
        decision = ("rejected:" + reason) if reason else "rejected"
        self.db.execute("INSERT INTO deliverable_approvals (id,tenant_id,version_id,user_id,decision,created_at) VALUES (?,?,?,?,?,?)",
                        (str(uuid.uuid4()), self.tenant_id, version_id, user_id, decision, _now()))

    def request_changes(self, version_id, user_id, reason=""):
        """Request changes on a deliverable version (distinct from rejection).
        The version stays reviewable and is flagged requested_changes=1; a new
        version (revision) is expected next. Records a decision; never closes the
        deliverable."""
        rows = self.db.query(
            "SELECT * FROM deliverable_versions WHERE id=? AND tenant_id=?",
            (version_id, self.tenant_id))
        if not rows:
            raise ValueError("version not found")
        v = rows[0]
        note = reason or ""
        self.db.execute(
            "UPDATE deliverable_versions SET requested_changes=1, review_note=? "
            "WHERE id=? AND tenant_id=?",
            (note, version_id, self.tenant_id))
        self.db.execute(
            "INSERT INTO deliverable_approvals (id,tenant_id,version_id,user_id,decision,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, version_id, user_id,
             "requested_changes:" + note if note else "requested_changes", _now()))

    def list_versions(self, deliverable_id):
        return self.db.query("SELECT * FROM deliverable_versions WHERE tenant_id=? AND deliverable_id=? ORDER BY version",
                             (self.tenant_id, deliverable_id))