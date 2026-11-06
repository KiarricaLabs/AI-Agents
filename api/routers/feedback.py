from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.settings import DB_PATH, DEFAULT_TENANT
from core.feedback import FeedbackService
from storage.database import Database

router = APIRouter(prefix="/feedback", tags=["feedback"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


class FeedbackBody(BaseModel):
    scope_type: str
    scope_id: Optional[str] = None
    agent_id: Optional[str] = None
    task_type: Optional[str] = None
    rating: str
    feedback: str
    output_snapshot: Optional[Dict[str, Any]] = None
    lesson: Optional[str] = None


@router.post("")
def submit(body: FeedbackBody, request: Request):
    tenant, user = _identity(request)
    try:
        return FeedbackService(_db, tenant, user).submit(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("")
def list_feedback(scope_type: Optional[str] = None, scope_id: Optional[str] = None,
                  request: Request = None):
    tenant, user = _identity(request)
    try:
        return {"items": FeedbackService(_db, tenant, user).list(scope_type, scope_id)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{feedback_id}/approve-lesson")
def approve_lesson(feedback_id: str, request: Request):
    tenant, user = _identity(request)
    try:
        return FeedbackService(_db, tenant, user).approve_lesson(feedback_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
