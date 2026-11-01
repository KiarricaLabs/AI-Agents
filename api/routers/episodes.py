from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT
from core.episodes import EpisodeService

router = APIRouter(prefix="/episodes", tags=["episodes"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


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
