"""T2-C-7 Phase 2 — deterministic seed for coordination E2E.

Creates an eligible (approved) TeamGoal in the dedicated E2E database
(``PAT_DB_PATH`` -> pat.test.db) using the real services, so the Playwright
spec can exercise the coordination UI without a live model.

This is TEST scaffolding only: it runs against the isolated E2E DB and never
touches production data. It does NOT authorize a plan, initiate any execution,
or dispatch any agent — the spec drives those through the real UI/API so the
frozen-plan authorization and human initiation remain exerciseable.

The TeamGoal mirrors the unit-test fixture (T2-C-1/2): coordinator
``workspace_architect`` delegating to ``strategist`` (the only declared
delegation), which yields a valid, reviewable coordination plan.

Idempotent: if an "E2E Launch Goal" already exists for this owner it is skipped,
so a rerun against a reused DB does not duplicate records.
"""
from __future__ import annotations

from config.settings import DB_PATH, DEFAULT_TENANT, LOCAL_USER
from core.team_goal import TeamGoalService
from core.workspace import WorkspaceService, ProjectService, GoalService
from storage.database import Database

TITLE = "E2E Launch Goal"


def main() -> None:
    tenant = DEFAULT_TENANT
    user = LOCAL_USER
    db = Database(path=DB_PATH, tenant_id=tenant)
    svc = TeamGoalService(db, tenant, user)
    if any(g.get("title") == TITLE for g in svc.list()):
        # Already seeded for this owner; reuse the existing goal.
        for g in svc.list():
            if g.get("title") == TITLE:
                print(g["id"])
                return
    ws = WorkspaceService(db, tenant, user).create("E2E WS")
    pid = ProjectService(db, tenant, user).create(ws, "E2E Project")
    gid = GoalService(db, tenant, user).create(pid, "E2E Goal", 0)
    tg = svc.propose(
        TITLE,
        "workspace_architect",
        goal_id=gid,
        steps=[{"seq": 1, "agent_id": "strategist",
                "responsibility": "Strategy for the launch"}],
    )["team_goal_id"]
    svc.approve(tg, user)
    print(tg)


if __name__ == "__main__":
    main()
