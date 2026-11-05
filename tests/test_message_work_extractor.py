"""Chunk 5 — Conversation → Assignment / Deliverable extraction tests.

Covers the deterministic extractors and the real HTTP ``POST /work/extract``
draft endpoint:
- assignment: title/subject/expected_output/priority parsing;
- deliverable: title/format/responsible_agent/description parsing;
- unknown agents and missing messages are rejected;
- draft extraction persists nothing (``persisted=False``);
- non-human role -> 403; identity comes from the request, never the body.
"""
from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from core.auth import issue_token
from core.message_work_extractor import (
    MessageToAssignment, MessageToDeliverable, MessageToProject, MessageToGoal,
)


class MockModelRouterTest(unittest.TestCase):
    def test_mock_off_by_default_returns_real_path(self):
        # With PAT_MOCK_AGENTS unset, complete() must NOT short-circuit:
        # it should attempt the real provider (Ollama) and fail there, proving
        # mock mode is off by default rather than silently substituting.
        import os
        from core.model_router import ModelRouter

        os.environ.pop("PAT_MOCK_AGENTS", None)
        r = ModelRouter(base_url="http://127.0.0.1:9", timeout=1, retries=0)
        with self.assertRaises(Exception):
            r.complete("strategist", "hi")

    def test_mock_on_returns_deterministic_reply(self):
        import os
        from core.model_router import ModelRouter

        os.environ["PAT_MOCK_AGENTS"] = "1"
        try:
            r = ModelRouter()
            res = r.complete("strategist", "anything")
            self.assertEqual(res.location, "mock")
            self.assertEqual(res.provider, "mock")
            self.assertIn("strategist", res.text.lower())
        finally:
            os.environ.pop("PAT_MOCK_AGENTS", None)

    def test_mock_never_returns_real_location(self):
        import os
        from core.model_router import ModelRouter

        os.environ["PAT_MOCK_AGENTS"] = "1"
        try:
            for slug in ("strategist", "tutor", "unknown_agent"):
                r = ModelRouter().complete(slug, "hi")
                self.assertEqual(r.location, "mock")
                self.assertFalse(r.location.startswith("local:"))
        finally:
            os.environ.pop("PAT_MOCK_AGENTS", None)


class MessageToAssignmentTest(unittest.TestCase):
    def test_extracts_task_subject_output_priority(self):
        d = MessageToAssignment.extract(
            "assign: Research the launch market\n"
            "to: strategist\n"
            "output: a market brief\n"
            "priority: high",
            subject_agent="workspace_architect",
        )
        self.assertEqual(d["kind"], "assignment")
        self.assertEqual(d["title"], "Research the launch market")
        self.assertEqual(d["subject_agent"], "strategist")
        self.assertEqual(d["expected_output"], "a market brief")
        self.assertEqual(d["priority"], "high")
        self.assertEqual(d["source_context"], "conversation")

    def test_falls_back_to_provided_subject(self):
        d = MessageToAssignment.extract("task: Write the spec", subject_agent="tutor")
        self.assertEqual(d["subject_agent"], "tutor")

    def test_inline_to_prefix_wins(self):
        d = MessageToAssignment.extract("task: Draft copy\nstrategist: write it")
        self.assertEqual(d["subject_agent"], "strategist")

    def test_unknown_subject_rejected(self):
        with self.assertRaises(ValueError):
            MessageToAssignment.extract("task: X", subject_agent="bogus_agent")

    def test_empty_message_rejected(self):
        with self.assertRaises(ValueError):
            MessageToAssignment.extract("", subject_agent="tutor")


class MessageToDeliverableTest(unittest.TestCase):
    def test_extracts_title_format_owner_description(self):
        d = MessageToDeliverable.extract(
            "deliverable: One-page launch plan\n"
            "by: strategist\n"
            "format: pdf\n"
            "Covering goals and budget.",
            owner_agent="tutor",
        )
        self.assertEqual(d["kind"], "deliverable")
        self.assertEqual(d["title"], "One-page launch plan")
        self.assertEqual(d["responsible_agent"], "strategist")
        self.assertEqual(d["format"], "pdf")
        self.assertIn("goals", d["description"])

    def test_owner_fallback(self):
        d = MessageToDeliverable.extract("deliverable: The report", owner_agent="workspace_architect")
        self.assertEqual(d["responsible_agent"], "workspace_architect")

    def test_unknown_owner_rejected(self):
        with self.assertRaises(ValueError):
            MessageToDeliverable.extract("deliverable: X by notarealagent")

    def test_empty_message_rejected(self):
        with self.assertRaises(ValueError):
            MessageToDeliverable.extract("")


class MessageToProjectAndGoalTest(unittest.TestCase):
    def test_project_extract_title_description(self):
        d = MessageToProject.extract("project: Launch a mobile app\nSolo founder building an MVP.")
        self.assertEqual(d["kind"], "project")
        self.assertEqual(d["title"], "Launch a mobile app")
        self.assertIn("MVP", d["description"])

    def test_goal_extract_title_description(self):
        d = MessageToGoal.extract("goal: Hit 1,000 users by summer\nFocus on referrals.")
        self.assertEqual(d["kind"], "goal")
        self.assertEqual(d["title"], "Hit 1,000 users by summer")
        self.assertIn("referrals", d["description"])

    def test_empty_rejected(self):
        from core.message_work_extractor import MessageToProject as P, MessageToGoal as G
        with self.assertRaises(ValueError):
            P.extract("")
        with self.assertRaises(ValueError):
            G.extract("")


class ExtractWorkAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _h(self, user, tenant, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def test_extract_assignment_draft_over_http(self):
        t, u = ("tw_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "assignment",
            "message": "assign: Research the market\nto: strategist\npriority: med",
            "subject_agent": "tutor",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["kind"], "assignment")
        self.assertEqual(body["persisted"], False)
        self.assertEqual(body["draft"]["subject_agent"], "strategist")
        self.assertEqual(body["draft"]["title"], "Research the market")

    def test_extract_deliverable_draft_over_http(self):
        t, u = ("tw_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "deliverable",
            "message": "deliverable: Launch deck\nby: workspace_architect",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["kind"], "deliverable")
        self.assertEqual(body["persisted"], False)
        self.assertEqual(body["draft"]["responsible_agent"], "workspace_architect")

    def test_extract_does_not_persist_anything(self):
        t, u = ("tw_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "assignment",
            "message": "task: Something",
            "subject_agent": "strategist",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["persisted"], False)
        # no proposal row is created by extraction
        prop = self.client.get("/work/proposals", headers=self._h(u, t)).json()
        self.assertEqual(prop.get("items", []), [])

    def test_unsupported_kind_400(self):
        t, u = ("tw_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "nonsense", "message": "hi",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 400)

    def test_unknown_agent_400(self):
        t, u = ("tw_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "assignment",
            "message": "task: X",
            "subject_agent": "not_an_agent",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 400)

    def test_non_human_403_on_writes(self):
        t, u = ("tw_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "assignment",
            "message": "task: X\nassign to strategist",
        }, headers=self._h(u, t, role="agent"))
        self.assertEqual(r.status_code, 403)

    def test_extract_project_draft_over_http(self):
        t, u = ("tw_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "project",
            "message": "project: Launch a mobile app",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["kind"], "project")
        self.assertEqual(body["persisted"], False)
        self.assertEqual(body["draft"]["title"], "Launch a mobile app")

    def test_extract_goal_draft_over_http(self):
        t, u = ("tw_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "goal",
            "message": "goal: Grow to 1,000 users",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["draft"]["kind"], "goal")


if __name__ == "__main__":
    unittest.main()
