"""Memory API. Identity is always resolved server-side from request.state."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from core.memory import MemoryService
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/memory", tags=["memory"])

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _svc(tenant_id: str):
    return MemoryService(db=_db, tenant_id=tenant_id)


class ProposeReq(BaseModel):
    agent_id: str
    kind: str
    key: str
    value: str
    source: str = "conversation"
    confidence: float = 0.5
    expires_at: Optional[str] = None


class ApproveReq(BaseModel):
    edited_value: Optional[str] = None


class RejectReq(BaseModel):
    pass


class RevokeReq(BaseModel):
    pass


class ConversationReq(BaseModel):
    content: str
    role: str = "user"
    thread_id: Optional[str] = None


@router.get("/profile")
def get_profile(request: Request):
    t, u = _identity(request)
    return {"items": _svc(t).list_profile(u)}


@router.get("/conversation")
def get_conversation(request: Request, thread_id: Optional[str] = None):
    t, u = _identity(request)
    return {"items": _svc(t).list_conversation(u, thread_id)}


@router.post("/conversation")
def add_conversation(req: ConversationReq, request: Request):
    t, u = _identity(request)
    _svc(t).add_conversation(u, req.content, req.role, req.thread_id)
    return {"ok": True}


@router.post("/proposals")
def propose(req: ProposeReq, request: Request):
    t, u = _identity(request)
    try:
        pid = _svc(t).propose(u, req.agent_id, req.kind, req.key, req.value,
                              req.source, req.confidence, req.expires_at)
        return {"ok": True, "proposal_id": pid}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/proposals")
def list_proposals(request: Request, status: Optional[str] = None):
    t, u = _identity(request)
    return {"proposals": _svc(t).list_proposals(u, status)}


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: str, req: ApproveReq, request: Request):
    t, u = _identity(request)
    try:
        _svc(t).approve(proposal_id, u, req.edited_value)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str, req: RejectReq, request: Request):
    t, u = _identity(request)
    try:
        _svc(t).reject(proposal_id, u)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/revoke/{memory_item_id}")
def revoke(memory_item_id: str, req: RevokeReq, request: Request):
    t, u = _identity(request)
    try:
        _svc(t).revoke(memory_item_id, u)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/audit")
def audit(request: Request):
    t, u = _identity(request)
    return {"events": _svc(t).audit_history(u)}
