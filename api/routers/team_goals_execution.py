"""T2-C-4 — Coordination execution API (backend only).

Human-initiated, step-by-step execution of an already-authorized coordination
plan. Endpoints:

- POST /team/goals/plans/{plan_id}/execution/initiate   human: start a run (idempotent)
- POST /team/goals/plans/{plan_id}/execution/{execution_id}/step/execute
                                                       human: run the NEXT eligible step
- POST /team/goals/plans/{plan_id}/execution/{execution_id}/step/{seq}/review
                                                       human: accept / revision / reject a step
- POST /team/goals/plans/{plan_id}/execution/{execution_id}/aggregate
                                                       human: build consolidated deliverable
- POST /team/goals/plans/{plan_id}/execution/{execution_id}/deliverable/review
                                                       human: final accept / revision / reject
- GET  /team/goals/plans/{plan_id}/execution/{execution_id}
                                                       read: run + step + deliverable status

Identities come from request.state; mutating endpoints require a human role.
All reads/writes are tenant/user-scoped; foreign/unknown resources -> 404.
Acceptance NEVER auto-dispatches the next agent; no autonomous/background work.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.settings import DB_PATH, DEFAULT_TENANT
from storage.database import Database
from core.coordination_execution import (
    CoordinationExecutionService,
    CoordinationExecutionNotFound,
    PlanNotAuthorized,
    PlanNotOwned,
    NoEligibleStep,
    StepNotAwaitingReview,
    StepAlreadyClaimed,
    ExecutionNotRunnable,
    NotAllStepsAccepted,
    AgentOutputInvalid,
    InvalidStep,
    ReviewNotPermitted,
)
from core.coordination_deliverable import CoordinationDeliverableVersionConflict

router = APIRouter(prefix="/team/goals/plans", tags=["coordination-execution"])
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


def _svc(t: str, u: str):
    return CoordinationExecutionService(_db, t, u)


def _thread_for_execution(t: str, u: str, execution_id: str) -> Optional[str]:
    """Resolve a coordination execution back to its source chat thread (if any)
    so execution progress lands in the same group-chat feed the work came from.
    Owner-scoped read; additive, never used for authorization."""
    rows = _db.query(
        "SELECT tg.thread_id FROM coordination_executions ce "
        "JOIN coordination_plans p ON p.id=ce.plan_id "
        "JOIN team_goals tg ON tg.id=p.team_goal_id "
        "WHERE ce.id=? AND ce.tenant_id=? AND ce.user_id=?",
        (execution_id, t, u))
    return rows[0]["thread_id"] if rows else None


def _record_progress(t: str, u: str, execution_id: str, agent_id: str,
                     status: str, detail: str) -> None:
    """Phase 8 §15: write a durable, owner-scoped progress ledger entry so the
    command center can show what the team did during coordination execution
    (not just chat delegation). Pure side-effect; never changes execution flow."""
    if not agent_id:
        return
    thread_id = _thread_for_execution(t, u, execution_id)
    if not thread_id:
        return
    try:
        from core.progress import ProgressService
        ProgressService(_db, t, u).record(thread_id, agent_id, status, detail)
    except ValueError:
        pass


def _record_run_progress(t: str, u: str, execution_id: str) -> None:
    """Phase 8 §15: after an autonomous run, record a completed ledger entry per
    distinct step-agent from the frozen plan snapshot so execution shows up in
    the source thread's progress feed. Pure side-effect; additive."""
    try:
        steps = _db.query(
            "SELECT ps.seq, ps.agent_id FROM coordination_plan_steps ps "
            "JOIN coordination_executions ce ON ce.plan_id = ps.plan_id "
            "WHERE ce.id=? AND ce.tenant_id=? AND ce.user_id=? ORDER BY ps.seq",
            (execution_id, t, u))
    except Exception:
        return
    for s in steps:
        seq = s.get("seq")
        _record_progress(t, u, execution_id, s.get("agent_id"), "completed",
                         f"step {seq} completed (run) — awaiting your review")


class DecisionBody(BaseModel):
    decision: str
    note: Optional[str] = None
    rework_steps: Optional[List[int]] = None


