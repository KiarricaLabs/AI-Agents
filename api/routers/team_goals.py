"""T2-C-3 — TeamGoal + coordination-plan API (backend only).

Exposes authenticated, tenant/user-scoped endpoints for reviewing TeamGoals and
their coordination plans and for human-authorized plan approval.

Endpoints
---------
- POST  /team/goals                       human: propose a TeamGoal (intent only)
- GET   /team/goals                       list owner's TeamGoals
- GET   /team/goals/{id}                  retrieve one TeamGoal (steps + approvals)
- GET   /team/goals/{id}/coordination-plan   transient validated plan (review-only)
- POST  /team/goals/{id}/approve          human: approve the TeamGoal
- POST  /team/goals/{id}/steps/{seq}/approve human: approve one agent plan
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

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from core.message_extractor import MessageToTeamGoal
from core.coordination_plan import (
    CoordinationPlanService,
    CoordinationPlanNotFound,
    CoordinationPlanInvalid,
    CoordinationPlanPermissionError,
)
from core.coordination import CoordinationPlanBuilder
from core.runtime import build_runtime

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


class ProposeStep(BaseModel):
    seq: int
    agent_id: str
    responsibility: Optional[str] = None
    depends_on_seq: Optional[int] = None


class DraftGoalBody(BaseModel):
    message: str
    coordinator_agent: str


class ProposeGoalBody(BaseModel):
    """Human-authored TeamGoal request. ``steps`` is an ordered list of
    per-agent contributions validated server-side by TeamGoalService.propose."""
    title: str
    coordinator_agent: str
    goal_id: Optional[str] = None
    thread_id: Optional[str] = None
    summary: Optional[str] = None
    expected_deliverable: Optional[str] = None
    steps: Optional[List[ProposeStep]] = None
    idempotency_key: Optional[str] = None


class ValidateGoalBody(BaseModel):
    coordinator_agent: str
    steps: List[ProposeStep]


@router.post("/{team_goal_id}/agent-plans")
def generate_agent_plans(team_goal_id: str, request: Request):
    """Generate and persist review-only plans for each assigned agent.

    This creates no approval, execution, or external side effect. Each agent
    receives the complete ordered team plan plus its own responsibility.
    """
    t, u = _identity(request)
    _require_human(request)
    goal = _goal_svc(t, u).get(team_goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="team goal not found")
    steps = goal.get("steps") or []
    shared = "\n".join(
        f"Step {s['seq']} — {s['agent_id']} — {s.get('responsibility') or 'not specified'}"
        for s in steps
    )
    assignment_outputs = {
        "strategist": (
            "Return a decision-ready audience and measurement plan. Include: "
            "one primary Bay Area audience, one secondary audience, positioning, "
            "a 6-12 week objective with numeric targets clearly labeled as proposed, "
            "a KPI baseline checklist, and three testable hypotheses. Do not write a "
            "generic content strategy."
        ),
        "communications": (
            "Return a usable Instagram content starter kit. Include: three content "
            "pillars for On Us, four Reel or carousel concepts, a hook and CTA for "
            "each, two complete caption drafts, and a one-week publishing sequence. "
            "Do not claim anything was posted or published."
        ),
        "soundboard": (
            "Return a specific creative and risk review of this campaign. Include: "
            "three alternative campaign angles, the strongest objection for each, "
            "risks around audience trust and cultural representation, five concrete "
            "improvements, and a go/no-go checklist. Do not replace the campaign "
            "with a generic brainstorming list."
        ),
        "workspace_architect": (
            "Return the integrated execution blueprint. Include: ordered deliverables "
            "from the prior agents, dependencies, owner for each deliverable, a "
            "credential-free local artifact to produce at each stage, acceptance "
            "criteria, and a revision loop. Do not claim to launch ads, access "
            "Instagram, or publish anything."
        ),
    }
    orch = build_runtime(_db, t, u)
    def prepare(step):
        task = (
            f"You are contributing to the team goal: {goal['title']}.\n\n"
            f"COMPLETE TEAM PLAN:\n{shared}\n\n"
            f"YOUR ASSIGNMENT (step {step['seq']}): {step.get('responsibility') or 'not specified'}\n\n"
            f"REQUIRED OUTPUT FOR YOUR ROLE:\n{assignment_outputs.get(step['agent_id'], 'Return a concrete plan with named outputs, dependencies, and acceptance criteria.')}\n\n"
            "Produce your actual reviewable agent plan now. Use the campaign objective "
            "and On Us context above; name concrete outputs rather than describing what "
            "a marketing team generally does. "
            "dependencies, assumptions, and handoff to the next agent. Stay within this "
            "assignment. This is local, credential-free planning only: do not claim to "
            "publish, send, book, pay, launch ads, or use unconfigured external tools."
        )
        result = orch.dispatch(step["agent_id"], task, {"team_goal_id": team_goal_id})
        reply = str(result.get("reply") or "").strip()
        if not reply:
            raise ValueError("agent returned no plan")
        return {"seq": step["seq"], "agent_id": step["agent_id"], "plan": reply}

    results = []
    with ThreadPoolExecutor(max_workers=min(len(steps), 6)) as pool:
        futures = {pool.submit(prepare, step): step for step in steps}
        for future in as_completed(futures):
            step = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"{step['agent_id']} could not produce a plan: {e}",
                )
    results.sort(key=lambda item: item["seq"])
    for item in results:
        _goal_svc(t, u).save_step_plan(team_goal_id, item["seq"], item["plan"])
    return {"team_goal_id": team_goal_id, "steps": results}


@router.post("/validate")
def validate_plan_draft(body: ValidateGoalBody, request: Request):
    """Non-persistent capability/delegation validation of a TeamGoal DRAFT.

    Returns per-step capability_ok / delegation_ok / valid / error plus the set
    of valid (delegable + capable) agents and a suggested agent for each invalid
    step, so the UI can guide or auto-reassign BEFORE proposing. Never persists
    or authorizes anything; exact same rules the plan builder uses at authorize.
    """
    t, u = _identity(request)
    _require_human(request)
    try:
        steps = [{"seq": s.seq, "agent_id": s.agent_id,
                  "responsibility": s.responsibility,
                  "depends_on_seq": s.depends_on_seq} for s in body.steps]
        return CoordinationPlanBuilder(_db, t, u).validate_draft(
            body.coordinator_agent, steps)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/draft")
def draft_team_goal_from_message(body: DraftGoalBody, request: Request):
    """Human-only, deterministic draft generator: turns a discussion/idea message
    into an editable TeamGoal DRAFT (title, summary, deliverable, coordinator,
    ordered steps). It NEVER persists or authorizes anything — the result is meant
    to be edited and then proposed via POST /team/goals."""
    t, u = _identity(request)
    _require_human(request)
    try:
        return MessageToTeamGoal.extract(body.message, body.coordinator_agent)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("")
def propose_team_goal(body: ProposeGoalBody, request: Request):
    """Human-only TeamGoal proposal. Creates an INTENT in 'proposed' state only:
    it does NOT approve the goal, does NOT authorize a coordination plan, and does
    NOT initiate execution. Project-goal ownership is checked owner-scoped (404 for
    a foreign/unknown goal); all other field validation errors map to 422. Identity
    comes exclusively from request.state (never client-supplied)."""
    t, u = _identity(request)
    _require_human(request)

    if body.goal_id:
        owned = _db.query(
            "SELECT id FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
            (body.goal_id, t, u))
        if not owned:
            raise HTTPException(status_code=404, detail="goal not found")

    try:
        result = _goal_svc(t, u).propose(
            title=body.title,
            coordinator_agent=body.coordinator_agent,
            goal_id=body.goal_id,
            thread_id=body.thread_id,
            summary=body.summary,
            expected_deliverable=body.expected_deliverable,
            steps=([{"seq": s.seq, "agent_id": s.agent_id,
                     "responsibility": s.responsibility,
                     "depends_on_seq": s.depends_on_seq} for s in body.steps]
                   if body.steps else None),
            idempotency_key=body.idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


@router.get("")
def list_team_goals(request: Request, status: Optional[str] = None):
    """Owner-scoped list of TeamGoals. Adds coordination-pipeline flags so the
    UI can render the from-chat-to-deliverable ladder for the coordination path
    without N+1 round-trips: plan_authorized / has_execution /
    deliverable_accepted / materialized."""
    t, u = _identity(request)
    items = _goal_svc(t, u).list(status) or []
    enriched = []
    for it in items:
        gid = it.get("id")
        plan = _db.query(
            "SELECT 1 FROM coordination_plans WHERE team_goal_id=? AND tenant_id=? "
            "AND user_id=? AND status='authorized' LIMIT 1", (gid, t, u))
        exec_rows = _db.query(
            "SELECT 1 FROM coordination_executions WHERE team_goal_id=? AND tenant_id=? "
            "AND user_id=? LIMIT 1", (gid, t, u))
        deliv = _db.query(
            "SELECT 1 FROM coordination_deliverables cd "
            "JOIN coordination_executions ce ON ce.id=cd.execution_id "
            "WHERE ce.team_goal_id=? AND ce.tenant_id=? AND ce.user_id=? "
            "AND cd.status='accepted' LIMIT 1", (gid, t, u))
        mat = _db.query(
            "SELECT 1 FROM deliverables d "
            "JOIN coordination_executions ce ON ce.id=d.coordination_execution_id "
            "WHERE ce.team_goal_id=? AND ce.tenant_id=? AND ce.user_id=? LIMIT 1",
            (gid, t, u))
        enriched.append({**it,
                         "plan_authorized": bool(plan),
                         "has_execution": bool(exec_rows),
                         "deliverable_accepted": bool(deliv),
                         "materialized": bool(mat)})
    return {"items": enriched}


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


@router.post("/{team_goal_id}/steps/{seq}/approve")
def approve_team_goal_step(team_goal_id: str, seq: int, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        return _goal_svc(t, u).approve_step(team_goal_id, seq, u)
    except TeamGoalNotFound:
        raise HTTPException(status_code=404, detail="team goal step not found")
    except TeamGoalApprovalNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to approve this step")


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
