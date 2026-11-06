from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService, DeliverableService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _require_human(request: Request):
    if getattr(request.state, "role", None) not in ("user", "admin"):
        raise HTTPException(status_code=403, detail="human-only")


class CreateWorkspace(BaseModel):
    name: str
class CreateProject(BaseModel):
    workspace_id: str
    name: str
class CreateGoal(BaseModel):
    project_id: str
    title: str
    priority: int = 0
class AssignReq(BaseModel):
    goal_id: str
    agent_id: str
    priority: int = 0
class CreateDeliverable(BaseModel):
    project_id: str
    title: str
class AddVersion(BaseModel):
    content: str
class RejectBody(BaseModel):
    reason: str = ""


@router.post("")
def create_workspace(req: CreateWorkspace, request: Request):
    t, u = _identity(request)
    svc = WorkspaceService(_db, t, u)
    return {"id": svc.create(req.name)}

@router.get("")
def list_workspaces(request: Request):
    t, u = _identity(request)
    svc = WorkspaceService(_db, t, u)
    return {"items": svc.list()}

@router.post("/projects")
def create_project(req: CreateProject, request: Request):
    t, u = _identity(request)
    svc = ProjectService(_db, t, u)
    return {"id": svc.create(req.workspace_id, req.name)}

@router.get("/projects")
def list_projects(workspace_id: Optional[str] = None, request: Request = None):
    t, u = _identity(request)
    svc = ProjectService(_db, t, u)
    return {"items": svc.list(workspace_id)}

@router.post("/goals")
def create_goal(req: CreateGoal, request: Request):
    t, u = _identity(request)
    svc = GoalService(_db, t, u)
    return {"id": svc.create(req.project_id, req.title, req.priority)}

@router.get("/goals")
def list_goals(project_id: Optional[str] = None, request: Request = None):
    t, u = _identity(request)
    svc = GoalService(_db, t, u)
    return {"items": svc.list(project_id)}

