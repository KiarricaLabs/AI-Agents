from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.memory import MemoryService
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/memory", tags=["memory"])

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _svc(user_id: str):
    return MemoryService(db=_db, tenant_id=DEFAULT_TENANT)


class ProposeReq(BaseModel):
    user_id: str
    agent_id: str
    kind: str
    key: str
    value: str
    source: str = "conversation"
    confidence: float = 0.5
    expires_at: Optional[str] = None


class ApproveReq(BaseModel):
    user_id: str
    edited_value: Optional[str] = None


class RejectReq(BaseModel):
    user_id: str


class RevokeReq(BaseModel):
    user_id: str


class PrivateReq(BaseModel):
    agent_id: str
    user_id: str
    key: str
    value: str


@router.get("/profile/{user_id}")
def get_profile(user_id: str):
    return {"items": _svc(user_id).list_profile(user_id)}


@router.get("/conversation/{user_id}")
def get_conversation(user_id: str, thread_id: Optional[str] = None):
    return {"items": _svc(user_id).list_conversation(user_id, thread_id)}


@router.post("/conversation")
def add_conversation(user_id: str, content: str, role: str = "user", thread_id: Optional[str] = None):
    _svc(user_id).add_conversation(user_id, content, role, thread_id)
    return {"ok": True}


@router.post("/proposals")
def propose(req: ProposeReq):
    try:
        pid = _svc(req.user_id).propose(req.user_id, req.agent_id, req.kind, req.key, req.value, req.source, req.confidence, req.expires_at)
        return {"ok": True, "proposal_id": pid}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/proposals/{user_id}")
def list_proposals(user_id: str, status: Optional[str] = None):
    return {"proposals": _svc(user_id).list_proposals(user_id, status)}


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: str, req: ApproveReq):
    try:
        _svc(req.user_id).approve(proposal_id, req.user_id, req.edited_value)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str, req: RejectReq):
    try:
        _svc(req.user_id).reject(proposal_id, req.user_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/revoke/{memory_item_id}")
def revoke(memory_item_id: str, req: RevokeReq):
    try:
        _svc(req.user_id).revoke(memory_item_id, req.user_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/audit/{user_id}")
def audit(user_id: str):
    return {"events": _svc(user_id).audit_history(user_id)}