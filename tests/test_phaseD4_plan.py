"""M10 D4.3-A1 — Unified coordinated-plan preview.

Covers:
- Capability-derived owner suggestions (from agent manifests, never granting)
- plan_steps structured parsing + honest failure markers
- PlanService.generate shaping a transient plan (no records, no execution)
- POST /agents/plan endpoint: validation, ownership/isolation, success
- Guarantee: the preview creates no proposals/goals/assignments/episodes
"""
from __future__ import annotations
import json, os, tempfile, unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from config.settings import DB_PATH
from storage.database import Database
from core.tools import build_registry
from core.runtime import load_registry, build_local_policy
from core.workspace import WorkspaceService, ProjectService
from agents.base import BaseAgent
from core.errors import ModelUnavailableError
from core.plan import PlanService, DEFAULT_COORDINATOR
from api.app import app

TENANT = "phaseD4plan"


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


class _FakeEnvelope:
    def __init__(self, text):
        self.text = text
        self.provider = "ollama"
        self.model = "llama3.1"
        self.location = "local:ollama:llama3.1"


class _FakeRouter:
    def __init__(self, text, exc=None):
        self._text = text
        self._exc = exc

    def complete(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return _FakeEnvelope(self._text)


class _StubOrch:
    def __init__(self, steps, generation_error=None):
        self._steps = steps
        self._err = generation_error

    def plan(self, agent_name, task, context):
        out = {"agent": agent_name, "reply": "sum", "steps": self._steps,
               "provider": "ollama", "model": "m", "location": "local"}
        if self._err:
            out["generation_error"] = self._err
        return out


class PlanUnitBase(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=TENANT)
        t, u = TENANT, "u1"
        self.wid = WorkspaceService(self.db, t, u).create("Personal")
        self.pid = ProjectService(self.db, t, u).create(self.wid, "Launch")
        self.reg = load_registry()
        self.policy = build_local_policy(self.reg)

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)


class TestOwnerSuggestions(PlanUnitBase):
    def test_capability_derived_candidates(self):
        svc = PlanService(_StubOrch([]), TENANT, "u1")
        self.assertIn("workspace_architect", svc.owner_candidates("workspace"))
        self.assertIn("strategist", svc.owner_candidates("goal"))
        self.assertIn("communications", svc.owner_candidates("deliverable"))
        self.assertIn("executive_assistant", svc.owner_candidates("assignment"))
        self.assertIn("communications", svc.owner_candidates("deliverable_version"))

    def test_unknown_type_no_suggestion(self):
        svc = PlanService(_StubOrch([]), TENANT, "u1")
        self.assertEqual(svc.owner_candidates("spaceship"), [])


class TestPlanStepsParsing(PlanUnitBase):
    def _agent(self, slug, text, exc=None):
        a = BaseAgent(memory=None, router=_FakeRouter(text, exc=exc),
                      manifest=self.reg.get(slug), user_id="u1",
                      tools=build_registry(db=self.db, tenant_id=TENANT),
                      policy=self.policy, brand=None)
        a.name = slug
        return a

    def test_valid_envelope_steps(self):
        env = json.dumps({"reply": "ok", "steps": [
            {"work_type": "goal", "action": "create", "title": "Scope launch", "reason": "plan"},
            {"work_type": "deliverable", "action": "create", "title": "Landing page", "reason": "comms"},
        ]})
        r = self._agent("strategist", env).plan_steps("organize a launch", {})
        self.assertEqual(len(r["steps"]), 2)
        self.assertTrue(all(s["title"] for s in r["steps"]))

    def test_invalid_entries_dropped(self):
        env = json.dumps({"reply": "ok", "steps": [
            {"work_type": "goal", "action": "create", "title": "ok"},
            {"work_type": "", "title": "no type"},
            {"work_type": "goal", "title": ""},
            "not a dict",
        ]})
        r = self._agent("strategist", env).plan_steps("t", {})
        self.assertEqual(len(r["steps"]), 1)

    def test_fenced_json_parsed(self):
        env = "```json\n" + json.dumps({"steps": [
            {"work_type": "project", "title": "Portal"}]}) + "\n```"
        r = self._agent("strategist", env).plan_steps("t", {})
        self.assertEqual(len(r["steps"]), 1)

    def test_empty_steps_honest(self):
        r = self._agent("strategist", json.dumps({"reply": "no ideas", "steps": []})).plan_steps("t", {})
        self.assertEqual(r["steps"], [])
        self.assertNotIn("generation_error", r)
        self.assertNotIn("model_empty", r.get("reply", ""))