@router.post("/assignments")
def assign(req: AssignReq, request: Request):
    t, u = _identity(request)
    svc = AssignmentService(_db, t, u)
    try:
        return {"id": svc.assign(req.goal_id, req.agent_id, req.priority)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/assignments")
def list_assignments(goal_id: Optional[str] = None, request: Request = None):
    t, u = _identity(request)
    svc = AssignmentService(_db, t, u)
    return {"items": svc.list(goal_id)}

@router.post("/deliverables")
def create_deliverable(req: CreateDeliverable, request: Request):
    t, u = _identity(request)
    svc = DeliverableService(_db, t, u)
    return {"id": svc.create(req.project_id, req.title)}

@router.get("/deliverables")
def list_deliverables(project_id: Optional[str] = None, request: Request = None):
    t, u = _identity(request)
    # Additive enrichment: expose the latest version's status and number on each
    # deliverable so the UI can display and filter by approval state without an
    # N+1 fetch of every version. No schema change; existing columns untouched.
    base = (
        "SELECT d.*,"
        " (SELECT v.status FROM deliverable_versions v"
        "  WHERE v.tenant_id = d.tenant_id AND v.deliverable_id = d.id"
        "  ORDER BY v.version DESC LIMIT 1) AS latest_status,"
        " (SELECT v.version FROM deliverable_versions v"
        "  WHERE v.tenant_id = d.tenant_id AND v.deliverable_id = d.id"
        "  ORDER BY v.version DESC LIMIT 1) AS latest_version"
        " FROM deliverables d"
    )
    if project_id:
        rows = _db.query(base + " WHERE d.tenant_id=? AND d.project_id=? AND d.is_synthetic != 1", (t, project_id))
    else:
        rows = _db.query(base + " WHERE d.tenant_id=? AND d.is_synthetic != 1", (t,))
    return {"items": rows}

@router.post("/deliverables/{did}/versions")
def add_version(did: str, req: AddVersion, request: Request):
    t, u = _identity(request)
    svc = DeliverableService(_db, t, u)
    vid, ver = svc.add_version(did, req.content)
    return {"id": vid, "version": ver}

@router.get("/deliverables/{did}/versions")
def list_versions(did: str, request: Request):
    t, u = _identity(request)
    svc = DeliverableService(_db, t, u)
    return {"items": svc.list_versions(did)}

@router.post("/versions/{vid}/approve")
def approve(vid: str, request: Request):
    t, u = _identity(request)
    svc = DeliverableService(_db, t, u)
    try:
        svc.approve(vid, u)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/versions/{vid}/reject")
def reject(vid: str, req: RejectBody = None, request: Request = None):
    t, u = _identity(request)
    svc = DeliverableService(_db, t, u)
    svc.reject(vid, u, reason=(req.reason if req else ""))
    return {"ok": True}

@router.post("/versions/{vid}/request-changes")
def request_changes(vid: str, req: RejectBody = None, request: Request = None):
    """Request changes on a deliverable version (revision) — distinct from reject.
    The version stays reviewable, flagged requested_changes, awaiting a new
    revision. Never closes the deliverable; human-only."""
    t, u = _identity(request)
    if getattr(request.state, "role", "user") not in ("user", "admin"):
        raise HTTPException(status_code=403, detail="human review required")
    svc = DeliverableService(_db, t, u)
    try:
        svc.request_changes(vid, u, reason=(req.reason if req else ""))
        return {"ok": True, "requested_changes": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/audit/export")
def audit_export(request: Request):
    role = getattr(request.state, "role", "user")
    if role != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    tenant = getattr(request.state, "tenant_id", "local")
    db = Database(path=DB_PATH, tenant_id=tenant)
    rows = db.query("SELECT * FROM memory_audit WHERE tenant_id=?", (tenant,))
    safe = [{k: v for k, v in r.items() if k not in ("detail",)} for r in rows]
    return {"ok": True, "exported": safe}

@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: str, request: Request):
    """Owner-scoped, human-gated goal deletion (removes its assignments + events)."""
    t, u = _identity(request); _require_human(request)
    if not _db.query("SELECT id FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
                     (goal_id, t, u)):
        raise HTTPException(status_code=404, detail="goal not found")
    _db.execute("DELETE FROM goal_events WHERE goal_id=? AND tenant_id=?", (goal_id, t))
    _db.execute("DELETE FROM assignments WHERE goal_id=? AND tenant_id=?", (goal_id, t))
    _db.execute("DELETE FROM goals WHERE id=? AND tenant_id=? AND user_id=?", (goal_id, t, u))
    return {"ok": True, "deleted": "goal"}


@router.delete("/deliverables/{deliverable_id}")
def delete_deliverable(deliverable_id: str, request: Request):
    """Owner-scoped, human-gated deliverable deletion (removes its versions)."""
    t, u = _identity(request); _require_human(request)
    if not _db.query("SELECT id FROM deliverables WHERE id=? AND tenant_id=? AND user_id=?",
                     (deliverable_id, t, u)):
        raise HTTPException(status_code=404, detail="deliverable not found")
    _db.execute("DELETE FROM deliverable_versions WHERE deliverable_id=? AND tenant_id=?",
                (deliverable_id, t))
    _db.execute("DELETE FROM deliverables WHERE id=? AND tenant_id=? AND user_id=?",
                (deliverable_id, t, u))
    return {"ok": True, "deleted": "deliverable"}


def _delete_project_cascade(db, tenant, user, pid) -> bool:
    owned = db.query("SELECT id FROM projects WHERE id=? AND tenant_id=? AND user_id=?",
                     (pid, tenant, user))
    if not owned:
        return False
    gids = [r["id"] for r in db.query(
        "SELECT id FROM goals WHERE project_id=? AND tenant_id=? AND user_id=?",
        (pid, tenant, user))]
    for gid in gids:
        db.execute("DELETE FROM goal_events WHERE goal_id=? AND tenant_id=?", (gid, tenant))
        db.execute("DELETE FROM assignments WHERE goal_id=? AND tenant_id=?", (gid, tenant))
    dids = [r["id"] for r in db.query(
        "SELECT id FROM deliverables WHERE project_id=? AND tenant_id=? AND user_id=?",
        (pid, tenant, user))]
    for did in dids:
        db.execute("DELETE FROM deliverable_versions WHERE deliverable_id=? AND tenant_id=?", (did, tenant))
    db.execute("DELETE FROM goals WHERE project_id=? AND tenant_id=? AND user_id=?", (pid, tenant, user))
    db.execute("DELETE FROM deliverables WHERE project_id=? AND tenant_id=? AND user_id=?", (pid, tenant, user))
    db.execute("DELETE FROM milestones WHERE project_id=? AND tenant_id=?", (pid, tenant))
    db.execute("DELETE FROM projects WHERE id=? AND tenant_id=? AND user_id=?", (pid, tenant, user))
    return True


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request):
    """Owner-scoped, human-gated project deletion (cascades goals/deliverables)."""
    t, u = _identity(request); _require_human(request)
    if not _delete_project_cascade(_db, t, u, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    return {"ok": True, "deleted": "project"}


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: str, request: Request):
    """Owner-scoped, human-gated workspace deletion (cascades all its projects)."""
    t, u = _identity(request); _require_human(request)
    if not _db.query("SELECT id FROM workspaces WHERE id=? AND tenant_id=? AND user_id=?",
                     (workspace_id, t, u)):
        raise HTTPException(status_code=404, detail="workspace not found")
    pids = [r["id"] for r in _db.query(
        "SELECT id FROM projects WHERE workspace_id=? AND tenant_id=? AND user_id=?",
        (workspace_id, t, u))]
    for pid in pids:
        _delete_project_cascade(_db, t, u, pid)
    _db.execute("DELETE FROM workspaces WHERE id=? AND tenant_id=? AND user_id=?",
                (workspace_id, t, u))
    return {"ok": True, "deleted": "workspace"}


@router.get("/health")
def health():
    return {"ok": True}
