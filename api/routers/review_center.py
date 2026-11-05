"""Phase 7 §13 — Review & Action Center API (backend only).

Read-only, human-gated aggregation of everything that needs the owner's
attention across their TeamGoals/plans/executions/steps/deliverables.

- GET /team/review    list all owner-scoped pending action items + counts.

Identity comes from request.state; all reads are tenant/user-scoped; a foreign
owner sees only their own items. This endpoint is READ-ONLY (no mutation, no
approval, no plan authorization, no execution) — acting happens on the existing
human-only endpoints (approve, authorize, step review, deliverable review).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.settings import DB_PATH, DEFAULT_TENANT
from storage.database import Database
from core.review_center import ReviewCenterService

router = APIRouter(prefix="/team", tags=["review-center"])
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


@router.get("/review")
def review_center(request: Request):
    """Return every owner-scoped pending decision (goal approvals, plan
    authorizations, step reviews, deliverable reviews, blocked steps)."""
    t, u = _identity(request)
    return ReviewCenterService(_db, t, u).review()


class DismissReq(BaseModel):
    type: str
    key: str


@router.post("/review/dismiss")
def dismiss_item(req: DismissReq, request: Request):
    """Human-only, owner-scoped hiding of one review item without deleting
    the underlying evidence. Idempotent."""
    t, u = _identity(request)
    _require_human(request)
    svc = ReviewCenterService(_db, t, u)
    try:
        return svc.dismiss(req.type, req.key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/review/dismiss")
def undismiss_item(type: str, key: str, request: Request):
    """Human-only, owner-scoped restore of a dismissed review item."""
    t, u = _identity(request)
    _require_human(request)
    svc = ReviewCenterService(_db, t, u)
    try:
        return svc.undismiss(type, key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
