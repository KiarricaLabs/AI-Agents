"""Structured project planning endpoint (Phase 2; approval comes later)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional

from config.settings import DB_PATH, DEFAULT_TENANT
from storage.database import Database
from core.project_planner import StructuredProjectPlanner
from core.project_runner import ProjectRunner

router = APIRouter(prefix="/projects", tags=["structured-projects"])
_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


class CreateProjectRequest(BaseModel):
    goal: str
    idempotency_key: str | None = None
    brand_id: str | None = None


class RunProjectRequest(BaseModel):
    run_key: str | None = None


class PlanTaskRequest(BaseModel):
    id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    deliverable_type: str = Field(default="draft", min_length=1)
    acceptance_criteria: list[str] = Field(default_factory=list)


class EditPlanRequest(BaseModel):
    goal: str = Field(min_length=1)
    tasks: list[PlanTaskRequest] = Field(min_length=1)


class RejectPlanRequest(BaseModel):
    feedback: str = Field(min_length=1)


class ReworkTaskRequest(BaseModel):
    notes: str = Field(min_length=1)


class ReviewTaskRequest(BaseModel):
    action: str = Field(pattern="^(approve|edit|send_back)$")
    output: str | None = None
    notes: str | None = None


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


_HUMAN_ROLES = {"user", "admin"}


def _require_human(request: Request):
    """Human-only gate for mutations. Identity and role come from request.state,
    never from the body. Agents may propose drafts but cannot approve, run,
    review, or edit the plan themselves."""
    role = getattr(request.state, "role", "user")
    if role not in _HUMAN_ROLES:
        raise HTTPException(status_code=403, detail="human approval required")




@router.post("")
def create_project(req: CreateProjectRequest, request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    key = req.idempotency_key

    # Idempotency: if a project already exists for this key, return it.
    if key is not None:
        existing = _find_project_by_key(tenant, user, key)
        if existing is not None:
            return _serialize_project(existing)

    try:
        plan = StructuredProjectPlanner(_db, tenant, user).plan(req.goal)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    remap = {task.id: f"{project_id}::task-{i + 1}" for i, task in enumerate(plan.tasks)}
    try:
        with _db.transaction() as conn:
            conn.execute(
                "INSERT INTO agent_projects "
                "(id,tenant_id,user_id,goal,status,plan_json,created_at,updated_at,idempotency_key,brand_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (project_id, tenant, user, plan.goal, "awaiting_plan_approval",
                 plan.model_dump_json(), now, now, key, req.brand_id),
            )
            for i, task in enumerate(plan.tasks):
                conn.execute(
                    "INSERT INTO agent_tasks "
                    "(id,project_id,tenant_id,user_id,agent,instruction,depends_on,status,deliverable_type,acceptance_criteria,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (remap[task.id], project_id, tenant, user, task.agent, task.instruction,
                     json.dumps([remap[d] for d in task.depends_on]), "pending", task.deliverable_type,
                     json.dumps(task.acceptance_criteria), now, now),
                )
    except Exception as exc:
        # Concurrent duplicate key: unique index fired. Re-query winner.
        if key is not None and "UNIQUE" in str(exc).upper():
            existing = _find_project_by_key(tenant, user, key)
            if existing is not None:
                return _serialize_project(existing)
        raise
    stored = []
    for task in plan.tasks:
        dumped = task.model_dump()
        dumped["id"] = remap[task.id]
        dumped["depends_on"] = [remap[d] for d in task.depends_on]
        stored.append(dumped)
    return {"id": project_id, "status": "awaiting_plan_approval",
            "goal": plan.goal, "tasks": stored}


def _find_project_by_key(tenant, user, key):
    rows = _db.query(
        "SELECT * FROM agent_projects WHERE tenant_id=? AND user_id=? AND idempotency_key=?",
        (key, ) if False else (tenant, user, key))
    if not rows:
        return None
    return rows[0]


def _serialize_project(proj):
    pid = proj["id"]
    tasks = _db.query(
        "SELECT * FROM agent_tasks WHERE project_id=? AND tenant_id=? AND user_id=? ORDER BY rowid",
        (pid, proj["tenant_id"], proj["user_id"]))
    stored = []
    for t in tasks:
        stored.append({
            "id": t["id"],
            "agent": t["agent"],
            "instruction": t["instruction"],
            "depends_on": json.loads(t["depends_on"] or "[]"),
            "deliverable_type": t["deliverable_type"],
            "acceptance_criteria": json.loads(t["acceptance_criteria"] or "[]"),
        })
    return {"id": pid, "status": proj["status"],
            "goal": proj["goal"], "tasks": stored}


def _project(tenant: str, user: str, project_id: str):
    rows = _db.query(
        "SELECT * FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?",
        (project_id, tenant, user))
    if not rows:
        raise HTTPException(status_code=404, detail="project not found")
    project = dict(rows[0])
    tasks = _db.query(
        "SELECT id, agent, instruction, depends_on, status, review_status, deliverable_type, "
        "acceptance_criteria, output, output_json, created_at, updated_at "
        "FROM agent_tasks WHERE project_id=? AND tenant_id=? AND user_id=? ORDER BY rowid",
        (project_id, tenant, user))
    for task in tasks:
        task["depends_on"] = json.loads(task["depends_on"] or "[]")
        task["acceptance_criteria"] = json.loads(task["acceptance_criteria"] or "[]")
    project["plan"] = json.loads(project.pop("plan_json"))
    project["tasks"] = tasks
    return project


def _project_summary(tenant: str, user: str, project_id: str):
    project = _project(tenant, user, project_id)
    tasks = project["tasks"]
    actions = _db.query(
        "SELECT status, type FROM pending_actions "
        "WHERE project_id=? AND tenant_id=? AND user_id=?",
        (project_id, tenant, user))
    completed = [task for task in tasks if task["status"] == "done"]
    approved = [task for task in tasks if task["review_status"] == "approved"]
    failed = [task for task in tasks if task["status"] == "failed"]
    pending_actions = [action for action in actions if action["status"] == "pending"]
    return {
        "project_id": project_id,
        "goal": project["goal"],
        "status": project["status"],
        "summary": (
            f"{len(approved)} of {len(tasks)} task drafts approved. "
            f"{len(pending_actions)} outward actions await approval."
        ),
        "completed_tasks": [
            {"id": task["id"], "agent": task["agent"], "output": task["output"]}
            for task in completed
        ],
        "approved_tasks": [task["id"] for task in approved],
        "pending_decisions": [
            {"id": task["id"], "agent": task["agent"], "type": "draft_review"}
            for task in tasks if task["status"] == "done" and task["review_status"] != "approved"
        ] + [
            {"type": action["type"], "kind": "outward_action"}
            for action in pending_actions
        ],
        "blocked_or_failed": [
            {"id": task["id"], "agent": task["agent"], "status": task["status"]}
            for task in failed
        ],
    }


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    tenant, user = _identity(request)
    return _project(tenant, user, project_id)


@router.get("/{project_id}/summary")
def get_project_summary(project_id: str, request: Request):
    tenant, user = _identity(request)
    return _project_summary(tenant, user, project_id)


@router.get("")
def list_projects(request: Request):
    tenant, user = _identity(request)
    rows = _db.query(
        "SELECT id, goal, status, created_at, updated_at FROM agent_projects "
        "WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC",
        (tenant, user))
    return {"items": [dict(row) for row in rows]}


@router.post("/{project_id}/plan/approve")
def approve_plan(project_id: str, request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    project = _project(tenant, user, project_id)
    if project["status"] != "awaiting_plan_approval":
        raise HTTPException(status_code=409, detail="plan is not awaiting approval")
    now = datetime.now(timezone.utc).isoformat()
    _db.execute(
        "UPDATE agent_projects SET status='running', updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
        (now, project_id, tenant, user))
    return _project(tenant, user, project_id)


@router.post("/{project_id}/plan/reject")
def reject_plan(project_id: str, body: RejectPlanRequest, request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    project = _project(tenant, user, project_id)
    if project["status"] != "awaiting_plan_approval":
        raise HTTPException(status_code=409, detail="plan is not awaiting approval")
    now = datetime.now(timezone.utc).isoformat()
    _db.execute(
        "UPDATE agent_projects SET status='failed', updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
        (now, project_id, tenant, user))
    _db.execute(
        "INSERT INTO activity_log (id,tenant_id,user_id,timestamp,agent,event,details) "
        "VALUES (?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), tenant, user, now, "human", "plan_rejected",
         json.dumps({"feedback": body.feedback})))
    return {**_project(tenant, user, project_id), "feedback": body.feedback}


@router.post("/{project_id}/plan/edit")
def edit_plan(project_id: str, body: EditPlanRequest, request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    project = _project(tenant, user, project_id)
    if project["status"] != "awaiting_plan_approval":
        raise HTTPException(status_code=409, detail="only pending plans can be edited")
    ids = {task.id for task in body.tasks}
    if len(ids) != len(body.tasks):
        raise HTTPException(status_code=422, detail="task ids must be unique")
    if any(dep not in ids or dep == task.id for task in body.tasks for dep in task.depends_on):
        raise HTTPException(status_code=422, detail="task dependencies must reference other tasks")
    now = datetime.now(timezone.utc).isoformat()
    with _db.transaction() as conn:
        conn.execute(
            "UPDATE agent_projects SET goal=?, plan_json=?, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (body.goal, json.dumps({"goal": body.goal, "tasks": [task.model_dump() for task in body.tasks]}),
             now, project_id, tenant, user))
        conn.execute(
            "DELETE FROM agent_tasks WHERE project_id=? AND tenant_id=? AND user_id=?",
            (project_id, tenant, user))
        for task in body.tasks:
            conn.execute(
                "INSERT INTO agent_tasks "
                "(id,project_id,tenant_id,user_id,agent,instruction,depends_on,status,deliverable_type,acceptance_criteria,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (task.id, project_id, tenant, user, task.agent, task.instruction,
                 json.dumps(task.depends_on), "pending", task.deliverable_type,
                 json.dumps(task.acceptance_criteria), now, now))
    return _project(tenant, user, project_id)


@router.post("/{project_id}/run", status_code=202)
def run_project(project_id: str, request: Request, body: Optional[RunProjectRequest] = None):
    _require_human(request)
    tenant, user = _identity(request)
    run_key = body.run_key if body else None
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _db.transaction() as conn:
        conn.execute(
            "INSERT INTO agent_runs (id,project_id,tenant_id,user_id,run_key,status,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (job_id, project_id, tenant, user, run_key, "queued", now),
        )
    from core.run_worker import get_worker
    get_worker(_db)
    return {"job_id": job_id, "status": "queued"}


@router.get("/runs/{job_id}")
def get_run(job_id: str, request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    rows = _db.query(
        "SELECT * FROM agent_runs WHERE id=? AND tenant_id=? AND user_id=?",
        (job_id, tenant, user))
    if not rows:
        raise HTTPException(status_code=404, detail="run not found")
    r = rows[0]
    result = json.loads(r["result_json"]) if r.get("result_json") else None
    return {"job_id": r["id"], "project_id": r["project_id"],
            "status": r["status"], "created_at": r["created_at"],
            "started_at": r.get("started_at"), "finished_at": r.get("finished_at"),
            "result": result, "error": r.get("error")}


# B2 — Scheduled triggers
@router.post("/{project_id}/schedule")
def set_schedule(project_id: str, request: Request, body: dict = None):
    _require_human(request)
    tenant, user = _identity(request)
    interval = (body or {}).get("interval_seconds")
    if interval is not None:
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="invalid interval")
        if interval <= 0:
            raise HTTPException(status_code=400, detail="interval must be positive")
    # verify project exists
    rows = _db.query(
        "SELECT * FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?",
        (project_id, tenant, user))
    if not rows:
        raise HTTPException(status_code=404, detail="project not found")
    _db.execute(
        "UPDATE agent_projects SET schedule_interval_seconds=?, updated_at=? "
        "WHERE id=? AND tenant_id=? AND user_id=?",
        (interval, datetime.now(timezone.utc).isoformat(), project_id, tenant, user))
    # Register scheduler if not already present (duplicate prevention).
    try:
        import api.app as _appmod
        if project_id not in _appmod._SCHEDULERS:
            from core.scheduler import Scheduler
            from core.run_worker import get_worker
            get_worker(_db)
            def enqueue():
                from core.run_worker import enqueue_scheduled_run
                enqueue_scheduled_run(_db, project_id, tenant, user, interval)
            sched = Scheduler(enqueue, interval_seconds=interval)
            sched.start()
            _appmod._SCHEDULERS[project_id] = sched
        elif interval is not None:
            # update interval by recreating
            old = _appmod._SCHEDULERS.pop(project_id, None)
            if old:
                old.stop()
            from core.scheduler import Scheduler
            from core.run_worker import get_worker
            get_worker(_db)
            def enqueue2():
                from core.run_worker import enqueue_scheduled_run
                enqueue_scheduled_run(_db, project_id, tenant, user, interval)
            sched = Scheduler(enqueue2, interval_seconds=interval)
            sched.start()
            _appmod._SCHEDULERS[project_id] = sched
    except Exception:
        pass
    return {"project_id": project_id, "schedule_interval_seconds": interval}


@router.get("/{project_id}/schedule")
def get_schedule(project_id: str, request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    rows = _db.query(
        "SELECT schedule_interval_seconds FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?",
        (project_id, tenant, user))
    if not rows:
        raise HTTPException(status_code=404, detail="project not found")
    return {"project_id": project_id,
            "schedule_interval_seconds": rows[0]["schedule_interval_seconds"]}


# B3 — Unified approval center
@router.get("/approvals")
def list_approvals(request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    projects = _db.query(
        "SELECT * FROM agent_projects WHERE tenant_id=? AND user_id=? AND status IN ('awaiting_plan_approval','awaiting_review','failed')",
        (tenant, user))
    items = []
    for p in projects:
        items.append({"project_id": p["id"], "goal": p["goal"],
                      "status": p["status"], "updated_at": p["updated_at"]})
    return {"approvals": items}


@router.post("/tasks/{task_id}/review")
def review_task(task_id: str, body: ReviewTaskRequest, request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    rows = _db.query(
        "SELECT * FROM agent_tasks WHERE id=? AND tenant_id=? AND user_id=?",
        (task_id, tenant, user))
    if not rows:
        raise HTTPException(status_code=404, detail="task not found")
    task = rows[0]
    if task["status"] != "done" or not task["output"]:
        raise HTTPException(status_code=409, detail="only completed drafts can be reviewed")
    now = datetime.now(timezone.utc).isoformat()
    if body.action == "edit":
        if not body.output or not body.output.strip():
            raise HTTPException(status_code=422, detail="edited output is required")
        _db.execute(
            "UPDATE agent_tasks SET output=?, review_status='pending', updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (body.output.strip(), now, task_id, tenant, user))
    elif body.action == "send_back":
        notes = (body.notes or "").strip()
        if not notes:
            raise HTTPException(status_code=422, detail="send-back notes are required")
        _db.execute(
            "UPDATE agent_tasks SET instruction=?, status='pending', review_status='pending', "
            "output=NULL, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
            (f"{task['instruction']}\n\nHUMAN REWORK NOTES:\n{notes}", now,
             task_id, tenant, user))
        _db.execute(
            "UPDATE agent_projects SET status='running', updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (now, task["project_id"], tenant, user))
    else:
        _db.execute(
            "UPDATE agent_tasks SET review_status='approved', updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (now, task_id, tenant, user))
        pending = _db.query(
            "SELECT COUNT(*) AS count FROM agent_tasks "
            "WHERE project_id=? AND tenant_id=? AND user_id=? "
            "AND (status != 'done' OR review_status != 'approved')",
            (task["project_id"], tenant, user))[0]["count"]
        if pending == 0:
            _db.execute(
                "UPDATE agent_projects SET status='done', updated_at=? "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (now, task["project_id"], tenant, user))
    _db.execute(
        "INSERT INTO activity_log (id,tenant_id,user_id,timestamp,agent,event,details) "
        "VALUES (?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), tenant, user, now, "human", f"task_{body.action}",
         json.dumps({"task_id": task_id, "project_id": task["project_id"],
                     "notes": body.notes or ""})))
    return _project(tenant, user, task["project_id"])


@router.post("/tasks/{task_id}/rework")
def rework_task(task_id: str, body: ReworkTaskRequest, request: Request):
    _require_human(request)
    tenant, user = _identity(request)
    rows = _db.query(
        "SELECT * FROM agent_tasks WHERE id=? AND tenant_id=? AND user_id=?",
        (task_id, tenant, user))
    if not rows:
        raise HTTPException(status_code=404, detail="task not found")
    task = rows[0]
    project = _db.query(
        "SELECT status FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?",
        (task["project_id"], tenant, user))
    if not project or project[0]["status"] not in {"awaiting_review", "failed"}:
        raise HTTPException(status_code=409, detail="task is not available for rework")
    now = datetime.now(timezone.utc).isoformat()
    instruction = f"{task['instruction']}\n\nHUMAN REWORK NOTES:\n{body.notes}"
    _db.execute(
        "UPDATE agent_tasks SET instruction=?, status='pending', output=NULL, updated_at=? "
        "WHERE id=? AND tenant_id=? AND user_id=?",
        (instruction, now, task_id, tenant, user))
    _db.execute(
        "UPDATE agent_projects SET status='running', updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
        (now, task["project_id"], tenant, user))
    return {"task_id": task_id, "project_id": task["project_id"], "status": "pending"}
