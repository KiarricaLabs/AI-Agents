"""Brand API. Identity and role are resolved server-side from request.state only."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.brand import BrandService
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/brand", tags=["brand"])

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _require_admin(request: Request):
    role = getattr(request.state, "role", "user")
    if role != "admin":
        raise HTTPException(status_code=403, detail="admin required")


def _svc(tenant_id: str) -> BrandService:
    return BrandService(db=_db, tenant_id=tenant_id)


def _call(fn):
    """Run a BrandService call, translating ValueError into an HTTP error."""
    try:
        return fn()
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg else 400
        raise HTTPException(status_code=status, detail=msg)


class CreateBrand(BaseModel):
    name: str
    is_default: bool = False


class RenameBrand(BaseModel):
    name: str


class ProposeFact(BaseModel):
    category: str
    key: str
    value: str
    agent_id: Optional[str] = None
    source: str = "manual"
    reason: Optional[str] = None
    context: Optional[str] = None
    confidence: float = 0.5
    base_version: Optional[int] = None


class ApproveReq(BaseModel):
    edited_value: Optional[str] = None


@router.get("")
def list_brands(request: Request):
    t, _u = _identity(request)
    return {"brands": _svc(t).list_brands()}


@router.post("")
def create_brand(req: CreateBrand, request: Request):
    t, u = _identity(request)
    _require_admin(request)
    bid = _call(lambda: _svc(t).create_brand(req.name, user_id=u, is_default=req.is_default))
    return {"id": bid}


@router.get("/default")
def get_default_brand(request: Request):
    t, _u = _identity(request)
    return {"brand": _svc(t).get_default_brand()}


@router.get("/{brand_id}")
def get_brand(brand_id: str, request: Request):
    t, _u = _identity(request)
    return _call(lambda: _svc(t).get_brand(brand_id))


@router.post("/{brand_id}/rename")
def rename_brand(brand_id: str, req: RenameBrand, request: Request):
    t, u = _identity(request)
    _require_admin(request)
    _call(lambda: _svc(t).rename_brand(brand_id, req.name, user_id=u))
    return {"ok": True}


@router.post("/{brand_id}/default")
def set_default_brand(brand_id: str, request: Request):
    t, u = _identity(request)
    _require_admin(request)
    _call(lambda: _svc(t).set_default_brand(brand_id, user_id=u))
    return {"ok": True}


@router.get("/{brand_id}/facts")
def list_facts(brand_id: str, request: Request, category: Optional[str] = None):
    t, _u = _identity(request)
    return {"facts": _call(lambda: _svc(t).list_facts(brand_id, category))}


@router.get("/{brand_id}/versions")
def all_versions(brand_id: str, request: Request):
    t, _u = _identity(request)
    return {"versions": _call(lambda: _svc(t).all_versions(brand_id))}


@router.get("/{brand_id}/facts/{category}/{key}/versions")
def fact_versions(brand_id: str, category: str, key: str, request: Request):
    t, _u = _identity(request)
    return {"versions": _call(lambda: _svc(t).fact_versions(brand_id, category, key))}


@router.post("/{brand_id}/proposals")
def propose(brand_id: str, req: ProposeFact, request: Request):
    t, u = _identity(request)
    pid = _call(lambda: _svc(t).propose(
        brand_id, req.category, req.key, req.value,
        agent_id=req.agent_id, source=req.source, reason=req.reason, context=req.context,
        confidence=req.confidence, base_version=req.base_version, user_id=u))
    return {"proposal_id": pid}


@router.get("/{brand_id}/proposals")
def list_proposals(brand_id: str, request: Request, status: Optional[str] = None):
    t, _u = _identity(request)
    return {"proposals": _call(lambda: _svc(t).list_proposals(brand_id, status))}


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: str, req: ApproveReq, request: Request):
    t, u = _identity(request)
    _require_admin(request)
    fact_id = _call(lambda: _svc(t).approve(proposal_id, u, req.edited_value))
    return {"fact_id": fact_id}


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str, request: Request):
    t, u = _identity(request)
    _require_admin(request)
    _call(lambda: _svc(t).reject(proposal_id, u))
    return {"ok": True}


@router.post("/facts/{fact_id}/revoke")
def revoke(fact_id: str, request: Request):
    t, u = _identity(request)
    _require_admin(request)
    _call(lambda: _svc(t).revoke(fact_id, u))
    return {"ok": True}


@router.get("/{brand_id}/history")
def history(brand_id: str, request: Request):
    t, _u = _identity(request)
    return {"events": _call(lambda: _svc(t).history(brand_id))}
