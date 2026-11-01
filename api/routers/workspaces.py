from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService, DeliverableService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
TENANT = DEFAULT_TENANT
USER = "local"


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
class ApprovalReq(BaseModel):
    decision: str  # approve/reject


@router.post("")
def create_workspace(req: CreateWorkspace):
    svc = WorkspaceService(_db, TENANT, USER)
    return {"id": svc.create(req.name)}

@router.get("")
def list_workspaces():
    svc = WorkspaceService(_db, TENANT, USER)
    return {"items": svc.list()}

@router.post("/projects")
def create_project(req: CreateProject):
    svc = ProjectService(_db, TENANT, USER)
    return {"id": svc.create(req.workspace_id, req.name)}

@router.get("/projects")
def list_projects(workspace_id: Optional[str] = None):
    svc = ProjectService(_db, TENANT, USER)
    return {"items": svc.list(workspace_id)}

@router.post("/goals")
def create_goal(req: CreateGoal):
    svc = GoalService(_db, TENANT, USER)
    return {"id": svc.create(req.project_id, req.title, req.priority)}

@router.get("/goals")
def list_goals(project_id: Optional[str] = None):
    svc = GoalService(_db, TENANT, USER)
    return {"items": svc.list(project_id)}

@router.post("/assignments")
def assign(req: AssignReq):
    svc = AssignmentService(_db, TENANT, USER)
    try:
        return {"id": svc.assign(req.goal_id, req.agent_id, req.priority)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/assignments")
def list_assignments(goal_id: Optional[str] = None):
    svc = AssignmentService(_db, TENANT, USER)
    return {"items": svc.list(goal_id)}

@router.post("/deliverables")
def create_deliverable(req: CreateDeliverable):
    svc = DeliverableService(_db, TENANT, USER)
    return {"id": svc.create(req.project_id, req.title)}

@router.post("/deliverables/{did}/versions")
def add_version(did: str, req: AddVersion):
    svc = DeliverableService(_db, TENANT, USER)
    vid, ver = svc.add_version(did, req.content)
    return {"id": vid, "version": ver}

@router.get("/deliverables/{did}/versions")
def list_versions(did: str):
    svc = DeliverableService(_db, TENANT, USER)
    return {"items": svc.list_versions(did)}

@router.post("/versions/{vid}/approve")
def approve(vid: str):
    svc = DeliverableService(_db, TENANT, USER)
    try:
        svc.approve(vid, USER)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/versions/{vid}/reject")
def reject(vid: str):
    svc = DeliverableService(_db, TENANT, USER)
    svc.reject(vid, USER)
    return {"ok": True}

@router.get("/health")
def health():
    return {"ok": True}
EOF