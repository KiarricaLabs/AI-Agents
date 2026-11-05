"""Phase 4 — Task Center & conversation-to-task API.

GET /tasks                    — user-facing task aggregation (Task Center).
POST /conversations/{thread}/to-task — turn an existing conversation into a
                             task-assignment proposal (human approves before any
                             work is created).

All endpoints are human-owned and tenant/user-scoped. Identities come from
request.state (security middleware), never from bodies. The conversation-to-task
path only creates a *proposal*; nothing is created or executed without approval.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.task_center import TaskCenter
from core.work_proposals import WorkProposalService
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(tags=["tasks"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)

_HUMAN_ROLES = {"user", "admin"}
_AGENT_SLUGS = {
    "tutor", "strategist", "executive_assistant",
    "communications", "soundboard", "workspace_architect",
}


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _require_human(request: Request):
    """Human-only mutation gate (user or admin). Mirrors other routers."""
    if getattr(request.state, "role", None) not in ("user", "admin"):
        raise HTTPException(status_code=403, detail="human-only")


def _svc(t: str, u: str) -> WorkProposalService:
    return WorkProposalService(db=_db, tenant_id=t, user_id=u)


@router.get("/tasks")
def list_tasks(request: Request, statuses: Optional[str] = None):
    """Task Center aggregation (read-only). Optional comma-separated statuses."""
    t, u = _identity(request)
    st = [s.strip() for s in (statuses or "").split(",") if s.strip()] or None
    return TaskCenter(_db, t, u).list(st)


class ToTaskReq(BaseModel):
    goal_id: str
    title: str = ""
    description: str = ""
    agent_id: str = ""
    idempotency_key: Optional[str] = None


@router.post("/conversations/{thread_id}/to-task")
def conversation_to_task(thread_id: str, req: ToTaskReq, request: Request):
    """Turn an existing conversation into a task-assignment *proposal*.

    Preserves the originating thread (thread_id) on the proposal so the task
    traces back to the discussion, then to the approved assignment, execution,
    and deliverable. Nothing is created or executed until a human approves the
    proposal. Safe against duplicate submission via an idempotency key.
    """
    t, u = _identity(request)
    role = getattr(request.state, "role", "user")
    if role not in _HUMAN_ROLES:
        raise HTTPException(status_code=403, detail="human approval required")

    goal_id = (req.goal_id or "").strip()
    title = (req.title or "").strip()
    agent = (req.agent_id or "").strip().lower()
    if not goal_id:
        raise HTTPException(status_code=422, detail="goal_id is required")
    if not title:
        raise HTTPException(status_code=422, detail="title is required")
    if agent and agent not in _AGENT_SLUGS:
        raise HTTPException(status_code=422, detail="unknown agent")

    # Validate thread ownership (never leak whether another user's thread exists).
    rows = _db.query(
        "SELECT thread_id FROM conversation_threads WHERE thread_id=? AND tenant_id=? AND user_id=?",
        (thread_id, t, u))
    if not rows:
        raise HTTPException(status_code=404, detail="conversation not found")

    # Validate goal ownership.
    g = _db.query(
        "SELECT id FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
        (goal_id, t, u))
    if not g:
        raise HTTPException(status_code=404, detail="goal not found")

    # Idempotency: same user + thread + goal + title yields one proposal.
    key = (req.idempotency_key or "").strip() or (
        "conv:" + hashlib.sha256(
            f"{t}|{u}|{thread_id}|{goal_id}|{title.lower()}".encode()).hexdigest())
    payload = {"goal_id": goal_id, "title": title,
               "description": (req.description or "").strip()}
    if agent:
        payload["agent_id"] = agent
    try:
        r = _svc(t, u).propose(
            "assignment", agent or "workspace_architect",
            payload=payload, thread_id=thread_id,
            idempotency_key=key, reason="created from conversation")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"proposal_id": r["proposal_id"], "status": r["status"],
            "work_type": "assignment", "thread_id": thread_id,
            "goal_id": goal_id, "reused": bool(r.get("reused", False))}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, request: Request):
    """Owner-scoped, human-gated deletion of a Task Center item.

    Task Center items come in two kinds (see core/task_center.py):

      - proposal-backed: ``task_id == "prop:{proposal_id}"``. Removes the
        originating work proposal and any work_links that reference it.
      - assignment-backed: ``task_id`` is the assignment id. Removes the
        assignment, its execution episodes/events, the originating work
        proposal (and its links), and the conversation work_links.

    The source goal and any project-scoped deliverables are intentionally
    preserved (deleting a task is not deleting a goal or a deliverable).
    Unknown or foreign resources return 404; non-human roles return 403.
    """
    t, u = _identity(request)
    _require_human(request)

    if task_id.startswith("prop:"):
        pid = task_id[len("prop:"):]
        if not pid or not _db.query(
                "SELECT id FROM work_proposals WHERE id=? AND tenant_id=? AND user_id=?",
                (pid, t, u)):
            raise HTTPException(status_code=404, detail="task not found")
        _db.execute(
            "DELETE FROM work_links WHERE tenant_id=? AND work_id=?", (t, pid))
        _db.execute(
            "DELETE FROM work_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (pid, t, u))
        return {"ok": True, "deleted": "task", "kind": "proposal"}

    # Assignment-backed task.
    owned = _db.query(
        "SELECT id FROM assignments WHERE id=? AND tenant_id=? AND user_id=?",
        (task_id, t, u))
    if not owned:
        raise HTTPException(status_code=404, detail="task not found")

    episode_ids = [r["id"] for r in _db.query(
        "SELECT id FROM episodes WHERE tenant_id=? AND user_id=? "
        "AND work_type='assignment' AND work_id=?", (t, u, task_id))]
    for eid in episode_ids:
        _db.execute(
            "DELETE FROM episode_events WHERE episode_id=? AND tenant_id=?", (eid, t))
    _db.execute(
        "DELETE FROM episodes WHERE tenant_id=? AND user_id=? "
        "AND work_type='assignment' AND work_id=?", (t, u, task_id))
    _db.execute(
        "DELETE FROM work_links WHERE tenant_id=? AND work_type='assignment' "
        "AND work_id=?", (t, task_id))

    for p in _db.query(
            "SELECT id FROM work_proposals WHERE tenant_id=? AND user_id=? "
            "AND work_type='assignment' AND result_id=?", (t, u, task_id)):
        _db.execute(
            "DELETE FROM work_links WHERE tenant_id=? AND work_id=?", (t, p["id"]))
        _db.execute(
            "DELETE FROM work_proposals WHERE id=? AND tenant_id=? AND user_id=?",
            (p["id"], t, u))

    _db.execute(
        "DELETE FROM assignments WHERE id=? AND tenant_id=? AND user_id=?",
        (task_id, t, u))
    return {"ok": True, "deleted": "task", "kind": "assignment"}
