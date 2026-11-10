"""V1.6.10.1.x — agent_run_history persistence tests."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token
from core.model_router import ModelResult
from storage.database import Database
from config.settings import DB_PATH

_GOOD = ModelResult("hello from test", "ollama", "llama3.1", "local:ollama:llama3.1")


class _FakeRouter:
    def _resolve(self, spec=None):
        return ("ollama", "llama3.1")

    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        return _GOOD

    def complete_stream(self, agent_id, prompt, system="", model_spec=None, context=None, **kw):
        yield "hello "
        yield "from test"


class _FailRouter(_FakeRouter):
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        raise RuntimeError("boom")

    def complete_stream(self, agent_id, prompt, system="", model_spec=None, context=None, **kw):
        raise RuntimeError("boom")
        yield


def _rows_for(tenant="t1", user="u1"):
    db = Database(path=DB_PATH, tenant_id=tenant)
    return db.query(
        "SELECT * FROM agent_run_history WHERE tenant_id=? AND user_id=?",
        (tenant, user),
    )


class TestAgentRunHistoryPersistence(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.tok = issue_token("u1", "t1", "user", 3600)
        # clean
        db = Database(path=DB_PATH, tenant_id="t1")
        db.execute("DELETE FROM agent_run_history WHERE tenant_id='t1' AND user_id='u1'")

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_nonstream_success(self, _m):
        r = self.client.post("/agents/tutor/run", json={"task": "hi"}, headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        rows = _rows_for()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "completed")

    @patch("core.runtime.ModelRouter", return_value=_FailRouter())
    def test_nonstream_failure(self, _m):
        r = self.client.post("/agents/tutor/run", json={"task": "hi"}, headers={"x-token": self.tok})
        self.assertNotEqual(r.status_code, 200)
        rows = _rows_for()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "failed")

    def test_nonstream_rejected_unknown_agent(self):
        r = self.client.post("/agents/nope/run", json={"task": "hi"}, headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 404)
        rows = _rows_for()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "rejected")

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_stream_success(self, _m):
        r = self.client.post("/agents/tutor/run/stream", json={"task": "hi"}, headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        _ = r.text
        rows = _rows_for()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "completed")

    @patch("core.runtime.ModelRouter", return_value=_FailRouter())
    def test_stream_failure(self, _m):
        r = self.client.post("/agents/tutor/run/stream", json={"task": "hi"}, headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        _ = r.text
        rows = _rows_for()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "failed")

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_task_summary_truncation(self, _m):
        long_task = "a" * 300
        r = self.client.post("/agents/tutor/run", json={"task": long_task}, headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        rows = _rows_for()
        self.assertTrue(len(rows[0]["task_summary"]) <= 200)




class TestAgentRunHistoryHardening(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.tok = issue_token("u1", "t1", "user", 3600)
        db = Database(path=DB_PATH, tenant_id="t1")
        db.execute("DELETE FROM agent_run_history WHERE tenant_id='t1' AND user_id='u1'")

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_thread_attribution_from_result(self, _m):
        r = self.client.post("/agents/tutor/run", json={"task": "hi", "thread_id": "thr-1"}, headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        db = Database(path=DB_PATH, tenant_id="t1")
        rows = db.query("SELECT * FROM agent_run_history WHERE tenant_id='t1' AND user_id='u1'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["thread_id"], "thr-1")

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_no_raw_response_persisted(self, _m):
        r = self.client.post("/agents/tutor/run", json={"task": "secret task"}, headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        db = Database(path=DB_PATH, tenant_id="t1")
        rows = db.query("SELECT * FROM agent_run_history WHERE tenant_id='t1' AND user_id='u1'")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("hello from test", str(rows[0]))
        self.assertLessEqual(len(rows[0]["task_summary"] or ""), 200)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_timestamps_ordered(self, _m):
        r = self.client.post("/agents/tutor/run", json={"task": "hi"}, headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        db = Database(path=DB_PATH, tenant_id="t1")
        rows = db.query("SELECT * FROM agent_run_history WHERE tenant_id='t1' AND user_id='u1'")
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(rows[0]["created_at"], rows[0]["finished_at"])


if __name__ == "__main__":
    unittest.main()
