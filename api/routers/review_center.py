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

from fastapi import APIRouter, Request

from config.settings import DB_PATH, DEFAULT_TENANT
from storage.database import Database
from core.review_center import ReviewCenterService

router = APIRouter(prefix="/team", tags=["review-center"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


@router.get("/review")
def review_center(request: Request):
    """Return every owner-scoped pending decision (goal approvals, plan
    authorizations, step reviews, deliverable reviews, blocked steps)."""
    t, u = _identity(request)
    return ReviewCenterService(_db, t, u).review()
