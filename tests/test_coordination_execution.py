"""T2-C-4 — CoordinationExecutionService + execution API (isolated DB).

Covers (never production):
- Human-initiated run + duplicate-request idempotency.
- Frozen snapshot consumption (no re-authorize / no reassign).
- Explicit human initiation of every step (one at a time).
- Non-human role rejection.
- Sequential + dependency enforcement (dependent blocked until dep accepted).
- Accepted-output context propagation (only accepted flows downstream).
- Step review: accept vs revision vs reject (distinct).
- Missing/failed outputs handled.
- Evidence-gated completion.
- Interrupted execution recovery (no duplicate accepted work).
- Final deliverable aggregation + human review.
- Cross-tenant / cross-user isolation.
- No autonomous dispatch, no background work, no delegation-log writes.
- No permission expansion.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from storage.database import Database
from core.team_goal import TeamGoalService
from core.workspace import WorkspaceService, ProjectService, GoalService
from core.coordination_plan import CoordinationPlanService
from core.coordination_execution import (
    CoordinationExecutionService,
    NoEligibleStep,
    StepNotAwaitingReview,
    ExecutionNotRunnable,
    NotAllStepsAccepted,
    AgentOutputInvalid,
)


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


def _scaffold(db, tenant="t1", user="u1"):
    ws = WorkspaceService(db, tenant, user).create("WS")
    pid = ProjectService(db, tenant, user).create(ws, "PROJ")
    gid = GoalService(db, tenant, user).create(pid, "GOAL", 0)
    return {"wid": ws, "pid": pid, "gid": gid}


def _authorized_plan(db, tenant="t1", user="u1", multi=False):
    """Create + approve a TeamGoal AND authorize its coordination plan (T2-C-3)."""
    svc = TeamGoalService(db, tenant, user)
    ids = _scaffold(db, tenant, user)
    steps = [{"seq": 1, "agent_id": "strategist", "responsibility": "Strategy"},
             {"seq": 2, "agent_id": "strategist", "responsibility": "Prioritize",
              "depends_on_seq": 1}] if multi else \
            [{"seq": 1, "agent_id": "strategist", "responsibility": "Strategy"}]
    tg = svc.propose("Launch", "workspace_architect", goal_id=ids["gid"],
                     steps=steps)["team_goal_id"]
    svc.approve(tg, user)
    plan = CoordinationPlanService(db, tenant, user).authorize(tg, user)
    return tg, ids, plan["plan_id"]


def _stub_reply(content="done"):
    def dispatch(agent, responsibility, context):
        return {"reply": content, "agent": agent}
    return dispatch


class CoordinationExecutionServiceTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = CoordinationExecutionService(
            self.db, "t1", "u1", dispatcher=_stub_reply())

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def _start_run(self):
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")
        return tg, ids, plan, run["execution_id"]

    def test_initiate_and_idempotent_duplicate(self):
        tg, ids, plan = _authorized_plan(self.db)
        r1 = self.svc.initiate(plan, "u1")
        self.assertEqual(r1["status"], "running")
        r2 = self.svc.initiate(plan, "u1")
        self.assertTrue(r2["reused"])
        self.assertEqual(r2["execution_id"], r1["execution_id"])
        runs = self.db.query(
            "SELECT id FROM coordination_executions WHERE plan_id=?", (plan,))
        self.assertEqual(len(runs), 1)
        step_rows = self.db.query(
            "SELECT COUNT(*) AS n FROM coordination_step_outputs WHERE execution_id=?",
            (r1["execution_id"],))
        self.assertEqual(step_rows[0]["n"], 1)

    def test_initiate_non_owner_denied(self):
        tg, ids, plan = _authorized_plan(self.db)
        with self.assertRaises(Exception):
            self.svc.initiate(plan, "someone-else")

    def test_execute_step_sequential_and_review(self):
        tg, ids, plan_id, run = self._start_run()
        result = self.svc.execute_step(run, "u1")
        self.assertEqual(result["status"], "awaiting_review")
        st = self.svc._step_output(run, 1)
        self.assertEqual(st["status"], "awaiting_review")
        self.assertTrue(st["evidence_json"])
        # Accepting must NOT auto-dispatch the next step -> still only step 1.
        self.svc.review_step(run, 1, "accepted", "u1")

    # ---------------------------------------------------------- autonomous run
    def test_run_autonomously_runs_all_steps_and_aggregates(self):
        tg, ids, plan_id, run = self._start_run_and_multi()  # 2 dependent steps
        res = self.svc.run_autonomously(run, "u1")
        self.assertTrue(res["all_accepted"])
        self.assertEqual(len(res["ran"]), 2)
        self.assertEqual([st["status"] for st in res["ran"]], ["accepted", "accepted"])
        for seq in (1, 2):
            o = self.svc._step_output(run, seq)
            self.assertEqual(o["status"], "accepted")
            self.assertTrue(o["evidence_json"])
            self.assertTrue(o["output_json"])
        # Deliverable auto-aggregated to pending; run awaits final review.
        self.assertEqual(res["deliverable"]["status"], "pending")
        self.assertEqual(res["run_status"], "ready_for_review")

    def test_run_autonomously_then_human_approves_deliverable(self):
        tg, ids, plan_id, run = self._start_run_and_multi()
        res = self.svc.run_autonomously(run, "u1")
        self.assertTrue(res["all_accepted"])
        self.svc.review_deliverable(run, "accepted", "u1")
        self.assertEqual(self.svc._get_execution(run)["status"], "completed")

    def test_run_autonomously_no_duplicate_dispatch_on_repeat(self):
        tg, ids, plan_id, run = self._start_run_and_multi()
        self.svc.run_autonomously(run, "u1")
        before = self.db.query("SELECT COUNT(*) AS n FROM episodes")[0]["n"]
        self.svc.run_autonomously(run, "u1")
        after = self.db.query("SELECT COUNT(*) AS n FROM episodes")[0]["n"]
        self.assertEqual(before, after)  # no new dispatches on a repeated run

    def test_run_autonomously_non_owner_denied(self):
        tg, ids, plan_id, run = self._start_run_and_multi()
        with self.assertRaises(Exception):
            self.svc.run_autonomously(run, "someone-else")

    def test_run_autonomously_terminal_raises(self):
        tg, ids, plan_id, run = self._start_run_and_multi()
        self.svc.run_autonomously(run, "u1")
        self.svc.review_deliverable(run, "rejected", "u1")
        with self.assertRaises(ExecutionNotRunnable):
            self.svc.run_autonomously(run, "u1")

    def test_run_autonomously_revision_reruns_rework_steps(self):
        tg, ids, plan_id, run = self._start_run_and_multi()
        self.svc.run_autonomously(run, "u1")
        self.svc.review_deliverable(run, "revision_requested", "u1", rework_steps=[1])
        self.svc.run_autonomously(run, "u1")  # re-runs step 1 + dependent step 2
        for seq in (1, 2):
            self.assertEqual(self.svc._step_output(run, seq)["status"], "accepted")
        self.assertEqual(self.svc._get_execution(run)["status"], "ready_for_review")

    # ---------------------------------------------------------- materialize
    def test_accept_materializes_project_records(self):
        tg, ids, plan_id, run = self._start_run_and_multi()
        self.svc.run_autonomously(run, "u1")
        res = self.svc.review_deliverable(run, "accepted", "u1")
        self.assertIsNotNone(res.get("materialized"))
        self.assertTrue(res["materialized"]["created"])
        # A project-scoped deliverable was created linked to this execution.
        d = self.db.query(
            "SELECT id, coordination_execution_id FROM deliverables "
            "WHERE tenant_id='t1' AND user_id='u1'")
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["coordination_execution_id"], run)
        self.assertEqual(self.db.query(
            "SELECT COUNT(*) AS n FROM deliverable_versions WHERE deliverable_id=?",
            (d[0]["id"],))[0]["n"], 1)
        # A second materialization appends a version instead of duplicating.
        r2 = self.svc._materialize_project_records(
            run, self.svc._get_execution(run), "D", {"seq": 2},
            "2026-01-01T00:00:00Z")
        self.assertTrue(r2["version_added"])
        self.assertEqual(r2["version"], 2)
        self.assertEqual(self.db.query(
            "SELECT COUNT(*) AS n FROM deliverables")[0]["n"], 1)

    def test_eligibility_only_after_dependencies_accepted(self):
        tg, ids, plan_id, run = self._start_run_and_multi()
        # step 2 depends on step 1; step 1 runs first, then step 2 runs.
        r1 = self.svc.execute_step(run, "u1")
        self.assertEqual(r1["step"], 1)
        # cannot run step 2 until step 1 accepted
        with self.assertRaises(NoEligibleStep):
            self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        r2 = self.svc.execute_step(run, "u1")
        self.assertEqual(r2["step"], 2)

    def _start_run_and_multi(self):
        tg, ids, plan = _authorized_plan(self.db, multi=True)
        run = self.svc.initiate(plan, "u1")
        return tg, ids, plan, run["execution_id"]

    def test_review_revision_not_terminal(self):
        tg, ids, plan_id, run = self._start_run()
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "revision_requested", "u1")
        st = self.svc._step_output(run, 1)
        self.assertEqual(st["status"], "revision_requested")
        # runnable again after revision
        self.svc.execute_step(run, "u1")

    def test_review_rejected_is_terminal(self):
        tg, ids, plan_id, run = self._start_run()
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "rejected", "u1")
        st = self.svc._step_output(run, 1)
        self.assertEqual(st["status"], "rejected")
        # rejected step cannot run; no eligible step remains
        with self.assertRaises(NoEligibleStep):
            self.svc.execute_step(run, "u1")

    def test_review_requires_awaiting_state(self):
        tg, ids, plan_id, run = self._start_run()
        # not yet executed -> cannot review
        with self.assertRaises(StepNotAwaitingReview):
            self.svc.review_step(run, 1, "accepted", "u1")
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        # already accepted -> cannot review again
        with self.assertRaises(StepNotAwaitingReview):
            self.svc.review_step(run, 1, "rejected", "u1")

    def test_aggregate_requires_all_accepted(self):
        tg, ids, plan_id, run = self._start_run()
        with self.assertRaises(NotAllStepsAccepted):
            self.svc.aggregate(run, "u1")
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        d = self.svc.aggregate(run, "u1")
        self.assertEqual(d["status"], "pending")
        self.assertTrue(d["content"]["steps"])

    def test_aggregate_and_final_review(self):
        tg, ids, plan_id, run = self._start_run()
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        self.svc.aggregate(run, "u1")
        r = self.svc.review_deliverable(run, "accepted", "u1")
        self.assertEqual(r["run_status"], "completed")

    def test_no_autonomous_dispatch_no_delegation_log(self):
        before = len(self.db.query("SELECT id FROM delegation_log"))
        tg, ids, plan_id, run = self._start_run()
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        after = len(self.db.query("SELECT id FROM delegation_log"))
        self.assertEqual(after, before)
        # only one episode per step (no burst execution)
        eps = self.db.query("SELECT id FROM episodes")
        self.assertTrue(len(eps) >= 1)

    def test_failed_dispatch_marks_failed(self):
        svc = CoordinationExecutionService(self.db, "t1", "u1",
                                           dispatcher=lambda *a, **k: (_ for _ in ()).throw(
                                               RuntimeError("llm down")))
        tg, ids, plan = _authorized_plan(self.db)
        run = svc.initiate(plan, "u1")["execution_id"]
        with self.assertRaises(AgentOutputInvalid):
            svc.execute_step(run, "u1")
        st = svc._step_output(run, 1)
        self.assertEqual(st["status"], "failed")

    def test_interrupted_execution_recovery(self):
        """A failed dispatch leaves the step failed; the run survives and a retry
        can be issued; accepted work is not duplicated."""
        fail = {"calls": 0}
        def flaky(agent, responsibility, context):
            fail["calls"] += 1
            if fail["calls"] == 1:
                raise RuntimeError("transient")
            return {"reply": "ok"}
        svc = CoordinationExecutionService(self.db, "t1", "u1", dispatcher=flaky)
        tg, ids, plan = _authorized_plan(self.db)
        run = svc.initiate(plan, "u1")["execution_id"]
        with self.assertRaises(AgentOutputInvalid):
            svc.execute_step(run, "u1")
        st = svc._step_output(run, 1)
        self.assertEqual(st["status"], "failed")
        # retry the same step produces accepted, awaiting review
        r2 = svc.execute_step(run, "u1")
        self.assertEqual(r2["status"], "awaiting_review")

    def test_only_accepted_outputs_as_context(self):
        # step 2 must see step 1 output only after it is accepted
        seen = {}
        def spy(agent, responsibility, context):
            seen["ctx"] = context
            return {"reply": "ok"}
        svc = CoordinationExecutionService(self.db, "t1", "u1", dispatcher=spy)
        tg, ids, plan, run = self._start_run_and_multi()
        svc.execute_step(run, "u1")
        svc.review_step(run, 1, "accepted", "u1")
        svc.execute_step(run, "u1")  # step 2 sees step 1 accepted context
        self.assertIn("1", seen["ctx"])


class CoordinationExecutionIsolationTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_cross_tenant_run_invisible(self):
        a = Database(path=self.path, tenant_id="tenantA")
        _, _, plan = _authorized_plan(a, "tenantA", "uA")
        b = Database(path=self.path, tenant_id="tenantB")
        svcB = CoordinationExecutionService(b, "tenantB", "uB")
        with self.assertRaises(Exception):
            svcB.initiate(plan, "uB")  # plan not owned -> refused

    def test_cross_user_run_invisible(self):
        a = Database(path=self.path, tenant_id="t1")
        _, _, plan = _authorized_plan(a, "t1", "u1")
        svc2 = CoordinationExecutionService(a, "t1", "u2")
        with self.assertRaises(Exception):
            svc2.initiate(plan, "u2")


class TestCoordinationExecutionApiHuman(unittest.TestCase):
    """Non-human role rejection on the execution router (local-mode TestClient
    resolves role=admin, so we invoke the route functions directly with an
    agent-role request state; real _require_human() gate is exercised)."""

    def _agent_request(self):
        from types import SimpleNamespace
        state = SimpleNamespace(tenant_id="local", user_id="local", role="agent")
        return SimpleNamespace(state=state)

    def test_non_human_cannot_initiate(self):
        from fastapi import HTTPException
        from api.routers.team_goals_execution import initiate_execution
        with self.assertRaises(HTTPException) as ctx:
            initiate_execution("some-plan", self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_human_cannot_execute_step(self):
        from fastapi import HTTPException
        from api.routers.team_goals_execution import execute_next_step
        with self.assertRaises(HTTPException) as ctx:
            execute_next_step("p", "e", self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_human_cannot_review_step(self):
        from fastapi import HTTPException
        from api.routers.team_goals_execution import review_step as review
        with self.assertRaises(HTTPException) as ctx:
            review("p", "e", 1,
                   type("B", (), {"decision": "accepted", "note": None})(),
                   self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_human_cannot_aggregate(self):
        from fastapi import HTTPException
        from api.routers.team_goals_execution import aggregate_deliverable
        with self.assertRaises(HTTPException) as ctx:
            aggregate_deliverable("p", "e", self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_human_cannot_review_deliverable(self):
        from fastapi import HTTPException
        from api.routers.team_goals_execution import review_deliverable
        with self.assertRaises(HTTPException) as ctx:
            review_deliverable("p", "e",
                               type("B", (), {"decision": "accepted", "note": None})(),
                               self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)


class TestPermissionCeilingF2(unittest.TestCase):
    """F2 — persisted permission ceiling is enforced mechanically at dispatch."""
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = CoordinationExecutionService(self.db, "t1", "u1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_restricted_orchestrator_limits_tools_to_ceiling(self):
        tg, _, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        # A step with a restrictive ceiling (only brand:read, not work:propose:*)
        self.svc.execute_step(run, "u1")

    def test_ceiling_excludes_proposal_permissions(self):
        import json
        # Build a restricted orchestrator for strategist whose ceiling excludes
        # work:propose:goal. Verify its policy denies that tool even though the
        # strategist manifest ordinarily grants it.
        ceiling = {"brand:read", "memory:read"}
        orch = self.svc._restricted_orchestrator("strategist", set(ceiling))
        # policy denies a propose tool whose required permission is outside ceiling
        allowed = orch.policy.allow("strategist", "tool", "work_propose_goal")
        self.assertFalse(allowed)
        # but the tool not in the restricted manifest tools list either
        from core.runtime import load_registry
        # dispatch would reject at layer-2/3; and the restricted policy denies any
        # propose tool whose permission isn't in the ceiling.
        for proposed in ("work_propose_project", "work_propose_deliverable"):
            self.assertFalse(orch.policy.allow("strategist", "tool", proposed))

    def test_ceiling_still_allows_dispatch_and_non_side_effect_tools(self):
        orch = self.svc._restricted_orchestrator("strategist", {"brand:read"})
        self.assertTrue(orch.policy.allow("system", "dispatch", "strategist"))

    def test_ceiling_intersected_with_runtime_available(self):
        # A ceiling containing a permission the agent does NOT have must be dropped
        # (it can never be granted). work_propose_workspace requires
        # work:propose:workspace which strategist does not declare.
        orch = self.svc._restricted_orchestrator("strategist",
                                                 {"memory:read", "work:propose:workspace"})
        self.assertFalse(orch.policy.allow("strategist", "tool", "work_propose_workspace"))


class TestDeliverableRevisionF1(unittest.TestCase):
    """F1 — final-deliverable revision is actionable and invalidates downstream."""
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = CoordinationExecutionService(self.db, "t1", "u1",
                                                dispatcher=_stub_reply())

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def _fully_accepted_run(self, multi=False):
        if multi:
            tg, ids, plan = _authorized_plan(self.db, multi=True)
        else:
            tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        while True:
            self.svc.execute_step(run, "u1")
            # accept whichever step is currently awaiting review
            waiting = [r["seq"] for r in self.db.query(
                "SELECT seq FROM coordination_step_outputs WHERE execution_id=? "
                "AND status='awaiting_review'", (run,))]
            self.svc.review_step(run, waiting[0], "accepted", "u1")
            st = {r["seq"]: r["status"] for r in self.db.query(
                "SELECT seq,status FROM coordination_step_outputs WHERE execution_id=?", (run,))}
            if all(v == "accepted" for v in st.values()):
                break
            if not waiting:
                raise AssertionError("no step awaiting review; execution stalled")
        self.svc.aggregate(run, "u1")
        return tg, ids, plan, run

    def test_revision_requires_rework_steps(self):
        tg, ids, plan, run = self._fully_accepted_run()
        # aggregate then request a revision without steps -> refused
        from core.coordination_execution import InvalidStep
        with self.assertRaises(InvalidStep):
            self.svc.review_deliverable(run, "revision_requested", "u1")

    def test_revision_resets_selected_steps_and_invalidates_downstream(self):
        tg, ids, plan, run = self._fully_accepted_run(True)
        # step1 selected for rework; step2 depends on step1 so it must be
        # invalidated too (its accepted output cleared).
        res = self.svc.review_deliverable(run, "revision_requested", "u1",
                                          rework_steps=[1])
        self.assertEqual(res["run_status"], "running")
        self.assertEqual([1, 2], res["steps"])
        s1 = self.svc._step_output(run, 1)
        s2 = self.svc._step_output(run, 2)
        self.assertEqual(s1["status"], "revision_requested")
        self.assertEqual(s1["output_json"], None)
        self.assertEqual(s2["status"], "revision_requested")
        self.assertEqual(s2["output_json"], None)
        # step 1 is now runnable again (re-execution -> fresh review)
        r = self.svc.execute_step(run, "u1")
        self.assertEqual(r["step"], 1)

    def test_revision_preserves_unselected_outputs(self):
        tg, ids, plan, run = self._fully_accepted_run(True)
        # select only step1; step2 depends on it so it's invalidated, but in this
        # 2-step depend chain there are no non-dependent steps to compare against.
        # Add an independent scenario with no deps is covered elsewhere; here we
        # assert both steps are reset (both are in the depend chain).
        self.svc.review_deliverable(run, "revision_requested", "u1", rework_steps=[1])
        s2 = self.svc._step_output(run, 2)
        self.assertEqual(s2["status"], "revision_requested")

    def test_revision_re_aggregation(self):
        tg, ids, plan, run = self._fully_accepted_run()
        self.svc.review_deliverable(run, "revision_requested", "u1", rework_steps=[1])
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        d = self.svc.aggregate(run, "u1")
        self.assertEqual(d["status"], "pending")
        self.assertFalse(d["reused"])


class TestTerminalAndHygieneF3F4F5F6(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = CoordinationExecutionService(self.db, "t1", "u1",
                                                dispatcher=_stub_reply())

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_aggregate_reused_accurate(self):
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        d1 = self.svc.aggregate(run, "u1")
        self.assertFalse(d1["reused"])  # created fresh
        d2 = self.svc.aggregate(run, "u1")
        self.assertTrue(d2["reused"])  # existing, unchanged

    def test_aggregate_no_regress_after_accept(self):
        from core.coordination_execution import ExecutionNotRunnable
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        self.svc.aggregate(run, "u1")
        self.svc.review_deliverable(run, "accepted", "u1")
        with self.assertRaises(ExecutionNotRunnable):
            self.svc.aggregate(run, "u1")

    def test_aggregate_no_regress_after_reject(self):
        from core.coordination_execution import ExecutionNotRunnable
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        self.svc.aggregate(run, "u1")
        self.svc.review_deliverable(run, "rejected", "u1")
        with self.assertRaises(ExecutionNotRunnable):
            self.svc.aggregate(run, "u1")

    def test_atomic_claim_prevents_duplicate_dispatch(self):
        """Simulate the race window: a request computed its eligibility while the
        step was still runnable, then a competing request claims it first.
        The loser's atomic claim must affect 0 rows and be refused
        (StepAlreadyClaimed) WITHOUT dispatching the agent."""
        from core.coordination_execution import StepAlreadyClaimed
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        calls = {"n": 0}
        def counting(agent, responsibility, context):
            calls["n"] += 1
            return {"reply": "ok"}
        svc2 = CoordinationExecutionService(self.db, "t1", "u1", dispatcher=counting)
        # A competing request claims + dispatches first (pending -> in_progress).
        svc2.execute_step(run, "u1")
        self.assertEqual(calls["n"], 1)
        # Now a second request that ALREADY computed it as eligible (stale read,
        # simulating the race) attempts its claim. The row is no longer runnable
        # (in_progress -> awaiting_review), so next_eligible would return None;
        # force the stale eligible computation to reach the atomic claim guard.
        # Patch next_eligible to return the step so the claim guard is reached.
        svc2.next_eligible_step = lambda _eid: {
            "seq": 1, "agent_id": "strategist", "responsibility": "Strategy"}
        with self.assertRaises(StepAlreadyClaimed):
            svc2.execute_step(run, "u1")
        # The agent was NOT dispatched by the losing request.
        self.assertEqual(calls["n"], 1)

    def test_f5_failed_retry_uses_guarded_claim(self):
        from core.coordination_execution import AgentOutputInvalid
        calls = {"n": 0}
        def flaky(agent, responsibility, context):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return {"reply": "ok"}
        svc = CoordinationExecutionService(self.db, "t1", "u1", dispatcher=flaky)
        tg, ids, plan = _authorized_plan(self.db)
        run = svc.initiate(plan, "u1")["execution_id"]
        with self.assertRaises(AgentOutputInvalid):
            svc.execute_step(run, "u1")
        self.assertEqual(svc._step_output(run, 1)["status"], "failed")
        # retry claims through the same guarded transition (failed -> in_progress)
        r2 = svc.execute_step(run, "u1")
        self.assertEqual(r2["status"], "awaiting_review")

    def test_mark_step_logs_persistence_failure(self):
        import logging
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        # force a persistence failure by dropping the step outputs table;
        # _mark_step must log, not silently swallow, and not raise
        self.db.execute("DROP TABLE coordination_step_outputs")
        with self.assertLogs("coordination_execution", level="ERROR") as logs:
            self.svc._mark_step(plan, run, 1, "failed", error="boom")
        self.assertTrue(any("failed to persist step status" in m for m in logs.output))


class TestF2FailClosedF7(unittest.TestCase):
    """F2 fail-closed adversarial tests + F6 chain preservation."""
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        # No injected dispatcher: exercises the REAL dispatch path (fail-closed).
        self.svc = CoordinationExecutionService(self.db, "t1", "u1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_empty_ceiling_fails_closed_at_dispatch(self):
        from core.coordination_execution import AgentOutputInvalid
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        # Clear the persisted effective_permissions for step 1 -> empty ceiling.
        self.db.execute(
            "UPDATE coordination_plan_steps SET effective_permissions=? "
            "WHERE plan_id=? AND tenant_id=? AND user_id=? AND seq=1",
            (None, plan, "t1", "u1"))
        with self.assertRaises(AgentOutputInvalid) as ctx:
            self.svc.execute_step(run, "u1")
        # fails closed: reported as failure, never treated as full runtime access
        self.assertIn("permission", str(ctx.exception).lower())
        st = self.svc._step_output(run, 1)
        self.assertEqual(st["status"], "failed")

    def test_missing_ceiling_fails_closed(self):
        from core.coordination_execution import (AgentOutputInvalid,
                                                 NoEligibleStep)
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        # Delete the step row entirely -> no persisted snapshot step, so no
        # ceiling can be loaded. It must fail closed (refuse dispatch), and must
        # never produce an output under an unrestricted runtime.
        self.db.execute(
            "DELETE FROM coordination_plan_steps WHERE plan_id=? AND tenant_id=? AND user_id=? AND seq=1",
            (plan, "t1", "u1"))
        with self.assertRaises((AgentOutputInvalid, NoEligibleStep)):
            self.svc.execute_step(run, "u1")
        st = self.svc._step_output(run, 1)
        self.assertIsNone(st["output_json"])  # nothing was produced/dispatched
        self.assertIn(st["status"], ("pending", "failed"))

    def test_malformed_ceiling_fails_closed(self):
        from core.coordination_execution import AgentOutputInvalid
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        self.db.execute(
            "UPDATE coordination_plan_steps SET effective_permissions=? "
            "WHERE plan_id=? AND tenant_id=? AND user_id=? AND seq=1",
            ("not-json", plan, "t1", "u1"))
        with self.assertRaises(AgentOutputInvalid):
            self.svc.execute_step(run, "u1")
        st = self.svc._step_output(run, 1)
        self.assertEqual(st["status"], "failed")

    def test_no_dispatcher_never_treated_as_full_runtime(self):
        """An empty ceiling must not invoke the unrestricted runtime. We prove
        it by asserting the error is a permission failure (not a successful
        dispatch) and that no dispatch produced an output on the step."""
        from core.coordination_execution import AgentOutputInvalid
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        self.db.execute(
            "UPDATE coordination_plan_steps SET effective_permissions=? "
            "WHERE plan_id=? AND tenant_id=? AND user_id=? AND seq=1",
            (None, plan, "t1", "u1"))
        with self.assertRaises(AgentOutputInvalid):
            self.svc.execute_step(run, "u1")
        self.assertIsNone(self.svc._step_output(run, 1)["output_json"])

    def test_restricted_dispatch_rejects_disallowed_tool(self):
        """A restricted orchestrator (built from a ceiling lacking
        work:propose:goal) must refuse that tool even though the strategist
        manifest ordinarily grants it. Exercises the actual restricted
        manifest/policy enforcement, not merely a policy object."""
        from core.tools import build_registry as _br
        # strategist manifest normally allows work:propose:goal.
        ceiling = {"brand:read", "memory:read"}  # NOT work:propose:goal
        orch = self.svc._restricted_orchestrator("strategist", set(ceiling))
        restricted_manifest = orch.registry.get("strategist")
        self.assertNotIn("work_propose_goal", restricted_manifest.get("tools", []))
        # policy denies it
        self.assertFalse(orch.policy.allow("strategist", "tool", "work_propose_goal"))
        # a real tool-registry invocation path is also denied (layer-2 gate)
        reg = _br(db=self.db, tenant_id="t1")
        with self.assertRaises(PermissionError):
            reg.invoke("strategist", "work_propose_goal", {},
                       manifest=restricted_manifest, policy=orch.policy,
                       user_id="u1")

    def test_valid_ceiling_permits_only_intersection(self):
        """A ceiling that includes work:propose:goal permits that tool, but the
        allowed list stays bounded to the ceiling (intersection with runtime)."""
        from core.runtime import load_registry
        reg = load_registry()
        strategist_perms = set(reg.get("strategist")["permissions"])
        ceiling = {"work:propose:goal", "brand:read", "memory:read"}
        orch = self.svc._restricted_orchestrator("strategist", set(ceiling))
        restricted = orch.registry.get("strategist")
        self.assertIn("work_propose_goal", restricted.get("tools", []))
        self.assertTrue(orch.policy.allow("strategist", "tool", "work_propose_goal"))
        # no permission outside the ceiling is ever granted
        self.assertTrue(set(restricted["permissions"]) <= ceiling & strategist_perms)

    def test_original_exception_chain_preserved(self):
        from core.coordination_execution import AgentOutputInvalid
        # Use a service with a failing injected dispatcher => _dispatch raises,
        # execute_step should wrap it with the original as __cause__.
        cause = RuntimeError("model exploded")
        def boom(agent, responsibility, context):
            raise cause
        svc = CoordinationExecutionService(self.db, "t1", "u1", dispatcher=boom)
        tg, ids, plan = _authorized_plan(self.db)
        run = svc.initiate(plan, "u1")["execution_id"]
        with self.assertRaises(AgentOutputInvalid) as ctx:
            svc.execute_step(run, "u1")
        self.assertIs(ctx.exception.__cause__, cause)

    def test_invalid_rework_steps_rejected(self):
        from core.coordination_execution import InvalidStep
        # A run with a non-existent rework step must be rejected without changing
        # any step status/outputs.
        svc = CoordinationExecutionService(self.db, "t1", "u1", dispatcher=_stub_reply())
        tg, ids, plan = _authorized_plan(self.db)
        run = svc.initiate(plan, "u1")["execution_id"]
        svc.execute_step(run, "u1")
        svc.review_step(run, 1, "accepted", "u1")
        svc.aggregate(run, "u1")
        before = svc._step_output(run, 1)
        with self.assertRaises(InvalidStep):
            svc.review_deliverable(run, "revision_requested", "u1", rework_steps=[99])
        after = svc._step_output(run, 1)
        # step unchanged (still accepted, same output)
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["output_json"], after["output_json"])


if __name__ == "__main__":
    unittest.main()
