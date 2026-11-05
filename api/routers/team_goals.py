"""T2-C-3 — TeamGoal + coordination-plan API (backend only).

Exposes authenticated, tenant/user-scoped endpoints for reviewing TeamGoals and
their coordination plans and for human-authorized plan approval.

Endpoints
---------
- GET   /team/goals                       list owner's TeamGoals
- GET   /team/goals/{id}                  retrieve one TeamGoal (steps + approvals)
- GET   /team/goals/{id}/coordination-plan   transient validated plan (review-only)
- POST  /team/goals/{id}/approve          human: approve the TeamGoal
- POST  /team/goals/{id}/reject           human: reject the TeamGoal (terminal)
- POST  /team/goals/{id}/coordination-plan/authorize  human: persist authoritative plan

Safety: identities come from ``request.state`` (set by security middleware);
never from bodies/headers. Human-only actions require ``request.state.role`` in
{"user","admin"} (fail closed). All reads/writes are owner-scoped; a missing or
foreign record returns 404 rather than leaking existence. Authorization NEVER
starts an episode, dispatches an agent, executes a tool, or starts background
work, and never mutates the TeamGoal status.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.settings import DB_PATH, DEFAULT_TENANT
from storage.database import Database
from core.team_goal import (
    TeamGoalService,
    TeamGoalNotFound,
    TeamGoalAlreadyDecided,
    TeamGoalApprovalNotPermitted,
    TeamGoalInvalidTransition,
)
from core.coordination_plan import (
    CoordinationPlanService,
    CoordinationPlanNotFound,
    CoordinationPlanInvalid,
    CoordinationPlanPermissionError,
)

router = APIRouter(prefix="/team/goals", tags=["team-goals"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)

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


def _goal_svc(t: str, u: str):
    return TeamGoalService(_db, t, u)


def _plan_svc(t: str, u: str):
    return CoordinationPlanService(_db, t, u)


class RejectGoalBody(BaseModel):
    reason: Optional[str] = None


@router.get("")
def list_team_goals(request: Request, status: Optional[str] = None):
    t, u = _identity(request)
    return {"items": _goal_svc(t, u).list(status)}


@router.get("/{team_goal_id}")
def get_team_goal(team_goal_id: str, request: Request):
    t, u = _identity(request)
    tg = _goal_svc(t, u).get(team_goal_id)
    if tg is None:
        raise HTTPException(status_code=404, detail="team goal not found")
    return tg


@router.get("/{team_goal_id}/coordination-plan")
def review_coordination_plan(team_goal_id: str, request: Request):
    """Transient, validated coordination plan for review. Never persists and
    never executes. Returns 404 for an unknown/foreign goal and 422 when the
    goal is not eligible or the plan is invalid."""
    t, u = _identity(request)
    try:
        plan = _plan_svc(t, u).review(team_goal_id)
    except CoordinationPlanNotFound:
        raise HTTPException(status_code=404, detail="team goal not found")
    except CoordinationPlanInvalid as e:
        raise HTTPException(status_code=422, detail=str(e))
    return plan


@router.post("/{team_goal_id}/approve")
def approve_team_goal(team_goal_id: str, request: Request):
    """Human approval of the TeamGoal (separate from plan authorization). Never
    starts execution and does not create a coordination plan."""
    t, u = _identity(request)
    _require_human(request)
    try:
        return _goal_svc(t, u).approve(team_goal_id, u)
    except TeamGoalNotFound:
        raise HTTPException(status_code=404, detail="team goal not found")
    except TeamGoalApprovalNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to approve this team goal")
    except TeamGoalAlreadyDecided:
        raise HTTPException(status_code=409, detail="team goal already decided")


@router.post("/{team_goal_id}/reject")
def reject_team_goal(team_goal_id: str, body: RejectGoalBody = None, request: Request = None):
    """Human rejection of the TeamGoal (terminal unless explicitly reopened)."""
    t, u = _identity(request)
    _require_human(request)
    try:
        _goal_svc(t, u).reject(team_goal_id, u, reason=(body.reason if body else None))
    except TeamGoalNotFound:
        raise HTTPException(status_code=404, detail="team goal not found")
    except TeamGoalApprovalNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to reject this team goal")
    except (TeamGoalAlreadyDecided, TeamGoalInvalidTransition):
        raise HTTPException(status_code=409, detail="invalid transition for this team goal")
    return {"ok": True, "status": "rejected"}


@router.post("/{team_goal_id}/coordination-plan/authorize")
def authorize_coordination_plan(team_goal_id: str, request: Request):
    """Human authorization that persists the validated coordination plan as the
    authoritative execution source. Idempotent; atomic; refuses invalid plans and
    steps with zero effective permissions. NEVER starts execution."""
    t, u = _identity(request)
    _require_human(request)
    try:
        return _plan_svc(t, u).authorize(team_goal_id, u)
    except CoordinationPlanNotFound:
        raise HTTPException(status_code=404, detail="team goal not found")
    except CoordinationPlanPermissionError:
        raise HTTPException(status_code=403, detail="not permitted to authorize this plan")
    except CoordinationPlanInvalid as e:
        raise HTTPException(status_code=422, detail=str(e))
