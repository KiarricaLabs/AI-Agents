"""Phase 3 §5-6 — agent-to-agent coordination ledger API (backend only).

Human-gated, owner-scoped endpoints to record, respond to, list, and resolve
durable agent-to-agent coordination, plus a human-visible view of loop-guard
blocks. Identity comes from request.state; every read/write is tenant/user
scoped. This NEVER triggers execution/approval/authorization — it only keeps a
traceable record for human visibility and control.

- GET  /team/comm                list coordination (optionally by thread_id)
- GET  /team/comm/blocked        loop-guard blocks awaiting human attention
- POST /team/comm                record an agent-to-agent request
- POST /team/comm/{id}/respond   record an agent response to an open request
- POST /team/comm/{id}/resolve   mark an entry resolved
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.settings import DB_PATH, DEFAULT_TENANT
from storage.database import Database
from core.agent_comm import AgentCommService

router = APIRouter(prefix="/team/comm", tags=["agent-comm"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _svc(t, u) -> AgentCommService:
    return AgentCommService(_db, t, u)


_HUMAN_ROLES = {"user", "admin"}


def _require_human(request: Request):
    role = getattr(request.state, "role", "user")
    if role not in _HUMAN_ROLES:
        raise HTTPException(status_code=403, detail="human approval required")


class SendBody(BaseModel):
    from_agent: str
    to_agent: str
    content: str
    kind: str = "request"
    thread_id: Optional[str] = None
    parent_id: Optional[str] = None


class RespondBody(BaseModel):
    from_agent: str
    content: str


@router.get("")
def list_comm(thread_id: Optional[str] = None, request: Request = None):
    t, u = _identity(request)
    return {"items": _svc(t, u).list(thread_id)}


@router.get("/blocked")
def list_blocked(request: Request):
    t, u = _identity(request)
    return {"items": _svc(t, u).blocked()}


@router.post("")
def send_comm(body: SendBody, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        return _svc(t, u).send(body.from_agent, body.to_agent, body.content,
                               kind=body.kind, thread_id=body.thread_id,
                               parent_id=body.parent_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{comm_id}/respond")
def respond_comm(comm_id: str, body: RespondBody, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        return _svc(t, u).respond(comm_id, body.from_agent, body.content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{comm_id}/resolve")
def resolve_comm(comm_id: str, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        return _svc(t, u).mark_resolved(comm_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
