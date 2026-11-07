"""Plain-code dependency runner for structured agent projects."""
from __future__ import annotations

import json
import os
import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from agents.base import _EMPTY_OUTPUT_REPLY, _GENERATION_FAILED_REPLY
from config.settings import BASE_DIR
from core.output_contracts import extract_structured, guidance_for
from core.runtime import build_runtime, load_registry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_generation_failure(raw: str) -> bool:
    """True when the agent's reply is a system fallback for a model failure
    rather than a real draft. The structured runner must never record these as
    completed work; they are transient (parallel calls hitting one local model)
    and should be retried."""
    text = (raw or "").strip()
    return (
        text == _GENERATION_FAILED_REPLY.strip()
        or text == _EMPTY_OUTPUT_REPLY.strip()
        or text.startswith("I couldn't reach the language model just now")
        or text.startswith("The model returned no usable response just now")
    )


def _task_retries() -> int:
    try:
        return max(0, int(os.getenv("PAT_TASK_RETRIES", "3")))
    except ValueError:
        return 3


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
        base_profile = (Path(BASE_DIR) / "business_profile.md").read_text(
            encoding="utf-8").strip()
        # C1: append learned preference lessons from feedback.
        try:
            from core.feedback import FeedbackService
            fs = FeedbackService(self.db, self.tenant_id, self.user_id)
            lessons = fs.preference_lessons()
            if lessons:
                base_profile = base_profile + "\n\nLEARNED PREFERENCES:\n" + "\n".join(f"- {l}" for l in lessons)
        except Exception:
            pass
        self.profile = base_profile
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

    def _claim_run(self, project_id: str, run_key: str = None) -> Dict[str, Any]:
        """Atomically claim ownership of a run for this project.

        Returns a dict with 'outcome' in:
          - 'claimed'            : this caller now owns the run; proceed.
          - 'already_completed'  : project already awaiting_review; returns cached result.
          - 'already_failed'     : project failed; returns last_error.
          - 'conflict'           : another run is in progress (stale heartbeat check).
          - 'not_approved'       : project not in approved/running state.
        Recovery: if a prior run was interrupted (status='running' with stale
        heartbeat), reconcile running->pending tasks of the old attempt, bump
        run_attempt, and claim. Done tasks/outputs are never touched.
        """
        stale_seconds = int(os.getenv("PAT_RUN_STALE_SECONDS", "300"))
        now = _now()
        with self.db.transaction_immediate() as c:
            c.row_factory = __import__("sqlite3").Row
            rows = c.execute(
                "SELECT * FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?",
                (project_id, self.tenant_id, self.user_id)).fetchall()
            if not rows:
                return {"outcome": "not_approved"}
            proj = dict(rows[0])
            status = proj.get("status")
            # Terminal states -> idempotent replay
            if status == "awaiting_review":
                tasks = c.execute(
                    "SELECT id, output FROM agent_tasks WHERE project_id=? AND tenant_id=? AND user_id=?",
                    (project_id, self.tenant_id, self.user_id)).fetchall()
                completed = {t["id"]: t["output"] for t in tasks if t["output"]}
                return {"outcome": "already_completed",
                        "result": {"project_id": project_id, "status": "awaiting_review",
                                   "outputs": completed}}
            if status == "failed":
                return {"outcome": "already_failed", "error": proj.get("last_error")}
            if status not in ("approved", "running"):
                return {"outcome": "not_approved"}

            # If already running, check heartbeat staleness / run_key match
            if status == "running":
                # Same run_key -> idempotent replay of in-progress run (conflict-ish but ok)
                if run_key and proj.get("run_key") == run_key:
                    # Treat as already claimed by this caller; just proceed.
                    pass
                else:
                    hb = proj.get("run_heartbeat_at")
                    stale = True
                    if hb:
                        try:
                            from datetime import datetime, timezone
                            hb_dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
                            age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
                            stale = age > stale_seconds
                        except Exception:
                            stale = True
                    if not stale:
                        return {"outcome": "conflict"}
                    # Stale -> recover: reset running tasks of old attempt to pending
                    old_attempt = proj.get("run_attempt") or 0
                    c.execute(
                        "UPDATE agent_tasks SET status='pending', updated_at=? "
                        "WHERE project_id=? AND tenant_id=? AND user_id=? "
                        "AND status='running' AND task_attempt <= ?",
                        (_now(), project_id, self.tenant_id, self.user_id, old_attempt))

            # Claim: bump attempt, set running, set run_key, heartbeat
            new_attempt = (proj.get("run_attempt") or 0) + 1
            c.execute(
                "UPDATE agent_projects SET status='running', run_attempt=?, run_key=?, "
                "run_heartbeat_at=?, updated_at=?, last_error=NULL "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (new_attempt, run_key, now, now, project_id, self.tenant_id, self.user_id))
            # Stamp task_attempt on pending tasks that are about to run
            c.execute(
                "UPDATE agent_tasks SET task_attempt=? "
                "WHERE project_id=? AND tenant_id=? AND user_id=? AND status='pending'",
                (new_attempt, project_id, self.tenant_id, self.user_id))
        return {"outcome": "claimed"}

    def _log(self, agent: str, event: str, details: Dict[str, Any]):
        self.db.execute(
            "INSERT INTO activity_log "
            "(id,tenant_id,user_id,timestamp,agent,event,details) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, self.user_id, _now(), agent,
             event, json.dumps(details)))

    def run(self, project_id: str, run_key: str = None) -> Dict[str, Any]:
        # --- Atomic ownership claim + recovery (short transaction, no model calls) ---
        claim = self._claim_run(project_id, run_key)
        if claim["outcome"] == "already_completed":
            # Idempotent replay of a finished run: return cached result, no re-run.
            return claim["result"]
        if claim["outcome"] == "already_failed":
            raise ValueError(claim.get("error") or "run already failed")
        if claim["outcome"] == "conflict":
            raise ValueError("run already in progress for this project")
        if claim["outcome"] == "not_approved":
            raise ValueError("project must be approved before it can run")

        if os.getenv("PAT_AGENT_KILL_SWITCH", "").lower() in {"1", "true", "yes", "on"}:
            raise ValueError("agent runner is halted by the global kill switch")

        project = self._project(project_id)
        run_attempt = project.get("run_attempt") or 0
        run_key = project.get("run_key")
        # Start a short-lived heartbeat daemon thread that refreshes the lease
        # during long Ollama generations (not only between tasks).
        stop_event = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(project_id, run_attempt, run_key, stop_event),
            daemon=True, name=f"hb-{project_id}")
        heartbeat_thread.start()
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
                        stop_event.set()
                        heartbeat_thread.join(timeout=5)
                        self._fail(project_id, task["id"], str(exc))
                        raise
                    completed[task_id] = output
                    task["status"] = "done"
                    # Heartbeat: keep the lease fresh during a long run.
                    self.db.execute(
                        "UPDATE agent_projects SET run_heartbeat_at=?, updated_at=? "
                        "WHERE id=? AND tenant_id=? AND user_id=?",
                        (_now(), _now(), project_id, self.tenant_id, self.user_id))

        remaining = [task for task in tasks if task["status"] == "pending"]
        if remaining:
            self.db.execute(
                "UPDATE agent_projects SET status='failed', last_error=?, updated_at=? "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                ("unresolved task dependencies", _now(), project_id, self.tenant_id, self.user_id))
            raise ValueError("project has unresolved task dependencies")
        stop_event.set()
        heartbeat_thread.join(timeout=5)
        self.db.execute(
            "UPDATE agent_projects SET status='awaiting_review', run_heartbeat_at=NULL, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (_now(), project_id, self.tenant_id, self.user_id))
        stop_event.set()
        heartbeat_thread.join(timeout=5)
        return {"project_id": project_id, "status": "awaiting_review", "outputs": completed}

    def _heartbeat_loop(self, project_id, run_attempt, run_key, stop_event):
        """Daemon thread: refresh run_heartbeat_at while a run is active.
        Every update is guarded by project_id + run_attempt + run_key + status='running'
        so a stale thread from an older attempt cannot refresh a newer lease."""
        interval = float(os.getenv("PAT_HEARTBEAT_INTERVAL_SECONDS", "5"))
        while not stop_event.wait(interval):
            try:
                self.db.execute(
                    "UPDATE agent_projects SET run_heartbeat_at=?, updated_at=? "
                    "WHERE id=? AND tenant_id=? AND user_id=? "
                    "AND status='running' AND run_attempt=? "
                    "AND (run_key IS ? OR run_key=?)",
                    (_now(), _now(), project_id, self.tenant_id, self.user_id,
                     run_attempt, run_key, run_key))
            except Exception:
                pass

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
        raw = ""
        last_err = ""
        retries = _task_retries()
        for attempt in range(retries + 1):
            result = runtime.dispatch(agent, prompt, {
                "project_id": project_id,
                "task_id": task["id"],
                "accepted_dependency_outputs": dependencies,
            })
            raw = str(result.get("reply") or "").strip()
            if not raw:
                last_err = "agent returned empty output"
            elif _is_generation_failure(raw):
                last_err = raw[:120]
            else:
                break  # real draft, use it
            if attempt < retries:
                time.sleep(1.5)
        if not raw or _is_generation_failure(raw):
            raise ValueError(last_err or "agent returned empty output")
        try:
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
            "UPDATE agent_projects SET status='failed', last_error=?, updated_at=? "
            "WHERE id=? AND tenant_id=? AND user_id=?",
            (error[:500], _now(), project_id, self.tenant_id, self.user_id))
        self._log("runner", "task_failed", {"project_id": project_id, "task_id": task_id, "error": error[:500]})
