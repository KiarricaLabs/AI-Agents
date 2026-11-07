"""Plain-code dependency runner for structured agent projects."""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from config.settings import BASE_DIR
from core.output_contracts import extract_structured, guidance_for
from core.runtime import build_runtime, load_registry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parallel_workers() -> int:
    """Bounded parallelism for a run wave. Independent tasks run together so the
    slow local-model calls overlap; the number is capped to keep memory/load sane."""
    try:
        return max(1, min(6, int(os.getenv("PAT_RUNNER_PARALLEL", "3"))))
    except ValueError:
        return 3


class ProjectRunner:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.profile = (Path(BASE_DIR) / "business_profile.md").read_text(
            encoding="utf-8").strip()
        self.registry = load_registry()

    def _project(self, project_id: str):
        rows = self.db.query(
            "SELECT * FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?",
            (project_id, self.tenant_id, self.user_id))
        if not rows:
            raise ValueError("project not found")
        return rows[0]

    def _tasks(self, project_id: str):
        return self.db.query(
            "SELECT * FROM agent_tasks WHERE project_id=? AND tenant_id=? AND user_id=? "
            "ORDER BY rowid",
            (project_id, self.tenant_id, self.user_id))

    def _log(self, agent: str, event: str, details: Dict[str, Any]):
        self.db.execute(
            "INSERT INTO activity_log "
            "(id,tenant_id,user_id,timestamp,agent,event,details) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, self.user_id, _now(), agent,
             event, json.dumps(details)))

    def run(self, project_id: str) -> Dict[str, Any]:
        project = self._project(project_id)
        if project["status"] != "running":
            raise ValueError("project must be approved before it can run")
        if os.getenv("PAT_AGENT_KILL_SWITCH", "").lower() in {"1", "true", "yes", "on"}:
            raise ValueError("agent runner is halted by the global kill switch")

        tasks = [dict(row) for row in self._tasks(project_id)]
        runtime = build_runtime(self.db, self.tenant_id, self.user_id)
        completed: Dict[str, Any] = {
            task["id"]: task["output"] for task in tasks
            if task["status"] == "done" and task["output"]
        }
        # Each wave runs every currently-runnable task concurrently (independent
        # tasks overlap their slow local-model calls); the next wave only opens
        # once all of the previous wave's tasks are done, preserving dependencies.
        while True:
            if os.getenv("PAT_AGENT_KILL_SWITCH", "").lower() in {"1", "true", "yes", "on"}:
                raise ValueError("agent runner halted by the global kill switch")
            runnable = [
                task for task in tasks
                if task["status"] == "pending"
                and all(dep in completed for dep in json.loads(task["depends_on"] or "[]"))
            ]
            if not runnable:
                break
            workers = min(_parallel_workers(), len(runnable))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(self._run_task, runtime, project, task, completed): task
                           for task in runnable}
                for fut in as_completed(futures):
                    task = futures[fut]
                    try:
                        task_id, output = fut.result()
                    except Exception as exc:
                        self._fail(project_id, task["id"], str(exc))
                        raise
                    completed[task_id] = output
                    task["status"] = "done"

        remaining = [task for task in tasks if task["status"] == "pending"]
        if remaining:
            self.db.execute(
                "UPDATE agent_projects SET status='failed', updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
                (_now(), project_id, self.tenant_id, self.user_id))
            raise ValueError("project has unresolved task dependencies")
        self.db.execute(
            "UPDATE agent_projects SET status='awaiting_review', updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (_now(), project_id, self.tenant_id, self.user_id))
        return {"project_id": project_id, "status": "awaiting_review", "outputs": completed}

    def _run_task(self, runtime, project, task, completed) -> tuple:
        """Execute one task to completion. Returns (task_id, output). Called from
        a worker thread; DB writes are serialized by the shared Database lock."""
        agent = task["agent"]
        if agent not in self.registry.list():
            raise ValueError(f"unknown agent: {agent}")
        dependencies = json.loads(task["depends_on"] or "[]")
        prompt = (
            f"Execute one focused task for this project: {project['goal']}\n\n"
            f"YOUR TASK:\n{task['instruction']}\n\n"
            f"DELIVERABLE TYPE:\n{task['deliverable_type']}\n\n"
            f"ACCEPTANCE CRITERIA:\n{task['acceptance_criteria']}\n\n"
            f"BUSINESS PROFILE:\n{self.profile}\n\n"
            f"COMPLETED DEPENDENCY OUTPUTS:\n{json.dumps({d: completed[d] for d in dependencies}, ensure_ascii=False)}\n\n"
            "Produce the full readable draft, research, or artifact for this task\u2014it is "
            "what the human will review. Keep quality high. "
            "Do not send email, post, DM, pay, book, or perform any outward action.\n\n"
            + guidance_for(task["deliverable_type"])
        )
        project_id = project["id"]
        now = _now()
        self.db.execute(
            "UPDATE agent_tasks SET status='running', updated_at=? "
            "WHERE id=? AND project_id=? AND tenant_id=? AND user_id=? AND status='pending'",
            (now, task["id"], project_id, self.tenant_id, self.user_id))
        self._log(agent, "task_started", {"project_id": project_id, "task_id": task["id"]})
        try:
            result = runtime.dispatch(agent, prompt, {
                "project_id": project_id,
                "task_id": task["id"],
                "accepted_dependency_outputs": dependencies,
            })
            raw = str(result.get("reply") or "").strip()
            if not raw:
                raise ValueError("agent returned empty output")
            # Best-effort structured payload: never blocks the run if the agent
            # omits/strips the JSON block \u2014 the readable prose is always kept.
            structured, prose = extract_structured(raw, task["deliverable_type"])
            self.db.execute(
                "UPDATE agent_tasks SET status='done', review_status='pending', "
                "output=?, output_json=?, updated_at=? "
                "WHERE id=? AND project_id=? AND tenant_id=? AND user_id=?",
                (prose, json.dumps(structured) if structured else None, _now(),
                 task["id"], project_id, self.tenant_id, self.user_id))
            self._log(agent, "task_completed", {"project_id": project_id, "task_id": task["id"],
                                                  "structured": bool(structured)})
            return task["id"], prose
        except Exception:
            raise

    def _fail(self, project_id: str, task_id: str, error: str):
        self.db.execute(
            "UPDATE agent_tasks SET status='failed', output=?, updated_at=? "
            "WHERE id=? AND project_id=? AND tenant_id=? AND user_id=?",
            (f"Task failed: {error[:500]}", _now(), task_id, project_id,
             self.tenant_id, self.user_id))
        self.db.execute(
            "UPDATE agent_projects SET status='failed', updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (_now(), project_id, self.tenant_id, self.user_id))
        self._log("runner", "task_failed", {"project_id": project_id, "task_id": task_id, "error": error[:500]})
