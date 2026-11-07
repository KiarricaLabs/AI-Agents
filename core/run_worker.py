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


_worker = None


def get_worker(db):
    global _worker
    if _worker is None:
        _worker = RunWorker(db)
        _worker.start()
    return _worker
"""