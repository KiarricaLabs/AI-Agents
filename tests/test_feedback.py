import os
import tempfile
import unittest

from agents.base import BaseAgent
from core.feedback import FeedbackService
from storage.database import Database


class FeedbackServiceTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = FeedbackService(self.db, "t1", "u1")

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + suffix)
            except OSError:
                pass

    def test_scoped_feedback_requires_explicit_lesson_approval(self):
        row = self.svc.submit(
            "brand", "on-us", "thumbs_down",
            "Too corporate; make it warmer.",
            agent_id="communications", task_type="campaign",
            lesson="Prefer warm, direct language for On Us.",
        )
        self.assertEqual(row["status"], "recorded")
        self.assertEqual(self.svc.approved_lessons("brand", "on-us"), [])
        approved = self.svc.approve_lesson(row["id"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(len(self.svc.approved_lessons("brand", "on-us")), 1)

    def test_feedback_scopes_do_not_cross_users(self):
        self.svc.submit("team", None, "approved", "Show tradeoffs.")
        other = FeedbackService(self.db, "t1", "u2")
        self.assertEqual(other.list(), [])

    def test_validation_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "scope_id"):
            self.svc.submit("brand", None, "approved", "good")
        with self.assertRaisesRegex(ValueError, "rating"):
            self.svc.submit("team", None, "bad", "bad")

    def test_lessons_are_scoped_to_agent_and_brand(self):
        self.svc.submit("team", None, "approved", "team rule",
                        lesson="Always show the next step.")
        self.svc.submit("agent", "communications", "approved", "agent rule",
                        lesson="Use a clear call to action.")
        self.svc.submit("brand", "on-us", "approved", "brand rule",
                        lesson="Keep On Us community-centered.")
        for row in self.svc.list():
            if row["lesson"]:
                self.svc.approve_lesson(row["id"])
        lessons = self.svc.lessons_for("communications", "on-us")
        text = "\n".join(row["lesson"] for row in lessons)
        self.assertIn("next step", text)
        self.assertIn("call to action", text)
        self.assertIn("community-centered", text)
        self.assertEqual(self.svc.lessons_for("tutor", "other-brand")[0]["scope_type"], "team")

    def test_base_agent_prompt_receives_only_selected_lessons(self):
        self.svc.submit("brand", "on-us", "approved", "feedback",
                        lesson="Use the On Us voice.")
        row = self.svc.list()[0]
        self.svc.approve_lesson(row["id"])
        lessons = self.svc.lessons_for("communications", "on-us")
        agent = BaseAgent(
            feedback=self.svc,
            manifest={"name": "communications", "identity": {
                "display_name": "Test", "role": "Communications",
            }},
        )
        prompt = agent._system_prompt(lessons=lessons)
        self.assertIn("Use the On Us voice.", prompt)
        self.assertIn("APPROVED FEEDBACK LESSONS", prompt)


if __name__ == "__main__":
    unittest.main()
