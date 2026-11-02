from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT
from core.episodes import (
    EpisodeService,
    EpisodeNotFound,
    EpisodeNotCompleted,
    MissingCompletionEvidence,
    GoalNotFound,
    StaleGoalVersion,
    GoalCompletionConflict,
)

router = APIRouter(prefix="/episodes", tags=["episodes"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _require_human(request: Request):
    role = getattr(request.state, "role", "user")
    if role not in {"user", "admin"}:
        raise HTTPException(status_code=403, detail="human action required")


@router.get("")
def list_episodes(request: Request):
    t, u = _identity(request)
    rows = _db.query("SELECT * FROM episodes WHERE tenant_id=? AND user_id=?", (t, u))
    return {"items": rows}


@router.get("/{eid}")
def get_episode(eid: str, request: Request):
    t, u = _identity(request)
    es = EpisodeService(db=_db, tenant_id=t, user_id=u)
    ep = es.get(eid)
    if not ep:
        raise HTTPException(status_code=404, detail="not found")
    events = _db.query("SELECT * FROM episode_events WHERE tenant_id=? AND episode_id=? ORDER BY created_at", (t, eid))
    return {"episode": ep, "events": events}


@router.post("/{eid}/cancel")
def cancel(eid: str, request: Request):
    t, u = _identity(request)
    es = EpisodeService(db=_db, tenant_id=t, user_id=u)
    ok = es.cancel(eid)
    return {"ok": ok}


@router.post("/{eid}/resume")
def resume(eid: str, request: Request):
    t, u = _identity(request)
    es = EpisodeService(db=_db, tenant_id=t, user_id=u)
    ok = es.recover(eid, lambda eid, prog, cp: None)
    return {"ok": ok}


class CheckpointBody(BaseModel):
    progress: float
    evidence: dict


class CompleteBody(BaseModel):
    evidence: dict


@router.post("/{eid}/apply")
def apply_completed(eid: str, request: Request):
    """Human-only, owner-scoped application of a completed episode's evidence
    to its referenced goal. One application per episode; version-guarded; uses
    only persisted evidence (no client-supplied evidence/progress)."""
    t, u = _identity(request)
    _require_human(request)
    es = EpisodeService(db=_db, tenant_id=t, user_id=u)
    try:
        result = es.apply_completed_episode(eid, u)
    except (EpisodeNotFound, GoalNotFound):
        raise HTTPException(status_code=404, detail="resource not found")
    except (EpisodeNotCompleted, MissingCompletionEvidence, GoalCompletionConflict) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except StaleGoalVersion as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result


@router.post("/{eid}/checkpoint")
def checkpoint(eid: str, body: CheckpointBody, request: Request):
    t, u = _identity(request)
    _require_human(request)
    es = EpisodeService(db=_db, tenant_id=t, user_id=u)
    if not es.get(eid):
        raise HTTPException(status_code=404, detail="episode not found")
    try:
        ok = es.checkpoint_with_evidence(eid, body.progress, body.evidence)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not ok:
        raise HTTPException(status_code=409, detail="episode cannot advance in its current state")
    return {"ok": True, "episode_id": eid, "progress": body.progress}


@router.post("/{eid}/complete")
def complete(eid: str, body: CompleteBody, request: Request):
    t, u = _identity(request)
    _require_human(request)
    es = EpisodeService(db=_db, tenant_id=t, user_id=u)
    if not es.get(eid):
        raise HTTPException(status_code=404, detail="episode not found")
    try:
        ok = es.complete_with_evidence(eid, body.evidence)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not ok:
        raise HTTPException(status_code=409, detail="episode cannot be completed in its current state")
    return {"ok": True, "episode_id": eid, "status": "done"}
