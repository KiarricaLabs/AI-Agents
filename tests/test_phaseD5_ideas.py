"""M10 Step 1 (Phase D5 ideas) - grounded parented idea proposals.

Covers:
- Agents propose ideas as structured proposal blocks (work_intent) against the
  caller-selected workspace/project context.
- Missing parents are injected server-side from trusted context (never from the
  model) and ownership is still re-validated in-tool.
- A block that omits a required parent and has no selected context is NOT saved
  (existing clarification behavior preserved).
- A foreign/non-owned injected parent is rejected (no record).
- Multiple idea blocks in one envelope are saved independently (per-block).
- Nothing creates a real goal/project record until approval.
"""
from __future__ import annotations
import json, os, tempfile, unittest

from storage.database import Database
from core.tools import build_registry
from core.runtime import load_registry, build_local_policy
from core.workspace import WorkspaceService, ProjectService
from agents.base import BaseAgent

TENANT = "phaseD5"


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
    def __init__(self, text):
        self._text = text

    def complete(self, **kwargs):
        return _FakeEnvelope(self._text)


class IdeasBase(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=TENANT)
        t, u = TENANT, "u1"
        self.wid = WorkspaceService(self.db, t, u).create("Personal")
        self.pid = ProjectService(self.db, t, u).create(self.wid, "Website Launch")
        self.reg = load_registry()
        self.policy = build_local_policy(self.reg)
        self.tools = build_registry(db=self.db, tenant_id=t)

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)

    def _agent(self, slug, envelope_text):
        a = BaseAgent(memory=None, router=_FakeRouter(envelope_text),
                      manifest=self.reg.get(slug), user_id="u1",
                      tools=self.tools, policy=self.policy, brand=None)
        a.name = slug
        return a

    def _count(self, table):
        return self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def _goal_block(self, **over):
        # Intentionally OMITS project_id: Step 1 injection fills it from context.
        b = {"work_type": "goal", "action": "create",
             "payload": {"title": "Guided welcome flow", "priority": 1},
             "reason": "improve onboarding", "expected_result": "x"}
        b.update(over)
        return b

    def _project_block(self, **over):
        b = {"work_type": "project", "action": "create",
             "payload": {"name": "Portal"}, "reason": "r", "expected_result": "x"}
        b.update(over)
        return b


class TestGroundedParentInjection(IdeasBase):
    def test_goal_missing_project_injected_from_context(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "Here is an idea.", "proposal_v1": self._goal_block()}))
        a._ground("think of a goal", context={
            "thread_id": "t1", "work_intent": True,
            "project_id": self.pid, "workspace_id": self.wid})
        rows = self.db.query(
            "SELECT work_type, project_id, status FROM work_proposals")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project_id"], self.pid)
        self.assertEqual(rows[0]["status"], "proposed")
        self.assertEqual(self._count("goals"), 0)
        self.assertEqual(self._count("projects"), 1)  # only the seeded parent

    def test_project_missing_workspace_injected(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": self._project_block()}))
        a._ground("propose a project", context={
            "thread_id": "t1", "work_intent": True, "workspace_id": self.wid})
        rows = self.db.query(
            "SELECT work_type, workspace_id FROM work_proposals")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["workspace_id"], self.wid)

    def test_no_context_missing_parent_not_saved(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": self._goal_block()}))
        a._ground("propose a goal", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(self._count("work_proposals"), 0)

    def test_foreign_injected_parent_rejected(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": self._goal_block()}))
        a._ground("propose a goal", context={
            "thread_id": "t1", "work_intent": True,
            "project_id": "not-owned-project", "workspace_id": "not-owned-ws"})
        self.assertEqual(self._count("work_proposals"), 0)

    def test_array_of_ideas_saved_independently(self):
        envelope = {"reply": "Ideas below", "proposal_v1": [
            self._goal_block(),
            self._goal_block(payload={"title": "Second idea", "priority": 1}),
        ]}
        a = self._agent("strategist", json.dumps(envelope))
        a._ground("ideas", context={
            "thread_id": "t1", "work_intent": True,
            "project_id": self.pid, "workspace_id": self.wid})
        rows = self.db.query(
            "SELECT project_id, status FROM work_proposals ORDER BY created_at")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["project_id"] == self.pid and r["status"] == "proposed"
                            for r in rows))
        self.assertEqual(self._count("goals"), 0)


if __name__ == "__main__":
    unittest.main()
