"""M10 Phase A — work proposal API (read-only list/detail).

Authenticated, tenant/user-scoped. Identities always come from
``request.state`` (set by security middleware); never from request bodies or
headers. No approval/execution endpoints in Phase A; proposals are stored only.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from core.work_proposals import WorkProposalService
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/work", tags=["work"])

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _svc(t: str, u: str):
    return WorkProposalService(_db, t, u)


@router.get("/proposals")
def list_proposals(request: Request, status: Optional[str] = None):
    t, u = _identity(request)
    return {"items": _svc(t, u).list(status)}


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, request: Request):
    t, u = _identity(request)
    p = _svc(t, u).get(proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return p
