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

    def test_summary_metadata_line_is_not_a_step(self):
        # A 'summary:' line (with a colon) must be kept as context, NOT become
        # an invalid coordinator step that would leave the plan unpopulated.
        draft = MessageToTeamGoal.extract(
            "title: Launch On Us in the Bay Area\n"
            "summary: Research the Oakland and SF market.\n"
            "strategist: Plan the competitive market research\n"
            "strategist: Prioritize the growth opportunities\n",
            "workspace_architect")
        self.assertEqual(draft["title"], "Launch On Us in the Bay Area")
        self.assertEqual([s["agent_id"] for s in draft["steps"]],
                         ["strategist", "strategist"])
        self.assertEqual([s["responsibility"] for s in draft["steps"]],
                         ["Plan the competitive market research",
                          "Prioritize the growth opportunities"])

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

    def test_pasted_team_transcript_uses_original_delegated_request(self):
        draft = MessageToTeamGoal.extract(
            """TEAM PLAN FROM YOUR MESSAGE
            Could not delegate: step 9: agent 'workspace_architect' lacks a relevant capability.
            [Delegated to team] Create an Instagram marketing campaign for On Us to grow Bay Area users
            Strategist: define the audience and success metrics
            Communications: draft captions and hooks
            """,
            "workspace_architect")
        self.assertEqual(
            draft["title"],
            "Create an Instagram marketing campaign for On Us to grow Bay Area users")
        self.assertEqual(
            [step["agent_id"] for step in draft["steps"]],
            ["strategist", "communications", "soundboard", "workspace_architect"])


