"""Phase 8 §15 — progress API (read-mostly).

Listing is owner-scoped. POST is human-gated and available for the human to log
a blocker/note, but agents never get an open self-report surface; progress is
primarily written by the backend team-run dispatcher. Identity comes from
request.state, never the body.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.progress import ProgressService
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/team/progress", tags=["ai-team"])
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


class RecordReq(BaseModel):
    thread_id: str
    agent_id: str
    status: str
    detail: Optional[str] = None


@router.get("")
def list_progress(request: Request, thread_id: Optional[str] = None):
    t, u = _identity(request)
    return {"items": ProgressService(_db, t, u).list(thread_id)}


@router.post("/record")
def record(req: RecordReq, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        r = ProgressService(_db, t, u).record(req.thread_id, req.agent_id, req.status, req.detail)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return r
