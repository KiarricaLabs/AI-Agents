"""T2-C-2 — Coordination Plan Builder (isolated DB, never production).

Covers (deterministic, side-effect-free builder):
- Valid approved TeamGoal -> ordered reviewable plan.
- Coordinator preservation.
- Capability mismatch flagged (separate from delegation).
- Authorized workspace_architect -> strategist delegation accepted.
- Undeclared delegation rejected (fail-closed; membership/capability is NOT
  authorization).
- Invalid dependencies / duplicate sequences / circular ordering rejected.
- Proposed or rejected TeamGoals refused.
- Empty-step handling.
- Cross-tenant and cross-user isolation.
- No DB mutations / episodes / tool executions / delegation-log writes.
"""
from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone

from storage.database import Database
from core.team_goal import TeamGoalService
from core.coordination import CoordinationPlanBuilder, CoordinationInvalidPlan
from core.workspace import WorkspaceService, ProjectService, GoalService


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


# Valid: coordinator workspace_architect delegates to strategist (declared rel).
def _valid_plan_payload():
    return {
        "coordinator_agent": "workspace_architect",
        "goal_id": None,  # set in setUp
        "steps": [
            {"seq": 1, "agent_id": "strategist",
             "responsibility": "Strategy and roadmap for the launch"},
            {"seq": 2, "agent_id": "strategist",
             "responsibility": "Prioritize next actions", "depends_on_seq": 1},
        ],
    }


class CoordinationBuilderTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = TeamGoalService(self.db, "t1", "u1")
        self.builder = CoordinationPlanBuilder(self.db, "t1", "u1")
        ids = _scaffold(self.db)
        # create + approve a valid TeamGoal
        self.tg_id = self.svc.propose(
            "Launch", "workspace_architect", goal_id=ids["gid"],
            steps=[{"seq": 1, "agent_id": "strategist",
                    "responsibility": "Strategy for the launch"}])["team_goal_id"]
        self.svc.approve(self.tg_id, "u1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def _counts(self):
        return {
            "goal_steps": len(self.db.query("SELECT id FROM team_goal_steps")),
            "episodes": len(self.db.query("SELECT id FROM episodes")),
            "tool_exec": len(self.db.query("SELECT id FROM tool_executions")),
            "deleg_log": len(self.db.query("SELECT id FROM delegation_log")),
            "approvals": len(self.db.query("SELECT id FROM team_goal_approvals")),
        }

    def test_valid_approved_goal_produces_ordered_plan(self):
        plan = self.builder.build(self.tg_id)
        self.assertTrue(plan["plan_valid"])
        self.assertEqual(plan["coordinator"], "workspace_architect")
        self.assertEqual(plan["goal_id"], self.svc.get(self.tg_id)["goal_id"])
        self.assertEqual(len(plan["steps"]), 1)
        self.assertTrue(plan["steps"][0]["valid"])
        self.assertTrue(plan["steps"][0]["capability_ok"])
        self.assertTrue(plan["steps"][0]["delegation_ok"])
        self.assertTrue(plan["transient"])

    def test_empty_steps_handled(self):
        ids = _scaffold(self.db)
        tg = self.svc.propose("Empty", "workspace_architect", goal_id=ids["gid"],
                              steps=[])["team_goal_id"]
        self.svc.approve(tg, "u1")
        plan = self.builder.build(tg)
        # no steps -> not plan_valid (nothing to coordinate), but no crash
        self.assertFalse(plan["plan_valid"])
        self.assertEqual(plan["steps"], [])

    def test_proposed_goal_refused(self):
        ids = _scaffold(self.db)
        tg = self.svc.propose("NotApproved", "workspace_architect",
                              goal_id=ids["gid"],
                              steps=[{"seq": 1, "agent_id": "strategist",
                                      "responsibility": "strategy"}])["team_goal_id"]
        with self.assertRaises(CoordinationInvalidPlan):
            self.builder.build(tg)

    def test_rejected_goal_refused(self):
        ids = _scaffold(self.db)
        tg = self.svc.propose("Rejected", "workspace_architect", goal_id=ids["gid"],
                              steps=[{"seq": 1, "agent_id": "strategist",
                                      "responsibility": "strategy"}])["team_goal_id"]
        self.svc.approve(tg, "u1")
        self.svc.reject(tg, "u1", reason="no")
        with self.assertRaises(CoordinationInvalidPlan):
            self.builder.build(tg)

    def test_capability_mismatch_flagged(self):
        # tutor assigned to a strategy step: capability check fails even though
        # delegation to strategist would be fine -- verify capability is SEPARATE.
        ids = _scaffold(self.db)
        tg = self.svc.propose("Cap", "workspace_architect", goal_id=ids["gid"],
                              steps=[{"seq": 1, "agent_id": "tutor",
                                      "responsibility": "Strategy for launch"}])["team_goal_id"]
        self.svc.approve(tg, "u1")
        plan = self.builder.build(tg)
        self.assertFalse(plan["steps"][0]["capability_ok"])
        self.assertFalse(plan["steps"][0]["valid"])
        self.assertFalse(plan["plan_valid"])
        self.assertTrue(any("lack" in e or "capabilit" in e for e in plan["errors"]))

    def test_undeclared_delegation_rejected(self):
        # strategist -> tutor: capability ok (tutor has abilities) but delegation
        # from strategist to tutor is NOT declared -> fail-closed invalid.
        ids = _scaffold(self.db)
        tg = self.svc.propose("Deleg", "strategist", goal_id=ids["gid"],
                              steps=[{"seq": 1, "agent_id": "tutor",
                                      "responsibility": "Explain a concept"}])["team_goal_id"]
        self.svc.approve(tg, "u1")
        plan = self.builder.build(tg)
        self.assertTrue(plan["steps"][0]["capability_ok"])
        self.assertFalse(plan["steps"][0]["delegation_ok"])
        self.assertFalse(plan["steps"][0]["valid"])
        self.assertFalse(plan["plan_valid"])
        self.assertTrue(any("delegation" in e for e in plan["errors"]))

    def test_authorized_architect_to_strategist_accepted(self):
        # already covered by test_valid_approved_goal; add explicit second step
        ids = _scaffold(self.db)
        tg = self.svc.propose("Auth", "workspace_architect", goal_id=ids["gid"],
                              steps=[{"seq": 1, "agent_id": "strategist",
                                      "responsibility": "Strategy"}])["team_goal_id"]
        self.svc.approve(tg, "u1")
        plan = self.builder.build(tg)
        self.assertTrue(plan["steps"][0]["delegation_ok"])
        self.assertTrue(plan["plan_valid"])

    def test_invalid_dependency_out_of_range(self):
        # Insert an approved goal with a step whose depends_on_seq references a
        # non-existent later seq (bypassing propose) to exercise the builder's
        # own dependency validation.
        ids = _scaffold(self.db)
        now = datetime.now(timezone.utc).isoformat()
        tg = "baddep"
        self.db.execute(
            "INSERT INTO team_goals "
            "(id,tenant_id,user_id,goal_id,title,coordinator_agent,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (tg, "t1", "u1", ids["gid"], "BadDep", "workspace_architect",
             "approved", now, now))
        self.db.execute(
            "INSERT INTO team_goal_steps "
            "(id,tenant_id,user_id,team_goal_id,seq,agent_id,responsibility,depends_on_seq,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), "t1", "u1", tg, 1, "strategist", "strategy", 99,
             "planned", now, now))
        with self.assertRaises(CoordinationInvalidPlan):
            self.builder.build(tg)

    def test_circular_dependency_rejected(self):
        # Insert two steps whose ordering violates acyclicity (a step depends on
        # one that is stored before it) to exercise the builder's cycle guard.
        ids = _scaffold(self.db)
        now = datetime.now(timezone.utc).isoformat()
        tg = "circgoal"
        self.db.execute(
            "INSERT INTO team_goals "
            "(id,tenant_id,user_id,goal_id,title,coordinator_agent,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (tg, "t1", "u1", ids["gid"], "Circ", "workspace_architect",
             "approved", now, now))
        # seq1 depends on seq2, but seq2 is stored after seq1 -> cyclic ordering.
        for seq, dep in ((1, 2), (2, None)):
            self.db.execute(
                "INSERT INTO team_goal_steps "
                "(id,tenant_id,user_id,team_goal_id,seq,agent_id,responsibility,depends_on_seq,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), "t1", "u1", tg, seq, "strategist",
                 "strategy", dep, "planned", now, now))
        with self.assertRaises(CoordinationInvalidPlan):
            self.builder.build(tg)

    def test_duplicate_sequence_rejected(self):
        # Insert an approved goal whose steps contain a duplicate seq directly,
        # bypassing propose (which already enforces contiguity), so we exercise
        # the builder's own sequence validation.
        ids = _scaffold(self.db)
        now = datetime.now(timezone.utc).isoformat()
        tg = "dupgoal"
        self.db.execute(
            "INSERT INTO team_goals "
            "(id,tenant_id,user_id,goal_id,title,coordinator_agent,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (tg, "t1", "u1", ids["gid"], "Dup", "workspace_architect", "approved", now, now))
        for seq in (1, 1):
            self.db.execute(
                "INSERT INTO team_goal_steps "
                "(id,tenant_id,user_id,team_goal_id,seq,agent_id,responsibility,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), "t1", "u1", tg, seq,
                 "strategist", "strategy", "planned", now, now))
        with self.assertRaises(CoordinationInvalidPlan):
            self.builder.build(tg)

    def test_no_side_effects(self):
        before = self._counts()
        self.builder.build(self.tg_id)
        after = self._counts()
        self.assertEqual(before, after)  # no writes at all


class CoordinationIsolationTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_cross_tenant_goal_invisible_to_builder(self):
        a = Database(path=self.path, tenant_id="tenantA")
        svcA = TeamGoalService(a, "tenantA", "uA")
        ids = _scaffold(a, "tenantA", "uA")
        tg = svcA.propose("X", "workspace_architect", goal_id=ids["gid"],
                          steps=[{"seq": 1, "agent_id": "strategist",
                                  "responsibility": "strategy"}])["team_goal_id"]
        svcA.approve(tg, "uA")
        b = Database(path=self.path, tenant_id="tenantB")
        builderB = CoordinationPlanBuilder(b, "tenantB", "uB")
        with self.assertRaises(CoordinationInvalidPlan):
            builderB.build(tg)  # not visible / not found -> refused

    def test_cross_user_goal_invisible_to_builder(self):
        a = Database(path=self.path, tenant_id="t1")
        svc1 = TeamGoalService(a, "t1", "u1")
        ids = _scaffold(a, "t1", "u1")
        tg = svc1.propose("Y", "workspace_architect", goal_id=ids["gid"],
                          steps=[{"seq": 1, "agent_id": "strategist",
                                  "responsibility": "strategy"}])["team_goal_id"]
        svc1.approve(tg, "u1")
        builder2 = CoordinationPlanBuilder(a, "t1", "u2")
        with self.assertRaises(CoordinationInvalidPlan):
            builder2.build(tg)


if __name__ == "__main__":
    unittest.main()
