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
from core.message_work_extractor import MessageToAssignment, MessageToDeliverable


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


if __name__ == "__main__":
    unittest.main()
