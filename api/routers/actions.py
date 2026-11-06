"""Approval-gated pending outward actions for structured projects."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from config.settings import DB_PATH, DEFAULT_TENANT
from core.action_executor import ActionExecutor
from storage.database import Database

router = APIRouter(prefix="/actions", tags=["pending-actions"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


class CreateActionRequest(BaseModel):
    project_id: str
    task_id: str | None = None
    agent: str = Field(min_length=1)
    type: str = Field(pattern="^(email|dm|ig_post)$")
    payload: dict


class EditActionRequest(BaseModel):
    payload: dict


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _action(tenant, user, action_id):
    rows = _db.query(
        "SELECT * FROM pending_actions WHERE id=? AND tenant_id=? AND user_id=?",
        (action_id, tenant, user))
    if not rows:
        raise HTTPException(status_code=404, detail="action not found")
    item = dict(rows[0])
    item["payload"] = json.loads(item["payload"])
    if item["result"]:
        item["result"] = json.loads(item["result"])
    return item


@router.get("")
def list_actions(request: Request, status: str = "pending"):
    tenant, user = _identity(request)
    rows = _db.query(
        "SELECT * FROM pending_actions WHERE tenant_id=? AND user_id=? AND status=? "
        "ORDER BY created_at DESC", (tenant, user, status))
    items = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        if item["result"]:
            item["result"] = json.loads(item["result"])
        items.append(item)
    return {"items": items}


@router.post("")
def create_action(body: CreateActionRequest, request: Request):
    tenant, user = _identity(request)
    project = _db.query(
        "SELECT id FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?",
        (body.project_id, tenant, user))
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    now = datetime.now(timezone.utc).isoformat()
    action_id = str(uuid.uuid4())
    _db.execute(
        "INSERT INTO pending_actions "
        "(id,project_id,task_id,tenant_id,user_id,agent,type,payload,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (action_id, body.project_id, body.task_id, tenant, user, body.agent,
         body.type, json.dumps(body.payload), "pending", now, now))
    return _action(tenant, user, action_id)


@router.post("/{action_id}/approve")
def approve_action(action_id: str, request: Request):
    tenant, user = _identity(request)
    item = _action(tenant, user, action_id)
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="action is not pending")
    now = datetime.now(timezone.utc).isoformat()
    _db.execute(
        "UPDATE pending_actions SET status='approved', updated_at=? "
        "WHERE id=? AND tenant_id=? AND user_id=?", (now, action_id, tenant, user))
    try:
        result = ActionExecutor(_db, tenant, user).execute(action_id)
    except Exception as exc:
        _db.execute(
            "UPDATE pending_actions SET status='failed', result=?, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (json.dumps({"error": str(exc)}), datetime.now(timezone.utc).isoformat(),
             action_id, tenant, user))
        raise HTTPException(status_code=502, detail=f"action executor failed: {exc}") from exc
    return {"action": _action(tenant, user, action_id), "execution": result}


@router.post("/{action_id}/reject")
def reject_action(action_id: str, request: Request):
    tenant, user = _identity(request)
    item = _action(tenant, user, action_id)
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="action is not pending")
    _db.execute(
        "UPDATE pending_actions SET status='rejected', updated_at=? "
        "WHERE id=? AND tenant_id=? AND user_id=?",
        (datetime.now(timezone.utc).isoformat(), action_id, tenant, user))
    return _action(tenant, user, action_id)


@router.post("/{action_id}/edit")
def edit_action(action_id: str, body: EditActionRequest, request: Request):
    tenant, user = _identity(request)
    item = _action(tenant, user, action_id)
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="only pending actions can be edited")
    _db.execute(
        "UPDATE pending_actions SET payload=?, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
        (json.dumps(body.payload), datetime.now(timezone.utc).isoformat(), action_id, tenant, user))
    return _action(tenant, user, action_id)