class TestPlanServiceGenerate(PlanUnitBase):
    def test_shapes_steps_with_suggested_agents(self):
        orch = _StubOrch([
            {"work_type": "goal", "action": "create", "title": "Scope launch", "reason": "r"},
            {"work_type": "deliverable", "action": "create", "title": "Landing", "reason": "r"},
        ])
        plan = PlanService(orch, TENANT, "u1").generate("organize launch", {"project_id": self.pid})
        self.assertEqual(plan["coordinator"], DEFAULT_COORDINATOR)
        self.assertEqual(len(plan["steps"]), 2)
        self.assertIn(plan["steps"][0]["suggested_agent"], ("strategist", "tutor", "executive_assistant"))
        # Deliverable can be owned by communications or workspace_architect; the
        # suggested owner must be one of the capability-derived candidates.
        self.assertIn(plan["steps"][1]["suggested_agent"], plan["steps"][1]["agent_options"])
        self.assertIn("communications", plan["steps"][1]["agent_options"])
        self.assertEqual(plan["steps"][0]["project_id"], self.pid)

    def test_no_records_created_during_preview(self):
        from core.workspace import GoalService
        before = len(self.db.query("SELECT id FROM goals"))
        orch = _StubOrch([{"work_type": "goal", "title": "G"}])
        PlanService(orch, TENANT, "u1").generate("t", {"project_id": self.pid})
        after = len(self.db.query("SELECT id FROM goals"))
        self.assertEqual(after, before)


