"""AI Team 2.0 (T2-A) — team relevance routing + group-thread schema.

Covers, on an isolated DB (never production):
- Hybrid routing: capability pass filters ineligible agents; context pass ranks.
- Non-relevant agents stay silent; responder cap honored.
- Sequential dispatch to the relevant shortlist only.
- Group thread creation (team/project), participants, workspace binding.
- Cross-tenant / cross-user isolation on thread + message routing.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from config.settings import DB_PATH
from storage.database import Database
from core.runtime import load_registry, build_local_policy
from core.team_router import TeamRouter, _is_plan_request
from core.workspace import WorkspaceService
from core.orchestrator import Orchestrator
from api.app import app

TENANT = "ai2routing"


def _fresh():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


class _StubOrch:
    """Deterministic dispatch stub: records calls, returns canned replies."""

    def __init__(self):
        self.calls = []

    def dispatch(self, agent_name, task, context=None):
        self.calls.append(agent_name)
        return {"reply": f"[{agent_name}] got: {task}", "model": "stub"}


class TeamRouterTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh()
        self.db = Database(path=self.path, tenant_id=TENANT)
        self.reg = load_registry()
        self.policy = build_local_policy(self.reg)
        self.orch = _StubOrch()
        self.router = TeamRouter(self.reg, self.orch, TENANT, "u1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def _real_orch(self):
        return Orchestrator(registry=self.reg, policy=self.policy, router=None,
                            memory=None, user_id="u1", tools=None, brand=None)

    def test_capability_pass_filters_ineligible(self):
        # A communications/marketing message routes to the comms-capable agent,
        # and never to an agent that lacks a matching capability.
        relevant = self.router.relevant("draft an announcement for the launch")
        self.assertIn("communications", relevant)
        self.assertNotIn("soundboard", relevant)  # no matching capability
        self.assertNotIn("tutor", relevant)

    def test_plan_message_routes_to_coordinator_capabilities(self):
        relevant = self.router.relevant("plan the roadmap for the project")
        self.assertIn("strategist", relevant)

    def test_respects_responder_cap(self):
        small = TeamRouter(self.reg, self.orch, TENANT, "u1", max_responders=1)
        relevant = small.relevant("organize the project and plan the roadmap")
        self.assertLessEqual(len(relevant), 1)

    def test_empty_message_no_routing(self):
        self.assertEqual(self.router.relevant("   "), [])

    def test_dispatch_only_calls_relevant_agents(self):
        res = self.router.dispatch_team("draft an announcement", {})
        self.assertIn("communications", res["routed_to"])
        for agent in res["routed_to"]:
            self.assertIn(agent, self.orch.calls)

    def test_honest_coordination_flag_single(self):
        res = self.router.dispatch_team("quiz me on a concept", {})
        # tutor is the quiz-capable agent; a single responder is NOT "multi-agent".
        self.assertFalse(res["coordinated_team_response"])
        self.assertEqual(res["coordination"], "single-coordinator" if res["responses"] else "none")

    def test_plan_intent_detection(self):
        self.assertTrue(_is_plan_request("organize the launch of my project"))
        self.assertTrue(_is_plan_request("help me plan the roadmap"))
        self.assertFalse(_is_plan_request("hello there"))


class SchemaIsolationTest(unittest.TestCase):
    """Group-thread + participants + cross-tenant isolation."""

    def setUp(self):
        self.path = _fresh()

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_thread_type_default_and_workspace_binding(self):
        a = Database(path=self.path, tenant_id="tenantA")
        from core.memory import MemoryService
        svc = MemoryService(db=a, tenant_id="tenantA")
        thread_id = "t1"
        svc.get_or_create_thread("uA", thread_id, "strategist", "hi")
        row = a.query("SELECT thread_type, workspace_id FROM conversation_threads WHERE thread_id=?",
                      (thread_id,))[0]
        self.assertEqual(row["thread_type"], "agent")  # default preserved
        # explicit team thread via team router API update path
        a.execute("UPDATE conversation_threads SET thread_type='team' WHERE thread_id=? AND tenant_id=?",
                  (thread_id, "tenantA"))
        row = a.query("SELECT thread_type FROM conversation_threads WHERE thread_id=?",
                      (thread_id,))[0]
        self.assertEqual(row["thread_type"], "team")

    def test_participants_created(self):
        a = Database(path=self.path, tenant_id="tenantA")
        a.execute(
            "INSERT INTO conversation_threads "
            "(thread_id,tenant_id,user_id,agent_id,title,is_renamed,created_at,updated_at) "
            "VALUES ('tid','tenantA','uA','strategist','T','0','now','now')")
        a.execute(
            "INSERT INTO conversation_participants "
            "(id,thread_id,agent_id,tenant_id,user_id,joined_at) VALUES ('p1','tid','strategist','tenantA','uA','now')")
        rows = a.query("SELECT agent_id FROM conversation_participants WHERE thread_id=? AND tenant_id=?",
                       ("tid", "tenantA"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent_id"], "strategist")

    def test_cross_tenant_thread_isolation(self):
        a = Database(path=self.path, tenant_id="tenantA")
        a.execute(
            "INSERT INTO conversation_threads "
            "(thread_id,tenant_id,user_id,agent_id,title,is_renamed,created_at,updated_at) "
            "VALUES ('tid','tenantA','uA',NULL,'T','0','now','now')")
        b = Database(path=self.path, tenant_id="tenantB")
        rows = b.query("SELECT thread_id FROM conversation_threads WHERE thread_id='tid' AND tenant_id=?",
                       ("tenantB",))
        self.assertEqual(rows, [])


class TeamRouterApiTest(unittest.TestCase):
    """Endpoint-level checks under LOCAL_MODE (tenant/user = 'local'); the test
    bootstrap points DB_PATH at an isolated DB, never production pat.db."""

    def setUp(self):
        from config.settings import DB_PATH
        self.api_db = Database(path=DB_PATH, tenant_id="local")
        self.wid = WorkspaceService(self.api_db, "local", "local").create("WS")

    def _client(self):
        return TestClient(app)

    def test_create_team_thread_roundtrip(self):
        c = self._client()
        r = c.post("/team/threads", json={"title": "Team room", "thread_type": "team"})
        self.assertEqual(r.status_code, 200, r.text)
        tid = r.json()["thread_id"]
        # verify persisted with thread_type='team'
        row = self.api_db.query(
            "SELECT thread_type FROM conversation_threads WHERE thread_id=? AND tenant_id='local'",
            (tid,))[0]
        self.assertEqual(row["thread_type"], "team")

    def test_project_thread_requires_owned_workspace(self):
        c = self._client()
        r = c.post("/team/threads", json={"title": "P", "thread_type": "project",
                                           "workspace_id": "nope"})
        self.assertEqual(r.status_code, 404, r.text)

    def test_add_participant_rejects_unknown_agent(self):
        c = self._client()
        tid = c.post("/team/threads", json={"title": "T", "thread_type": "team"}).json()["thread_id"]
        r = c.post(f"/team/threads/{tid}/participants", json={"agent_id": "notanagent"})
        self.assertEqual(r.status_code, 422)

    def test_propose_plan_creates_no_records(self):
        c = self._client()
        before = {t: len(self.api_db.query(f"SELECT id FROM {t}")) for t in
                  ("workspaces", "goals", "assignments", "episodes", "milestones")}
        r = c.post("/team/plans", json={
            "title": "Plan", "agent_id": "strategist",
            "milestones": [{"title": "M1", "order": 1}],
            "tasks": [{"title": "T1", "agent": "communications"}],
        })
        self.assertEqual(r.status_code, 200, r.text)
        for t, n in before.items():
            self.assertEqual(len(self.api_db.query(f"SELECT id FROM {t}")), n,
                             f"{t} must be unchanged after plan propose")

    def test_revision_endpoint_preserves_original(self):
        c = self._client()
        pid = c.post("/team/plans", json={"title": "P", "agent_id": "strategist"}).json()["proposal_id"]
        orig = self.api_db.query(
            "SELECT payload_json FROM work_proposals WHERE id=?", (pid,))[0]["payload_json"]
        r = c.post(f"/team/plans/{pid}/revision",
                   json={"agent_id": "strategist", "payload_updates": {"title": "P v2"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["revision_of"], pid)
        after = self.api_db.query(
            "SELECT payload_json FROM work_proposals WHERE id=?", (pid,))[0]["payload_json"]
        self.assertEqual(orig, after)  # original byte-for-byte

    def test_plan_revision_of_must_be_plan(self):
        c = self._client()
        # create a non-plan proposal via work/proposals
        r = c.post("/work/proposals", json={
            "work_type": "workspace", "action": "create", "payload": {"name": "WS2"},
            "agent_id": "workspace_architect"})
        self.assertEqual(r.status_code, 200, r.text)
        nonplan = r.json()["proposal_id"]
        r = c.post(f"/team/plans/{nonplan}/revision",
                   json={"agent_id": "strategist", "payload_updates": {}})
        self.assertEqual(r.status_code, 422)

    def test_approve_plan_creates_workspace_t2b(self):
        c = self._client()
        ws_before = len(self.api_db.query("SELECT id FROM workspaces"))
        pid = c.post("/team/plans", json={
            "title": "P", "agent_id": "strategist",
            "tasks": [{"title": "T1", "agent": "communications"}]}).json()["proposal_id"]
        r = c.post(f"/work/proposals/{pid}/approve", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.api_db.query("SELECT status FROM work_proposals WHERE id=?",
                                           (pid,))[0]["status"], "approved")
        self.assertEqual(len(self.api_db.query("SELECT id FROM workspaces")), ws_before + 1)
        # approval must not auto-create any episode (no auto-execution)
        self.assertEqual(len(self.api_db.query("SELECT id FROM episodes")), 0)

    def test_list_plans_scoped_by_tenant(self):
        c = self._client()
        c.post("/team/plans", json={"title": "P1", "agent_id": "strategist"})
        r = c.get("/team/plans")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(x["work_type"] == "plan" for x in r.json()["plans"]))

    def test_milestones_endpoint_validates_ownership(self):
        c = self._client()
        from core.workspace import ProjectService
        pid = ProjectService(self.api_db, "local", "local").create(self.wid, "Proj")
        r = c.post("/team/milestones", json={"project_id": pid, "title": "M1"})
        self.assertEqual(r.status_code, 200, r.text)
        r2 = c.post("/team/milestones", json={"project_id": "nope", "title": "M"})
        self.assertEqual(r2.status_code, 404)

    def test_dependencies_endpoint(self):
        c = self._client()
        r = c.post("/team/dependencies", json={
            "from_type": "task", "from_id": "t1", "to_type": "task", "to_id": "t2"})
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
