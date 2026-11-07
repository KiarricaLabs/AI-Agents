"""Structured output-contract extraction + runner best-effort persistence."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.output_contracts import extract_structured, guidance_for
from core.project_runner import ProjectRunner
from storage.database import Database


class OutputContractTest(unittest.TestCase):
    def test_guidance_names_contract_keys(self):
        prompt = guidance_for("positioning_statement")
        self.assertIn("positioning", prompt)
        self.assertIn("audience", prompt)
        self.assertIn("```json", prompt)

    def test_extracts_fenced_json_block_and_strips_prose(self):
        reply = (
            "Here is my positioning draft for On Us.\n\n"
            "```json\n{\"positioning\": \"community-first\", \"audience\": \"Bay Area\", "
            "\"message\": \"connect\", \"summary\": \"short\"}\n```\n"
        )
        structured, prose = extract_structured(reply, "positioning_statement")
        self.assertIsNotNone(structured)
        self.assertEqual(structured["positioning"], "community-first")
        self.assertNotIn("```json", prose)
        self.assertIn("Here is my positioning draft", prose)

    def test_missing_required_key_is_graceful(self):
        reply = '```json\n{"content": "x"}\n```'  # positioning needs more keys
        structured, prose = extract_structured(reply, "positioning_statement")
        self.assertIsNone(structured)  # not enforced -> keep prose, no structured payload
        self.assertIn("x", prose)

    def test_no_json_block_keeps_prose(self):
        structured, prose = extract_structured("just a plain draft", "draft")
        self.assertIsNone(structured)
        self.assertEqual(prose, "just a plain draft")


class RunnerStructuredOutputTest(unittest.TestCase):
    def test_runner_stores_output_json_and_prose_when_agent_complies(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(path=str(Path(directory) / "test.db"), tenant_id="t1")
            now = "2026-01-01T00:00:00+00:00"
            db.execute(
                "INSERT INTO agent_projects "
                "(id,tenant_id,user_id,goal,status,plan_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("p1", "t1", "u1", "Grow users", "running", "{}", now, now))
            db.execute(
                "INSERT INTO agent_tasks "
                "(id,project_id,tenant_id,user_id,agent,instruction,depends_on,status,"
                "deliverable_type,acceptance_criteria,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("a", "p1", "t1", "u1", "strategist",
                 "Define the audience as a positioning statement.", "[]", "pending",
                 "positioning_statement", "[]", now, now))

            class Runtime:
                def dispatch(self, agent, prompt, context):
                    return {"reply": (
                        "On Us is the community-first space for Black Bay Area creatives.\n"
                        "```json\n{\"positioning\": \"community-first\", \"audience\": "
                        "\"Black Bay Area creatives\", \"message\": \"connect and build\", "
                        "\"summary\": \"A concise positioning statement.\"}\n```\n")}

            with patch("core.project_runner.build_runtime", return_value=Runtime()):
                ProjectRunner(db, "t1", "u1").run("p1")
            row = db.query("SELECT output, output_json FROM agent_tasks WHERE id='a'")[0]
            self.assertTrue(row["output"].startswith("On Us is the community-first space"))
            self.assertNotIn("```json", row["output"])
            parsed = json.loads(row["output_json"])
            self.assertEqual(parsed["positioning"], "community-first")


class RunnerRetryTest(unittest.TestCase):
    def _seed(self, db, task_id="a", status="running", project_status="running"):
        now = "2026-01-01T00:00:00+00:00"
        db.execute(
            "INSERT INTO agent_projects "
            "(id,tenant_id,user_id,goal,status,plan_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("p1", "t1", "u1", "Grow users", project_status, "{}", now, now))
        db.execute(
            "INSERT INTO agent_tasks "
            "(id,project_id,tenant_id,user_id,agent,instruction,depends_on,status,"
            "deliverable_type,acceptance_criteria,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, "p1", "t1", "u1", "strategist", "Define the audience.", "[]", "pending",
             "draft", "[]", now, now))

    def _runner(self, db, dispatch):
        class Runtime:
            def dispatch(self, agent, prompt, context):
                return {"reply": dispatch()}
        return Runtime()

    def test_retries_transient_generation_failure_then_succeeds(self):
        from agents.base import _GENERATION_FAILED_REPLY

        with tempfile.TemporaryDirectory() as directory:
            db = Database(path=str(Path(directory) / "retry.db"), tenant_id="t1")
            self._seed(db)
            calls = {"n": 0}

            def dispatch():
                calls["n"] += 1
                if calls["n"] == 1:
                    return _GENERATION_FAILED_REPLY
                return "On Us is the community-first space for Black Bay Area creatives."

            with patch("core.project_runner.build_runtime", return_value=self._runner(db, dispatch)):
                ProjectRunner(db, "t1", "u1").run("p1")
            self.assertGreater(calls["n"], 1, "transient failure should be retried")
            row = db.query("SELECT status, output FROM agent_tasks WHERE id='a'")[0]
            self.assertEqual(row["status"], "done")
            self.assertNotIn("couldn't reach", row["output"])

    def test_persistent_failure_marks_task_and_project_failed(self):
        from agents.base import _GENERATION_FAILED_REPLY

        with patch.dict("os.environ", {"PAT_TASK_RETRIES": "1"}):
            with tempfile.TemporaryDirectory() as directory:
                db = Database(path=str(Path(directory) / "fail.db"), tenant_id="t1")
                self._seed(db)

                def dispatch():
                    return _GENERATION_FAILED_REPLY

                with patch("core.project_runner.build_runtime", return_value=self._runner(db, dispatch)):
                    with self.assertRaises(ValueError):
                        ProjectRunner(db, "t1", "u1").run("p1")
                task = db.query("SELECT status, output FROM agent_tasks WHERE id='a'")[0]
                self.assertEqual(task["status"], "failed")
                proj = db.query("SELECT status FROM agent_projects WHERE id='p1'")[0]
                self.assertEqual(proj["status"], "failed")


if __name__ == "__main__":
    unittest.main()