class TestPlanEndpoint(PlanUnitBase):
    # Uses LOCAL_MODE auto-auth (tenant/user = "local"), matching the app in the
    # test environment. DB_PATH is the isolated test DB set by tests/__init__, so
    # the production data/pat.db is never opened.
    def setUp(self):
        super().setUp()
        self.api_db = Database(path=DB_PATH, tenant_id="local")
        self.wid_l = WorkspaceService(self.api_db, "local", "local").create("Personal")
        self.pid_l = ProjectService(self.api_db, "local", "local").create(self.wid_l, "Launch")

    def _client(self):
        return TestClient(app)

    def test_empty_objective_422(self):
        r = self._client().post("/agents/plan", json={"objective": "   "})
        self.assertEqual(r.status_code, 422)

    def test_foreign_project_404(self):
        r = self._client().post("/agents/plan", json={"objective": "organize", "project_id": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_cross_tenant_project_not_found(self):
        # A project owned by another tenant must be treated as not found (no leak).
        r = self._client().post("/agents/plan", json={"objective": "organize", "project_id": self.pid})
        self.assertEqual(r.status_code, 404)

    def test_success_returns_plan_no_records(self):
        fake = {"agent": "strategist", "reply": "sum",
                "steps": [{"work_type": "goal", "title": "Scope launch"}],
                "provider": "ollama", "model": "m", "location": "local"}
        with patch("agents.base.BaseAgent.plan_steps", return_value=fake):
            r = self._client().post("/agents/plan",
                                    json={"objective": "organize launch", "project_id": self.pid_l})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["objective"], "organize launch")
        self.assertEqual(len(body["steps"]), 1)
        # Preview must create NO new records (the isolated DB may already contain
        # rows from other tests, so assert zero delta per table).
        _before = {t: len(self.api_db.query(f"SELECT id FROM {t}")) for t in
                   ("work_proposals", "goals", "assignments", "episodes")}
        with patch("agents.base.BaseAgent.plan_steps", return_value=fake):
            self._client().post("/agents/plan",
                                json={"objective": "again", "project_id": self.pid_l})
        for table, count in _before.items():
            self.assertEqual(len(self.api_db.query(f"SELECT id FROM {table}")), count,
                             f"{table} must be unchanged after preview")

    def test_run_with_project_grounding_does_not_crash(self):
        # Regression: grounding a run on a project must not abort on the goal
        # lookup (GoalService now receives the scoped user). Model is offline;
        # success means the grounding block ran and failure was handled honestly
        # rather than an internal 500.
        class _Offline:
            def complete(self, agent_id, prompt, system="", model_spec=None, context=None, json_format=False):
                raise ModelUnavailableError("down")
            def check_availability(self):
                return {"ok": False, "available": False, "provider": "ollama", "model": "m", "location": "local:ollama:m", "code": "model_unavailable"}
        with patch("core.runtime.ModelRouter", return_value=_Offline()):
            r = self._client().post("/agents/strategist/run",
                                    json={"task": "hi", "project_id": self.pid_l})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["generation_error"]["code"], "model_unavailable")

    def test_proposal_bridge_is_idempotent(self):
        # The A2 bridge reuses /work/proposals; a duplicate submission of the same
        # finalized step must reuse the same proposal, never create a duplicate.
        body = {"work_type": "goal", "action": "create",
                "payload": {"project_id": self.pid_l, "title": "Dup bridge goal"},
                "agent_id": "strategist"}
        c = self._client()
        r1 = c.post("/work/proposals", json=body)
        r2 = c.post("/work/proposals", json=body)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r1.json()["reused"] or r2.json()["reused"])
        self.assertEqual(r1.json()["proposal_id"], r2.json()["proposal_id"])

    def test_proposal_bridge_rejects_foreign_parent(self):
        before = len(self.api_db.query("SELECT id FROM work_proposals"))
        body = {"work_type": "goal", "action": "create",
                "payload": {"project_id": "not-owned", "title": "X"},
                "agent_id": "strategist"}
        r = self._client().post("/work/proposals", json=body)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(len(self.api_db.query("SELECT id FROM work_proposals")), before)


if __name__ == "__main__":
    unittest.main()


class TestActionableParentNote(PlanUnitBase):
    def _agent(self, envelope_text):
        a = BaseAgent(memory=None, router=_FakeRouter(envelope_text),
                      manifest=self.reg.get("strategist"), user_id="u1",
                      tools=build_registry(db=self.db, tenant_id=TENANT),
                      policy=self.policy, brand=None)
        a.name = "strategist"
        return a

    def test_missing_parent_uses_actionable_note(self):
        a = self._agent(json.dumps({"reply": "ok", "proposal_v1": {
            "work_type": "goal", "action": "create", "payload": {"title": "G"}}}))
        with patch.object(BaseAgent, "_ingest_proposal_block", return_value={
                "status": "failed",
                "error": "project_id is required to create/update this work record"}):
            r = a._generate_structured("make a goal", {"work_intent": True})
        self.assertIn("needs a parent", r["reply"])
        self.assertIn("Project", r["reply"])
        self.assertNotIn("To try again, please confirm the parent", r["reply"])

    def test_generic_failure_keeps_generic_note(self):
        a = self._agent(json.dumps({"reply": "ok", "proposal_v1": {
            "work_type": "goal", "action": "create", "payload": {"title": "G"}}}))
        with patch.object(BaseAgent, "_ingest_proposal_block", return_value={
                "status": "failed", "error": "some other validation issue"}):
            r = a._generate_structured("make a goal", {"work_intent": True})
        self.assertIn("To try again, please confirm the parent", r["reply"])
        self.assertNotIn("needs a parent", r["reply"])