@router.post("/{plan_id}/execution/initiate")
def initiate_execution(plan_id: str, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        return _svc(t, u).initiate(plan_id, u)
    except ReviewNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to initiate this execution")
    except PlanNotOwned:
        raise HTTPException(status_code=404, detail="plan not found")
    except PlanNotAuthorized as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{plan_id}/execution/{execution_id}/run")
def run_autonomously(plan_id: str, execution_id: str, request: Request):
    """Autonomous run (replaces per-step execution): runs every eligible step in
    dependency order (auto-accept), then aggregates the consolidated deliverable
    for the owner\u2019s final review. Human-launched, owner-scoped, one action."""
    t, u = _identity(request)
    _require_human(request)
    try:
        r = _svc(t, u).run_autonomously(execution_id, u)
        # Phase 8 §15: surface the completed run in the source thread's ledger.
        _record_run_progress(t, u, execution_id)
        return r
    except ReviewNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to run this execution")
    except CoordinationExecutionNotFound:
        raise HTTPException(status_code=404, detail="execution not found")
    except StepAlreadyClaimed as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (ExecutionNotRunnable, NotAllStepsAccepted) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AgentOutputInvalid as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{plan_id}/execution/{execution_id}/step/execute")
def execute_next_step(plan_id: str, execution_id: str, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        r = _svc(t, u).execute_step(execution_id, u)
        # Phase 8 §15: reflect the completed step in the source thread's progress
        # feed so the command center shows execution progress, not only delegation.
        _record_progress(t, u, execution_id, r.get("agent_id"), "completed",
                         f"step {r.get('step')} completed — awaiting your review")
        return r
    except ReviewNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to execute a step")
    except CoordinationExecutionNotFound:
        raise HTTPException(status_code=404, detail="execution not found")
    except StepAlreadyClaimed as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (ExecutionNotRunnable, NoEligibleStep) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AgentOutputInvalid as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{plan_id}/execution/{execution_id}/step/{seq}/review")
def review_step(plan_id: str, execution_id: str, seq: int, body: DecisionBody,
                request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        return _svc(t, u).review_step(execution_id, seq, body.decision, u, body.note)
    except ReviewNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to review this step")
    except CoordinationExecutionNotFound:
        raise HTTPException(status_code=404, detail="execution not found")
    except InvalidStep as e:
        raise HTTPException(status_code=422, detail=str(e))
    except StepNotAwaitingReview as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{plan_id}/execution/{execution_id}/aggregate")
def aggregate_deliverable(plan_id: str, execution_id: str, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        return _svc(t, u).aggregate(execution_id, u)
    except ReviewNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to aggregate")
    except CoordinationExecutionNotFound:
        raise HTTPException(status_code=404, detail="execution not found")
    except NotAllStepsAccepted as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{plan_id}/execution/{execution_id}/deliverable/review")
def review_deliverable(plan_id: str, execution_id: str, body: DecisionBody,
                       request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        return _svc(t, u).review_deliverable(execution_id, body.decision, u, body.note,
                                             rework_steps=body.rework_steps)
    except ReviewNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to review the deliverable")
    except CoordinationExecutionNotFound:
        raise HTTPException(status_code=404, detail="execution not found")
    except NotAllStepsAccepted as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CoordinationDeliverableVersionConflict as e:
        # The version is already permanently decided; the requested decision
        # conflicts with history. The transaction is rolled back and nothing is
        # changed, so return an intentional 409 without weakening idempotency.
        raise HTTPException(status_code=409, detail=str(e))
    except InvalidStep as e:
        raise HTTPException(status_code=422, detail=str(e))


def _deliverable_id_for_execution(t, u, execution_id: str):
    """Owner-scoped lookup of the coordination deliverable id for an execution.
    Returns the id or raises 404 so foreign executions never leak."""
    rows = _db.query(
        "SELECT id FROM coordination_deliverables WHERE execution_id=? AND tenant_id=? AND user_id=?",
        (execution_id, t, u))
    if not rows:
        raise HTTPException(status_code=404, detail="execution not found")
    return rows[0]["id"]


@router.get("/{plan_id}/execution/{execution_id}/deliverable/versions")
def list_deliverable_versions(plan_id: str, execution_id: str, request: Request):
    t, u = _identity(request)
    did = _deliverable_id_for_execution(t, u, execution_id)
    from core.coordination_deliverable import CoordinationDeliverableService
    svc = CoordinationDeliverableService(_db, t, u)
    return {"execution_id": execution_id, "versions": svc.list_versions(did)}


@router.get("/{plan_id}/execution/{execution_id}/deliverable/versions/{version_id}")
def get_deliverable_version(plan_id: str, execution_id: str, version_id: str, request: Request):
    t, u = _identity(request)
    did = _deliverable_id_for_execution(t, u, execution_id)
    from core.coordination_deliverable import CoordinationDeliverableService
    v = CoordinationDeliverableService(_db, t, u).get_version(version_id, did)
    if v is None:
        raise HTTPException(status_code=404, detail="version not found")
    return v


@router.get("/{plan_id}/execution/{execution_id}")
def execution_status(plan_id: str, execution_id: str, request: Request):
    t, u = _identity(request)
    try:
        return _svc(t, u).status(execution_id)
    except CoordinationExecutionNotFound:
        raise HTTPException(status_code=404, detail="execution not found")
