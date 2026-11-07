"""In-process async run worker (Phase B1). Polls agent_runs queue and executes."""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT
from core.project_runner import ProjectRunner


def _now():
    return datetime.now(timezone.utc).isoformat()


class RunWorker:
    def __init__(self, db):
        self.db = db
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="run-worker")

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                job = self._claim_next()
                if job is None:
                    time.sleep(1)
                    continue
                self._execute(job)
            except Exception:
                time.sleep(1)

    def _claim_next(self):
        with self.db.transaction_immediate() as c:
            rows = c.execute(
                "SELECT * FROM agent_runs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchall()
            if not rows:
                return None
            job = dict(rows[0])
            c.execute(
                "UPDATE agent_runs SET status='running', started_at=? WHERE id=?",
                (_now(), job["id"]))
        return job

    def _execute(self, job):
        try:
            runner = ProjectRunner(self.db, job["tenant_id"], job["user_id"])
            result = runner.run(job["project_id"], run_key=job.get("run_key"))
            self.db.execute(
                "UPDATE agent_runs SET status='completed', finished_at=?, result_json=? WHERE id=?",
                (_now(), json.dumps(result), job["id"]))
        except Exception as exc:
            self.db.execute(
                "UPDATE agent_runs SET status='failed', finished_at=?, error=? WHERE id=?",
                (_now(), str(exc)[:500], job["id"]))


def enqueue_scheduled_run(db, project_id, tenant, user, interval):
    """Idempotently enqueue a scheduled run for one occurrence."""
    import uuid
    from datetime import datetime, timezone
    # occurrence key: project + interval bucket
    bucket = int(time.time() // max(1, interval)) if False else None
    # use wall-clock minute bucket for determinism within an occurrence
    now = datetime.now(timezone.utc)
    # bucket to interval boundary
    epoch = int(now.timestamp())
    occ = epoch - (epoch % max(1, int(interval)))
    run_key = f"{project_id}:{occ}"
    # check existing
    rows = db.query("SELECT id FROM agent_runs WHERE project_id=? AND run_key=?", (project_id, run_key))
    if rows:
        return rows[0]["id"]
    # approval gate
    pr = db.query("SELECT status FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?", (project_id, tenant, user))
    if not pr or pr[0]["status"] not in ("approved", "running"):
        return None
    job_id = str(uuid.uuid4())
    nows = datetime.now(timezone.utc).isoformat()
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO agent_runs (id,project_id,tenant_id,user_id,run_key,status,created_at) VALUES (?,?,?,?,?,?,?)",
                         (job_id, project_id, tenant, user, run_key, "queued", nows))
    except Exception as exc:
        # Unique constraint violation -> return existing run id.
        if "UNIQUE" in str(exc).upper() or "CONSTRAINT" in str(exc).upper():
            rows = db.query("SELECT id FROM agent_runs WHERE project_id=? AND run_key=?", (project_id, run_key))
            if rows:
                return rows[0]["id"]
        raise
    return job_id


_worker = None


def get_worker(db):
    global _worker
    if _worker is None:
        _worker = RunWorker(db)
        _worker.start()
    return _worker