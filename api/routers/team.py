"""AI Team 2.0 (T2-A) — team chat + plan proposal API (backend only).

Provides the unified "coordinated team" surface:
- POST /team/threads                      create a 'team' or 'project' thread
- POST /team/threads/{thread}/participants add an agent to a team/project thread
- POST /team/messages                     route a shared message to relevant agents
- POST /team/plans                        propose a coordinated plan (existing work_proposals)
- POST /team/plans/{proposal_id}/revision create a revision (version+1, revision_of)
- GET  /team/plans                        list plan proposals
- GET  /team/plans/{proposal_id}          get one plan proposal
- POST /team/milestones                   create a milestone (additive)
- POST /team/dependencies                 create a dependency edge (additive)

Safety: everything routes through tenant/user-scoped identity from request.state.
Plan proposals reuse WorkProposalService (single state machine). Proposing a plan
creates NO workspace records and triggers NO execution. Approving is handled by
the existing /work/proposals approval path (plan approval execution is T2-B).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.settings import DB_PATH, DEFAULT_TENANT
from storage.database import Database
from core.runtime import load_registry, build_runtime
from core.team_router import TeamRouter, DEFAULT_PLAN_COORDINATOR
from core.work_proposals import WorkProposalService
from core.memory import MemoryService

router = APIRouter(prefix="/team", tags=["ai-team"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)

_HUMAN_ROLES = {"user", "admin"}


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ thread model
class ThreadCreateReq(BaseModel):
    title: str
    thread_type: str = "team"  # 'team' | 'project'
    workspace_id: Optional[str] = None


# ------------------------------------------------------------------ plan model
class PlanProposeReq(BaseModel):
    title: str
    agent_id: str = "strategist"          # coordinator (suggestion, not a grant)
    description: str = ""
    milestones: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    deliverables: List[Dict[str, Any]] = []
    success_criteria: List[str] = []
    thread_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class PlanRevisionReq(BaseModel):
    agent_id: str = "strategist"
    payload_updates: Dict[str, Any] = {}
    thread_id: Optional[str] = None
    reason: Optional[str] = None
    idempotency_key: Optional[str] = None


class TeamMessageReq(BaseModel):
    message: str
    thread_id: Optional[str] = None
    project_id: Optional[str] = None
    subject_agent: Optional[str] = None


class ParticipantReq(BaseModel):
    agent_id: str


class MilestoneReq(BaseModel):
    project_id: str
    title: str
    order: int = 0
    deadline: Optional[str] = None


class DependencyReq(BaseModel):
    from_type: str   # 'task' | 'milestone'
    from_id: str
    to_type: str
    to_id: str


# ------------------------------------------------------------------ thread
@router.post("/threads")
def create_thread(req: ThreadCreateReq, request: Request):
    t, u = _identity(request)
    _require_human(request)
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")
    tt = (req.thread_type or "team").strip()
    if tt not in ("team", "project"):
        raise HTTPException(status_code=422, detail="thread_type must be 'team' or 'project'")
    wid = req.workspace_id
    if tt == "project":
        if not wid:
            raise HTTPException(status_code=422, detail="project threads require workspace_id")
        ws = _db.query("SELECT id FROM workspaces WHERE id=? AND tenant_id=? AND user_id=?",
                       (wid, t, u))
        if not ws:
            raise HTTPException(status_code=404, detail="workspace not found")
    tid = str(uuid.uuid4())
    svc = MemoryService(db=_db, tenant_id=t)
    # Create the thread; set thread_type + workspace_id after (MemoryService
    # inserts without those columns). Tenant/user enforced by MemoryService.
    svc.get_or_create_thread(u, tid, None, title)
    _db.execute(
        "UPDATE conversation_threads SET thread_type=?, workspace_id=? "
        "WHERE thread_id=? AND tenant_id=? AND user_id=?",
        (tt, wid, tid, t, u))
    return {"thread_id": tid, "thread_type": tt, "workspace_id": wid}


@router.post("/threads/{thread_id}/participants")
def add_participant(thread_id: str, req: ParticipantReq, request: Request):
    t, u = _identity(request)
    _require_human(request)
    ag = (req.agent_id or "").strip().lower()
    from core.work_proposals import AGENT_SLUGS
    if ag not in AGENT_SLUGS:
        raise HTTPException(status_code=422, detail="unknown agent")
    owned = _db.query(
        "SELECT thread_id FROM conversation_threads WHERE thread_id=? AND tenant_id=? AND user_id=?",
        (thread_id, t, u))
    if not owned:
        raise HTTPException(status_code=404, detail="thread not found")
    _db.execute(
        "INSERT OR IGNORE INTO conversation_participants "
        "(id, thread_id, agent_id, tenant_id, user_id, joined_at) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), thread_id, ag, t, u, _now()))
    return {"thread_id": thread_id, "agent_id": ag, "added": True}


@router.post("/messages")
def team_message(req: TeamMessageReq, request: Request):
    """Route a shared team message to relevant agents (hybrid routing)."""
    t, u = _identity(request)
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(status_code=422, detail="message must not be empty")

    reg = load_registry()
    orch = build_runtime(_db, t, u)

    def persist(tid, agent_id, role, content):
        if not tid:
            return
        MemoryService(db=_db, tenant_id=t).add_conversation(u, content, role, tid)

    router_ctx: Dict[str, Any] = {"thread_id": req.thread_id}
    if req.subject_agent:
        subject = req.subject_agent.strip().lower()
        if subject not in reg.list():
            raise HTTPException(status_code=422, detail="unknown agent")
        router_ctx["subject_agent"] = subject
    if req.project_id:
        owned = _db.query(
            "SELECT id, name FROM projects WHERE id=? AND tenant_id=? AND user_id=?",
            (req.project_id, t, u))
        if owned:
            router_ctx["project_id"] = req.project_id
            router_ctx["project_name"] = owned[0]["name"]

    try:
        result = TeamRouter(reg, orch, t, u,
                            coordinator=DEFAULT_PLAN_COORDINATOR).dispatch_team(msg, router_ctx, persist)
        # Phase 8 §15: record completed progress for each agent that responded so
        # the command center can show what the team did, without re-running anyone.
        if req.thread_id and result.get("responses"):
            from core.progress import ProgressService
            prog = ProgressService(_db, t, u)
            for resp in result["responses"]:
                try:
                    prog.record(req.thread_id, resp.get("agent", "agent"), "completed",
                                (resp.get("reply") or "")[:200] or None)
                except ValueError:
                    pass
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return result


# ------------------------------------------------------------------ plans
@router.post("/plans")
def propose_plan(req: PlanProposeReq, request: Request):
    t, u = _identity(request)
    _require_human(request)
    agent = (req.agent_id or "strategist").strip().lower()
    from core.work_proposals import AGENT_SLUGS, WorkProposalService
    if agent not in AGENT_SLUGS:
        raise HTTPException(status_code=422, detail="unknown agent")
    payload = {
        "title": (req.title or "").strip(),
        "description": (req.description or ""),
        "version": 1,
        "milestones": req.milestones or [],
        "tasks": req.tasks or [],
        "deliverables": req.deliverables or [],
        "success_criteria": req.success_criteria or [],
        "coordinator_agent": agent,
    }
    key = req.idempotency_key or _plan_key(t, u, payload)
    try:
        r = WorkProposalService(_db, t, u).propose(
            "plan", agent, action="propose", payload=payload,
            thread_id=req.thread_id, idempotency_key=key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"proposal_id": r["proposal_id"], "status": r["status"],
            "reused": bool(r.get("reused", False))}


@router.post("/plans/{proposal_id}/revision")
def revise_plan(proposal_id: str, req: PlanRevisionReq, request: Request):
    t, u = _identity(request)
    _require_human(request)
    agent = (req.agent_id or "strategist").strip().lower()
    from core.work_proposals import AGENT_SLUGS, WorkProposalService
    if agent not in AGENT_SLUGS:
        raise HTTPException(status_code=422, detail="unknown agent")
    key = req.idempotency_key or _revision_key(t, u, proposal_id, req.payload_updates)
    try:
        r = WorkProposalService(_db, t, u).revision_plan(
            proposal_id, agent, payload_updates=req.payload_updates or {},
            thread_id=req.thread_id, reason=req.reason, idempotency_key=key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"proposal_id": r["proposal_id"], "status": r["status"],
            "reused": bool(r.get("reused", False)), "revision_of": proposal_id}


@router.get("/plans")
def list_plans(request: Request, status: Optional[str] = None):
    t, u = _identity(request)
    return {"plans": WorkProposalService(_db, t, u).list(status)}


@router.get("/plans/{proposal_id}")
def get_plan(proposal_id: str, request: Request):
    t, u = _identity(request)
    p = WorkProposalService(_db, t, u).get(proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="plan proposal not found")
    return p


# ------------------------------------------------------------------ milestones / dependencies (additive runtime records, T2-A)
@router.post("/milestones")
def create_milestone(req: MilestoneReq, request: Request):
    t, u = _identity(request)
    _require_human(request)
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title required")
    owned = _db.query("SELECT id FROM projects WHERE id=? AND tenant_id=? AND user_id=?",
                      (req.project_id, t, u))
    if not owned:
        raise HTTPException(status_code=404, detail="project not found")
    mid = str(uuid.uuid4())
    _db.execute(
        "INSERT INTO milestones (id,tenant_id,user_id,project_id,title,ord,status,deadline,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (mid, t, u, req.project_id, title, int(req.order), "planned",
         req.deadline, _now(), _now()))
    return {"milestone_id": mid, "status": "planned"}


@router.post("/dependencies")
def create_dependency(req: DependencyReq, request: Request):
    t, u = _identity(request)
    _require_human(request)
    if req.from_type not in ("task", "milestone") or req.to_type not in ("task", "milestone"):
        raise HTTPException(status_code=422, detail="from_type/to_type must be 'task' or 'milestone'")
    did = str(uuid.uuid4())
    _db.execute(
        "INSERT OR IGNORE INTO dependencies "
        "(id,tenant_id,user_id,from_type,from_id,to_type,to_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (did, t, u, req.from_type, req.from_id, req.to_type, req.to_id, _now()))
    return {"dependency_id": did, "created": True}


# ------------------------------------------------------------------ helpers
def _require_human(request: Request):
    role = getattr(request.state, "role", "user")
    if role not in _HUMAN_ROLES:
        raise HTTPException(status_code=403, detail="human approval required")


def _plan_key(t: str, u: str, payload: Dict[str, Any]) -> str:
    import hashlib, json as _j
    return hashlib.sha256(
        f"{t}|{u}|plan|propose|v{payload.get('version')}|{payload.get('title')}".encode("utf-8")
    ).hexdigest()


def _revision_key(t: str, u: str, proposal_id: str, updates: Dict[str, Any]) -> str:
    import hashlib, json as _j
    return hashlib.sha256(
        f"{t}|{u}|plan|revise|{proposal_id}|{_j.dumps(updates, sort_keys=True, default=str)}".encode("utf-8")
    ).hexdigest()
