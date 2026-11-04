"""TeamPlan — AI Team 2.0 (T2-B) plan-to-workspace builder.

Pure, testable builder that turns a coordinated plan proposal payload into the
ordered set of workspace-tree records created on human approval.

Design notes
------------
- Pure/functional: ``describe`` returns a normalized, validated description of
  the tree to create WITHOUT touching the DB. ``execute`` takes a live
  transaction cursor and creates the actual rows. This keeps the approval path
  in ``WorkProposalService`` thin and makes the builder unit-testable in
  isolation.
- All inserts happen on the caller's transaction cursor so the WHOLE operation
  is one atomic unit: any exception rolls back every table (workspace, project,
  goals, assignments, deliverables, milestones, dependencies, conversation
  thread, participants, work_links).
- Idempotency and duplicate protection are the caller's job (the existing
  work_proposals 'proposed' guard + reused result_id) — the builder itself never
  runs outside the human-approved transaction.
- Coordinates between the plan's structured snapshot and the runtime work model
  (workspaces/projects/goals/assignments/deliverables + T2-A milestones and
  dependencies). It does NOT introduce any new task table or second approval
  machine.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

# Stable set of the six permanent agent slugs (used for assignment validation).
AGENT_SLUGS = {
    "tutor", "strategist", "executive_assistant",
    "communications", "soundboard", "workspace_architect",
}


class PlanValidationError(ValueError):
    """A malformed / invalid plan payload could not be turned into a workspace."""


class TeamPlanBuilder:
    def __init__(self, tenant_id: str, user_id: str):
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ------------------------------------------------------------------ parsing
    def describe(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize a plan payload into an ordered creation plan.

        Raises PlanValidationError with a meaningful message when the plan cannot
        be safely realized (missing/invalid title, unknown agent slug, non-list
        sections, or a task without a resolvable agent owner).

        Normalized output (all sections always present as lists):
          {title, milestones: [{title, order, deadline}],
           tasks: [{title, agent, milestone_index}],
           deliverables: [{title}],
           success_criteria: [...]}
        """
        title = str(payload.get("title") or "").strip()
        if not title:
            raise PlanValidationError("plan title is required")

        milestones = payload.get("milestones") or []
        if not isinstance(milestones, list):
            raise PlanValidationError("plan milestones must be a list")
        norm_milestones = []
        for i, m in enumerate(milestones):
            if not isinstance(m, dict):
                raise PlanValidationError(f"milestone [{i}] must be an object")
            mt = str(m.get("title") or "").strip()
            if not mt:
                raise PlanValidationError(f"milestone [{i}] title is required")
            norm_milestones.append({
                "title": mt,
                "order": int(m.get("order", 0) or 0),
                "deadline": (str(m.get("deadline")) or None) if m.get("deadline") else None,
            })

        tasks = payload.get("tasks") or []
        if not isinstance(tasks, list):
            raise PlanValidationError("plan tasks must be a list")
        norm_tasks = []
        for i, t in enumerate(tasks):
            if not isinstance(t, dict):
                raise PlanValidationError(f"task [{i}] must be an object")
            tt = str(t.get("title") or "").strip()
            if not tt:
                raise PlanValidationError(f"task [{i}] title is required")
            agent = str(t.get("agent") or t.get("agent_id") or "").strip().lower()
            if agent and agent not in AGENT_SLUGS:
                raise PlanValidationError(f"task [{i}] references unknown agent '{agent}'")
            if not agent:
                raise PlanValidationError(f"task [{i}] has no assigned agent; cannot authorize")
            mi = t.get("milestone_index")
            if mi is not None:
                mi = int(mi)
                if not (0 <= mi < len(norm_milestones)):
                    raise PlanValidationError(
                        f"task [{i}] milestone_index {mi} is out of range")
            norm_tasks.append({"title": tt, "agent": agent, "milestone_index": mi})

        deliverables = payload.get("deliverables") or []
        if not isinstance(deliverables, list):
            raise PlanValidationError("plan deliverables must be a list")
        norm_deliverables = []
        for i, d in enumerate(deliverables):
            if isinstance(d, dict):
                dt = str(d.get("title") or "").strip()
            else:
                dt = str(d or "").strip()
            if not dt:
                raise PlanValidationError(f"deliverable [{i}] title is required")
            norm_deliverables.append({"title": dt})

        sc = payload.get("success_criteria") or []
        if not isinstance(sc, list):
            raise PlanValidationError("plan success_criteria must be a list")
        norm_sc = [str(x) for x in sc if str(x).strip()]

        return {
            "title": title,
            "milestones": norm_milestones,
            "tasks": norm_tasks,
            "deliverables": norm_deliverables,
            "success_criteria": norm_sc,
        }

    # ------------------------------------------------------------------ execution
    def execute(self, c, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create the workspace tree on the transaction cursor ``c``.

        Returns ids: {workspace_id, project_id, thread_id, goal_ids, milestone_ids,
        assignment_ids, deliverable_ids}. All inserts use the caller's cursor so
        the transaction is atomic; on any exception the caller rolls back.
        """
        plan = self.describe(payload)
        now = _now()

        # --- workspace + project ---
        wid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO workspaces (id,tenant_id,user_id,name,created_at) VALUES (?,?,?,?,?)",
            (wid, self.tenant_id, self.user_id, plan["title"], now))
        pid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO projects (id,tenant_id,workspace_id,user_id,name,status,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (pid, self.tenant_id, wid, self.user_id, plan["title"], "active", now))

        # --- milestones ---
        milestone_ids: List[str] = []
        for m in plan["milestones"]:
            mid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO milestones "
                "(id,tenant_id,user_id,project_id,title,ord,status,deadline,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (mid, self.tenant_id, self.user_id, pid, m["title"], m["order"],
                 "planned", m["deadline"], now, now))
            milestone_ids.append(mid)

        # --- goals + assignments (tasks roll up to milestones) ---
        goal_ids: List[str] = []
        assignment_ids: List[str] = []
        for t in plan["tasks"]:
            gid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO goals "
                "(id,tenant_id,project_id,user_id,title,priority,status,progress,updated_at,version,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (gid, self.tenant_id, pid, self.user_id, t["title"], 0,
                 "open", 0, now, 0, now))
            # roll task up to its milestone if present
            if t.get("milestone_index") is not None:
                c.execute(
                    "UPDATE goals SET milestone_id=? WHERE id=? AND tenant_id=?",
                    (milestone_ids[t["milestone_index"]], gid, self.tenant_id))
            c.execute(
                "INSERT INTO goal_events (id,tenant_id,goal_id,status,detail,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), self.tenant_id, gid, "created",
                 f"title={t['title']}", now))
            goal_ids.append(gid)
            # assignment for the task's agent
            aid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO assignments "
                "(id,tenant_id,goal_id,user_id,agent_id,priority,status,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (aid, self.tenant_id, gid, self.user_id, t["agent"], 0, "queued", now))
            if t.get("milestone_index") is not None:
                c.execute(
                    "UPDATE assignments SET milestone_id=? WHERE id=? AND tenant_id=?",
                    (milestone_ids[t["milestone_index"]], aid, self.tenant_id))
            assignment_ids.append(aid)

        # --- deliverables ---
        deliverable_ids: List[str] = []
        for d in plan["deliverables"]:
            did = str(uuid.uuid4())
            c.execute(
                "INSERT INTO deliverables (id,tenant_id,project_id,user_id,title,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (did, self.tenant_id, pid, self.user_id, d["title"], now))
            deliverable_ids.append(did)

        # --- provenance: project conversation (project thread) ---
        thread_id = str(uuid.uuid4())
        c.execute(
            "INSERT INTO conversation_threads "
            "(thread_id,tenant_id,user_id,agent_id,title,is_renamed,created_at,updated_at,thread_type,workspace_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (thread_id, self.tenant_id, self.user_id, None,
             f"{plan['title']} — Project", 0, now, now, "project", wid))
        # add participating agents to the project conversation
        seen_agents: set = set()
        for t in plan["tasks"]:
            ag = t["agent"]
            if ag in seen_agents:
                continue
            seen_agents.add(ag)
            c.execute(
                "INSERT INTO conversation_participants "
                "(id, thread_id, agent_id, tenant_id, user_id, joined_at) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), thread_id, ag, self.tenant_id, self.user_id, now))

        return {
            "workspace_id": wid,
            "project_id": pid,
            "thread_id": thread_id,
            "goal_ids": goal_ids,
            "milestone_ids": milestone_ids,
            "assignment_ids": assignment_ids,
            "deliverable_ids": deliverable_ids,
        }


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
