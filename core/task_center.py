"""Task Center — user-facing task aggregation (Phase 4).

A "task" is an assignment (goal -> agent) enriched with its project, goal,
assigned agent, deliverable readiness, conversation origin, and a human-facing
status. It does NOT introduce a competing task system — it is a read-only view
over the existing assignment/execution/deliverable architecture.

Exposed statuses (user-facing), mapped from backend state:

  awaiting_assignment   - an assignment proposal exists but the assignment has
                          not yet been approved/created (plan not authorized)
  awaiting_execution    - assignment approved; no active execution yet
  in_progress           - an execution episode is running
  needs_input           - execution is waiting on your decision
  ready_for_review      - execution done AND a valid deliverable exists
  revision_requested    - deliverable version flagged requested changes
  completed             - episode applied to goal / goal done
  rejected              - task assignment rejected (or deliverable rejected)

A task is "ready for review" only when BOTH a completed episode exists AND its
project has a deliverable with an approved/valid version. This enforces the
requirement that episode-done does NOT automatically mean ready-for-review.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from core.work_proposals import WorkProposalService


class TaskCenter:
    def __init__(self, db, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ------------------------------------------------------------------ reads
    def _owned(self, table: str, rid: str) -> bool:
        rows = self.db.query(
            f"SELECT id FROM {table} WHERE id=? AND tenant_id=? AND user_id=?",
            (rid, self.tenant_id, self.user_id))
        return bool(rows)

    def _tasks_for_goals(self, goal_ids: List[str]) -> List[Dict[str, Any]]:
        if not goal_ids:
            return []
        qmarks = ",".join("?" for _ in goal_ids)
        return self.db.query(
            f"SELECT a.*, COALESCE(a.title, g.title) AS task_title "
            f"FROM assignments a JOIN goals g ON g.id=a.goal_id "
            f"WHERE a.tenant_id=? AND a.user_id=? AND a.goal_id IN ({qmarks}) "
            f"ORDER BY a.priority DESC, a.created_at DESC",
            (self.tenant_id, self.user_id, *goal_ids))

    def _goal_rows(self, goal_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not goal_ids:
            return {}
        qmarks = ",".join("?" for _ in goal_ids)
        rows = self.db.query(
            f"SELECT g.id AS goal_id, g.title, g.status, g.progress, g.priority, "
            f"p.id AS project_id, p.name AS project_name, p.status AS project_status, "
            f"w.id AS workspace_id, w.name AS workspace_name "
            f"FROM goals g "
            f"JOIN projects p ON p.id=g.project_id "
            f"JOIN workspaces w ON w.id=p.workspace_id "
            f"WHERE g.tenant_id=? AND g.user_id=? AND g.id IN ({qmarks})",
            (self.tenant_id, self.user_id, *goal_ids))
        return {r["goal_id"]: dict(r) for r in rows}

    def _approved_assignment_ids(self) -> set:
        """Assignments that were created via an approved proposal (authorized)."""
        rows = self.db.query(
            "SELECT result_id FROM work_proposals WHERE tenant_id=? AND user_id=? "
            "AND work_type='assignment' AND status='approved' AND result_id IS NOT NULL",
            (self.tenant_id, self.user_id))
        return {r["result_id"] for r in rows}

    def _pending_assignment_proposals(self) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT id, goal_id, agent_id, thread_id, payload_json, reason, context, "
            "requested_changes, created_at FROM work_proposals "
            "WHERE tenant_id=? AND user_id=? AND work_type='assignment' "
            "AND status='proposed' ORDER BY created_at DESC",
            (self.tenant_id, self.user_id))

    def _episode_for_assignment(self, assignment_id: str):
        rows = self.db.query(
            "SELECT e.* FROM episodes e WHERE e.tenant_id=? AND e.user_id=? "
            "AND e.work_type='assignment' AND e.work_id=? "
            "ORDER BY e.created_at DESC LIMIT 1",
            (self.tenant_id, self.user_id, assignment_id))
        return rows[0] if rows else None

    def _deliverables_for_project(self, project_id: str):
        rows = self.db.query(
            "SELECT d.id, d.title, v.version, v.status, v.requested_changes, v.review_note "
            "FROM deliverables d "
            "LEFT JOIN deliverable_versions v ON v.deliverable_id=d.id "
            "AND v.id=(SELECT v2.id FROM deliverable_versions v2 "
            "          WHERE v2.tenant_id=d.tenant_id AND v2.deliverable_id=d.id "
            "          ORDER BY v2.version DESC LIMIT 1) "
            "WHERE d.tenant_id=? AND d.user_id=? AND d.project_id=?",
            (self.tenant_id, self.user_id, project_id))
        return rows or []

    def _work_links_for_work(self, work_type: str, work_id: str) -> List[str]:
        rows = self.db.query(
            "SELECT thread_id FROM work_links WHERE tenant_id=? AND user_id=? "
            "AND work_type=? AND work_id=?",
            (self.tenant_id, self.user_id, work_type, work_id))
        return [r["thread_id"] for r in rows if r.get("thread_id")]

    # ------------------------------------------------------------------ view
    def _assemble(self, include_pending: bool = True, statuses: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []

        # 1. Pending assignment proposals -> "awaiting_assignment" tasks.
        if include_pending:
            for p in self._pending_assignment_proposals():
                payload = {}
                try:
                    payload = json.loads(p.get("payload_json") or "{}")
                except Exception:
                    payload = {}
                gid = p.get("goal_id") or payload.get("goal_id")
                tasks.append({
                    "task_id": "prop:" + p["id"],
                    "kind": "proposal",
                    "status": "revision_requested" if p.get("requested_changes") else "awaiting_assignment",
                    "title": (payload.get("title") or "").strip() or "Proposed task",
                    "description": (payload.get("description") or payload.get("task") or "").strip(),
                    "agent_id": p.get("agent_id"),
                    "goal_id": gid,
                    "project_id": None,
                    "proposal_id": p["id"],
                    "assignment_id": None,
                    "deliverable": None,
                    "thread_ids": [p["thread_id"]] if p.get("thread_id") else [],
                    "next_action": "Review and approve (or reject) this proposed assignment.",
                    "episode": None,
                    "needs_approval": True,
                })

        # gather task-goal ids
        goal_ids_all: set = set()
        for p in self._pending_assignment_proposals():
            try:
                payload = json.loads(p.get("payload_json") or "{}")
            except Exception:
                payload = {}
            gid = p.get("goal_id") or payload.get("goal_id")
            if gid:
                goal_ids_all.add(gid)

        assignments = self.db.query(
            "SELECT a.* FROM assignments a WHERE a.tenant_id=? AND a.user_id=? "
            "ORDER BY a.priority DESC, a.created_at DESC",
            (self.tenant_id, self.user_id))
        for a in assignments:
            goal_ids_all.add(a["goal_id"])
        goal_map = self._goal_rows(list(goal_ids_all))
        approved_ids = self._approved_assignment_ids()

        for a in assignments:
            gid = a["goal_id"]
            g = goal_map.get(gid, {})
            pid = g.get("project_id")
            episode = self._episode_for_assignment(a["id"])
            deliverables = self._deliverables_for_project(pid) if pid else []
            valid_deliverable = any(
                d.get("status") == "approved" for d in deliverables)
            latest_deliv = deliverables[0] if deliverables else None

            episode_done = episode and episode.get("status") == "done"
            applied = bool(episode and episode.get("applied_at"))
            running = episode and episode.get("status") == "running"
            approved = a["id"] in approved_ids

            if latest_deliv and latest_deliv.get("requested_changes"):
                status = "revision_requested"
                next_action = "Revisions were requested on the deliverable; a new version is expected."
            elif running:
                status = "in_progress"
                next_action = "Task is running. Monitor progress or provide evidence."
            elif applied:
                status = "completed"
                next_action = "Applied to goal. Mark as complete or move on."
            elif episode_done and valid_deliverable:
                status = "ready_for_review"
                next_action = "Review the deliverable: approve, request changes, or reject."
            elif episode_done and not valid_deliverable:
                status = "completed"
                next_action = "Execution complete with no attached deliverable. Review evidence or apply to goal."
            elif approved:
                status = "awaiting_execution"
                next_action = "Approved. Start execution when ready."
            else:
                status = "awaiting_assignment"
                next_action = "Awaiting assignment authorization."

            threads = self._work_links_for_work("assignment", a["id"])
            tasks.append({
                "task_id": a["id"],
                "kind": "assignment",
                "status": status,
                "title": a.get("title") or a.get("task_title") or "Task",
                "description": a.get("description") or a.get("task_title") or "",
                "agent_id": a.get("agent_id"),
                "goal_id": gid,
                "goal_title": g.get("title"),
                "goal_status": g.get("status"),
                "goal_progress": g.get("progress"),
                "project_id": pid,
                "project_name": g.get("project_name"),
                "workspace_id": g.get("workspace_id"),
                "workspace_name": g.get("workspace_name"),
                "assignment_id": a["id"],
                "proposal_id": None,
                "deliverable": latest_deliv,
                "deliverables": deliverables,
                "thread_ids": threads,
                "next_action": next_action,
                "episode": {
                    "id": episode["id"],
                    "status": episode["status"],
                    "progress": episode.get("progress"),
                    "applied_at": episode.get("applied_at"),
                } if episode else None,
                "needs_approval": not approved,
            })

        if statuses:
            tasks = [t for t in tasks if t["status"] in statuses]
        return tasks

    def list(self, statuses: Optional[List[str]] = None) -> Dict[str, Any]:
        tasks = self._assemble(include_pending=True, statuses=statuses)
        return {"items": tasks, "count": len(tasks)}
