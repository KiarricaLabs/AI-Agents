from __future__ import annotations
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
        return self.db.query("SELECT * FROM workspaces WHERE tenant_id=? AND user_id=?", (self.tenant_id, self.user_id))


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
            return self.db.query("SELECT * FROM projects WHERE tenant_id=? AND user_id=? AND workspace_id=?",
                                 (self.tenant_id, self.user_id, workspace_id))
        return self.db.query("SELECT * FROM projects WHERE tenant_id=? AND user_id=?", (self.tenant_id, self.user_id))


class GoalService:
    def __init__(self, db, tenant_id, user_id):
        self.db = db; self.tenant_id = tenant_id; self.user_id = user_id
    def create(self, project_id, title, priority=0):
        gid = str(uuid.uuid4())
        self.db.execute("INSERT INTO goals (id,tenant_id,project_id,user_id,title,priority,created_at) VALUES (?,?,?,?,?,?,?)",
                        (gid, self.tenant_id, project_id, self.user_id, title, priority, _now()))
        return gid
    def list(self, project_id=None):
        if project_id:
            return self.db.query("SELECT * FROM goals WHERE tenant_id=? AND user_id=? AND project_id=? ORDER BY priority DESC",
                                 (self.tenant_id, self.user_id, project_id))
        return self.db.query("SELECT * FROM goals WHERE tenant_id=? AND user_id=? ORDER BY priority DESC",
                             (self.tenant_id, self.user_id))


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
            return self.db.query("SELECT * FROM assignments WHERE tenant_id=? AND user_id=? AND goal_id=? ORDER BY priority DESC",
                                 (self.tenant_id, self.user_id, goal_id))
        return self.db.query("SELECT * FROM assignments WHERE tenant_id=? AND user_id=? ORDER BY priority DESC",
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
        vid = str(uuid.uuid4())
        self.db.execute("INSERT INTO deliverable_versions (id,tenant_id,deliverable_id,version,content,status,created_at) VALUES (?,?,?,?,?,?,?)",
                        (vid, self.tenant_id, deliverable_id, mv, content, "draft", _now()))
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
    def reject(self, version_id, user_id):
        self.db.execute("UPDATE deliverable_versions SET status='rejected' WHERE id=?", (version_id,))
        self.db.execute("INSERT INTO deliverable_approvals (id,tenant_id,version_id,user_id,decision,created_at) VALUES (?,?,?,?,?,?)",
                        (str(uuid.uuid4()), self.tenant_id, version_id, user_id, "rejected", _now()))
    def list_versions(self, deliverable_id):
        return self.db.query("SELECT * FROM deliverable_versions WHERE tenant_id=? AND deliverable_id=? ORDER BY version",
                             (self.tenant_id, deliverable_id))