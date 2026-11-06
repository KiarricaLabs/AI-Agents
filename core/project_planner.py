"""Structured project planning for the approval-gated project workflow."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from pydantic import BaseModel, Field, ValidationError

from config.settings import BASE_DIR
from core.model_router import ModelRouter


class PlannedTask(BaseModel):
    id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    deliverable_type: str = Field(default="draft")
    acceptance_criteria: list[str] = Field(min_length=2, max_length=4)


class ProjectPlan(BaseModel):
    goal: str = Field(min_length=1)
    tasks: list[PlannedTask] = Field(min_length=1, max_length=6)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StructuredProjectPlanner:
    def __init__(self, db, tenant_id: str, user_id: str, router: Optional[ModelRouter] = None):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.router = router or ModelRouter(
            timeout=int(os.getenv("PAT_PLANNER_TIMEOUT_SECONDS", "90")),
            retries=1,
        )
        self.profile_path = Path(BASE_DIR) / "business_profile.md"

    def _profile(self) -> str:
        try:
            return self.profile_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"could not read business profile: {exc}") from exc

    def _record(self, event: str, agent: str = "orchestrator", details=None) -> None:
        self.db.execute(
            "INSERT INTO activity_log "
            "(id,tenant_id,user_id,timestamp,agent,event,details) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, self.user_id, _now(), agent,
             event, json.dumps(details or {})),
        )

    def plan(self, goal: str) -> ProjectPlan:
        goal = str(goal or "").strip()
        if not goal:
            raise ValueError("goal must not be empty")
        schema = ProjectPlan.model_json_schema()
        prompt = (
            "Create an executable, business-specific plan for this goal. "
            "Generic role descriptions are invalid. Every instruction must name "
            "the concrete artifact, audience, channel or decision it will produce "
            "for this exact goal.\n\n"
            f"GOAL:\n{goal}\n\n"
            f"BUSINESS PROFILE:\n{self._profile()}\n\n"
            "Use only registered agents and split the work into small, concrete "
            "tasks (no more than 6). Use these exact agent ids only: "
            "strategist, communications, soundboard, workspace_architect, "
            "executive_assistant, tutor. Each task must produce a draft or "
            "local research artifact. "
            "For a campaign, require specific deliverables such as audience "
            "segments, positioning, measurable objectives, content concepts, "
            "hooks, captions, calls to action, risks, and acceptance criteria "
            "as appropriate. Include the actual business name, geography, "
            "audience, offer, and channel from the goal/profile in the task "
            "instructions. Do not write instructions like 'develop a strategy', "
            "'create content', or 'review the plan' without specifying what "
            "must be delivered and how it will be judged. "
            "Each task must include a short deliverable_type and exactly 2 "
            "observable acceptance criteria specific to the goal. "
            "Do not include sending email, posting, DMs, payments, bookings, or "
            "other outward actions. Return only the requested JSON schema."
        )
        last_error = ""
        for attempt in range(1, 4):
            retry_prompt = prompt
            if last_error:
                retry_prompt += (
                    "\n\nThe previous response failed validation. Correct this exact "
                    f"validation error and return the full JSON again:\n{last_error}"
                )
            self._record("plan_attempt", details={"attempt": attempt, "goal": goal})
            result = self.router.complete(
                agent_id="orchestrator",
                prompt=retry_prompt,
                system="You are the orchestrator. Produce only valid structured JSON.",
                model_spec={"provider": "ollama",
                            "model": os.getenv("PAT_ORCHESTRATOR_MODEL",
                                               os.getenv("PAT_AI_MODEL", "llama3.1"))},
                json_schema=schema,
            )
            try:
                plan = ProjectPlan.model_validate(json.loads(result.text))
                self._validate_task_graph(plan)
                self._record("plan_validated", details={"tasks": len(plan.tasks)})
                return plan
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = str(exc)
                self._record("plan_validation_failed", details={"attempt": attempt, "error": last_error})
        raise ValueError(f"structured plan failed validation after 3 attempts: {last_error}")

    @staticmethod
    def _validate_task_graph(plan: ProjectPlan) -> None:
        ids = [task.id for task in plan.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("task ids must be unique")
        known = set(ids)
        for task in plan.tasks:
            instruction = task.instruction.lower()
            allowed_agents = {
                "strategist",
                "communications",
                "soundboard",
                "workspace_architect",
                "executive_assistant",
                "tutor",
            }
            generic = (
                "develop a strategy",
                "create content",
                "review the plan",
                "provide recommendations",
                "analyze the goal",
            )
            if len(task.instruction.strip()) < 30 or (
                instruction in generic
                or any(instruction == phrase for phrase in generic)
            ):
                raise ValueError(
                    f"task {task.id} instruction is too generic; require a "
                    "specific artifact, audience/channel, and acceptance criteria"
                )
            if task.agent not in allowed_agents:
                raise ValueError(
                    f"task {task.id} uses unregistered agent {task.agent!r}"
                )
            outward_terms = (
                "send ",
                "publish ",
                "post ",
                "dm ",
                "book ",
                "pay ",
                "purchase ",
                "create a new instagram account",
            )
            if any(term in instruction for term in outward_terms):
                raise ValueError(
                    f"task {task.id} requests an outward action; create a local draft instead"
                )
            if task.id in task.depends_on:
                raise ValueError(f"task {task.id} cannot depend on itself")
            unknown = set(task.depends_on) - known
            if unknown:
                raise ValueError(f"task {task.id} has unknown dependencies: {sorted(unknown)}")
