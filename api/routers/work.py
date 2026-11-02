"""M10 Phase A + Phase C — work proposal API.

Phase A: authenticated, tenant/user-scoped read-only list/detail of proposals.
Phase C adds human-controlled approval and rejection endpoints. Identities
always come from ``request.state`` (set by security middleware); never from
request bodies or headers. Human-only actions require ``request.state.role`` in
``{"user","admin"}`` (fail closed). Approval/rejection never returns internal
exception details or leaks the existence of another user's proposal.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.work_proposals import (
    WorkProposalService,
    ProposalNotFound,
    ProposalAlreadyDecided,
    StaleProposal,
    ApprovalNotPermitted,
    ProposalExecutionFailed,
    ProposalValidationError,
    TransientApprovalError,
)
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/work", tags=["work"])

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)

# Verified human roles allowed to approve/reject work proposals. Agents have no
# API surface with these roles; fail closed for anything else.
_HUMAN_ROLES = {"user", "admin"}


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _require_human(request: Request):
    role = getattr(request.state, "role", "user")
    if role not in _HUMAN_ROLES:
        raise HTTPException(status_code=403, detail="human approval required")


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


@router.get("/feed")
def get_feed(request: Request):
    """Consolidated proposal/decision feed (read-only)."""
    t, u = _identity(request)
    return {"items": _svc(t, u).list_feed()}


@router.get("/links")
def links_for_thread(request: Request, thread_id: Optional[str] = None):
    """Conversation thread -> approved linked work (read-only)."""
    t, u = _identity(request)
    return {"items": _svc(t, u).links_for_thread(thread_id)}


@router.get("/links/work/{work_type}/{work_id}")
def links_to_thread(work_type: str, work_id: str, request: Request):
    """Work record -> originating conversation thread(s) (read-only)."""
    t, u = _identity(request)
    try:
        threads = _svc(t, u).threads_for_work(work_type, work_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="unsupported work type")
    return {"work_type": work_type, "work_id": work_id, "threads": threads}


class RejectBody(BaseModel):
    reason: Optional[str] = None


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        result = _svc(t, u).approve(proposal_id, u)
    except ProposalNotFound:
        raise HTTPException(status_code=404, detail="proposal not found")
    except ApprovalNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to approve this proposal")
    except ProposalAlreadyDecided:
        raise HTTPException(status_code=409, detail="proposal already decided")
    except StaleProposal:
        raise HTTPException(status_code=422, detail="proposal is no longer valid; a parent record changed or is missing")
    except ProposalValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ProposalExecutionFailed:
        raise HTTPException(status_code=409, detail="proposal could not be executed")
    except TransientApprovalError:
        raise HTTPException(status_code=503, detail="approval temporarily unavailable; try again")
    return result


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, body: RejectBody = None, request: Request = None):
    t, u = _identity(request)
    _require_human(request)
    try:
        _svc(t, u).reject(proposal_id, u, reason=(body.reason if body else None))
    except ProposalNotFound:
        raise HTTPException(status_code=404, detail="proposal not found")
    except ProposalAlreadyDecided:
        raise HTTPException(status_code=409, detail="proposal already decided")
    return {"ok": True, "status": "rejected"}
