"""Phase 4 §8 — Conversation → TeamGoal draft generator tests.

Unit tests for MessageToTeamGoal extraction + real-HTTP tests for POST
/team/goals/draft. Confirms:
- deterministic extraction (title, summary, deliverable, ordered steps + deps);
- only explicit '<agent>: task' lines become steps (prose stays as summary);
- unknown coordinator / empty message -> 422;
- non-human role -> 403;
- the draft endpoint NEVER persists or authorizes anything (read-only preview).
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from config.settings import DB_PATH
from core.auth import issue_token
from core.message_extractor import MessageToTeamGoal
from storage.database import Database


class MessageToTeamGoalTest(unittest.TestCase):
    def test_structured_message_into_draft(self):
        draft = MessageToTeamGoal.extract(
            "Launch strategy\n"
            "- strategist: research the market\n"
            "- tutor: explain findings\n"
            "deliverable: a one-page launch plan",
            "workspace_architect")
        self.assertEqual(draft["title"], "Launch strategy")
        self.assertEqual(draft["coordinator_agent"], "workspace_architect")
        self.assertIn("launch plan", draft["expected_deliverable"])
        self.assertEqual([s["seq"] for s in draft["steps"]], [1, 2])
        self.assertEqual(draft["steps"][0]["agent_id"], "strategist")
        self.assertEqual(draft["steps"][1]["agent_id"], "tutor")
        self.assertIsNone(draft["steps"][0]["depends_on_seq"])
        self.assertEqual(draft["steps"][1]["depends_on_seq"], 1)

    def test_prose_stays_as_summary_not_steps(self):
        draft = MessageToTeamGoal.extract(
            "We should expand into Europe. Research the market for our launch.", "strategist")
        # no explicit agent-prefixed step line -> a single coordinator default step
        self.assertEqual(len(draft["steps"]), 1)
        self.assertEqual(draft["steps"][0]["agent_id"], "strategist")
        self.assertIn("expand into europe", (draft["title"] or "").lower())

    def test_unknown_slug_falls_back_to_coordinator(self):
        draft = MessageToTeamGoal.extract(
            "- noneSuch: some task\n- strategist: real task", "workspace_architect")
        agents = [s["agent_id"] for s in draft["steps"]]
        self.assertEqual(agents, ["workspace_architect", "strategist"])

    def test_unknown_coordinator_rejected(self):
        with self.assertRaises(ValueError):
            MessageToTeamGoal.extract("title: x", "no_such_agent")

    def test_empty_message_rejected(self):
        with self.assertRaises(ValueError):
            MessageToTeamGoal.extract("", "strategist")


class DraftEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _h(self, user, tenant, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def test_draft_endpoint_returns_draft(self):
        r = self.client.post(
            "/team/goals/draft",
            json={"message": "Launch\n- strategist: research\n- tutor: teach",
                  "coordinator_agent": "workspace_architect"},
            headers=self._h("u1", "t1"))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["title"], "Launch")
        self.assertEqual(len(body["steps"]), 2)
        self.assertEqual(body["steps"][0]["agent_id"], "strategist")

    def test_draft_endpoint_422_on_bad_input(self):
        r = self.client.post(
            "/team/goals/draft",
            json={"message": "", "coordinator_agent": "strategist"},
            headers=self._h("u1", "t1"))
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post(
            "/team/goals/draft",
            json={"message": "Launch", "coordinator_agent": "nope"},
            headers=self._h("u1", "t1"))
        self.assertEqual(r.status_code, 422, r.text)

    def test_draft_endpoint_403_for_non_human(self):
        r = self.client.post(
            "/team/goals/draft",
            json={"message": "Launch", "coordinator_agent": "strategist"},
            headers=self._h("u1", "t1", role="agent"))
        self.assertEqual(r.status_code, 403, r.text)

    def test_draft_endpoint_is_read_only(self):
        r = self.client.post(
            "/team/goals/draft",
            json={"message": "Launch\n- strategist: research",
                  "coordinator_agent": "workspace_architect"},
            headers=self._h("u1", "t1"))
        self.assertEqual(r.status_code, 200)
        # nothing persisted / no approval / no execution
        db = Database(path=DB_PATH, tenant_id="t1")
        self.assertEqual(db.query(
            "SELECT COUNT(*) AS n FROM team_goals WHERE tenant_id=? AND user_id=?",
            ("t1", "u1"))[0]["n"], 0)
        self.assertEqual(db.query(
            "SELECT COUNT(*) AS n FROM coordination_plans WHERE tenant_id=? AND user_id=?",
            ("t1", "u1"))[0]["n"], 0)
        self.assertEqual(db.query(
            "SELECT COUNT(*) AS n FROM coordination_executions WHERE tenant_id=? AND user_id=?",
            ("t1", "u1"))[0]["n"], 0)


if __name__ == "__main__":
    unittest.main()
