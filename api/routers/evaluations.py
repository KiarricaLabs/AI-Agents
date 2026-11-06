from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.evaluation import SCENARIOS, evaluate_scenario
from config.settings import DB_PATH, DEFAULT_TENANT
from storage.database import Database

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


class EvaluationRequest(BaseModel):
    scenario: str
    agents: List[str] = []
    plan_status: str
    output: Any = None
    active_brand_id: Optional[str] = None
    output_brand_id: Optional[str] = None
    lessons: List[Dict[str, Any]] = []


@router.get("/scenarios")
def scenarios(request: Request):
    _identity(request)
    return {"scenarios": sorted(SCENARIOS)}


@router.post("/run")
def run_evaluation(body: EvaluationRequest, request: Request):
    _identity(request)
    try:
        return evaluate_scenario(
            body.scenario,
            agents=body.agents,
            plan_status=body.plan_status,
            output=body.output,
            active_brand_id=body.active_brand_id,
            output_brand_id=body.output_brand_id,
            lessons=body.lessons,
        ).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/executions")
def executions(request: Request):
    """List persisted executions owned by the current local identity."""
    tenant, user = _identity(request)
    rows = _db.query(
        "SELECT ce.id AS execution_id, ce.plan_id, ce.team_goal_id, ce.status, "
        "ce.initiated_at, cp.expected_deliverable, "
        "(SELECT COUNT(*) FROM coordination_plan_steps ps "
        " WHERE ps.plan_id=ce.plan_id AND ps.tenant_id=ce.tenant_id AND ps.user_id=ce.user_id) AS step_count "
        "FROM coordination_executions ce "
        "LEFT JOIN coordination_plans cp ON cp.id=ce.plan_id "
        "WHERE ce.tenant_id=? AND ce.user_id=? "
        "ORDER BY ce.updated_at DESC LIMIT 50",
        (tenant, user),
    )
    return {"executions": [dict(row) for row in rows]}


@router.get("/execution/{execution_id}")
def evaluate_execution(execution_id: str, scenario: str, request: Request,
                       active_brand_id: Optional[str] = None):
    """Evaluate an owner-scoped persisted execution without changing it."""
    tenant, user = _identity(request)
    from core.coordination_execution import CoordinationExecutionService, CoordinationExecutionNotFound
    try:
        service = CoordinationExecutionService(_db, tenant, user)
        status = service.status(execution_id)
    except CoordinationExecutionNotFound:
        raise HTTPException(status_code=404, detail="execution not found")
    plan_id = status["plan_id"]
    steps = _db.query(
        "SELECT agent_id FROM coordination_plan_steps "
        "WHERE plan_id=? AND tenant_id=? AND user_id=? ORDER BY seq",
        (plan_id, tenant, user),
    )
    output = status.get("deliverable", {}).get("content", {}) if status.get("deliverable") else {
        "steps": status.get("steps", [])
    }
    return evaluate_scenario(
        scenario,
        agents=[row["agent_id"] for row in steps],
        plan_status=status["status"],
        output=output,
        active_brand_id=active_brand_id,
        output_brand_id=active_brand_id,
    ).as_dict() | {"execution_id": execution_id, "plan_id": plan_id}
