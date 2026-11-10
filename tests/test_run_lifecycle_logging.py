import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token


class _FakeRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        from core.model_router import ModelResult
        return ModelResult("hello", "ollama", "llama3.1", "local:ollama:llama3.1")


class TestRunLifecycleLogging(unittest.TestCase):
    def _client(self):
        return TestClient(app)

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_success_events(self, _m, log_event):
        c = self._client()
        r = c.post("/agents/tutor/run", json={"task": "explain gravity"})
        self.assertEqual(r.status_code, 200)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertIn("run.started", actions)
        self.assertIn("run.dispatched", actions)
        self.assertIn("run.completed", actions)
        self.assertNotIn("run.failed", actions)
        self.assertNotIn("run.rejected", actions)

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_rejected_unknown_agent(self, _m, log_event):
        c = self._client()
        r = c.post("/agents/nope/run", json={"task": "x"})
        self.assertEqual(r.status_code, 404)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertIn("run.rejected", actions)
        self.assertNotIn("run.dispatched", actions)
        self.assertNotIn("run.completed", actions)

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_empty_task_rejected(self, _m, log_event):
        c = self._client()
        r = c.post("/agents/tutor/run", json={"task": ""})
        self.assertEqual(r.status_code, 422)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertIn("run.rejected", actions)


class _SecretRouter:
    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        from core.model_router import ModelResult
        return ModelResult("my password is hunter2", "ollama", "llama3.1", "local:ollama:llama3.1")


class TestRunLifecycleLoggingExtra(unittest.TestCase):
    def _client(self):
        return TestClient(app)

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_SecretRouter())
    def test_failure_event(self, _m, log_event):
        c = self._client()
        r = c.post("/agents/tutor/run", json={"task": "explain gravity"})
        self.assertEqual(r.status_code, 422)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertIn("run.started", actions)
        self.assertIn("run.dispatched", actions)
        self.assertIn("run.failed", actions)
        self.assertNotIn("run.completed", actions)
        failed_calls = [cc for cc in log_event.call_args_list if cc.args and cc.args[0] == "run.failed"]
        self.assertTrue(failed_calls)
        fields = failed_calls[-1].kwargs
        self.assertNotIn("password", str(fields))
        self.assertNotIn("hunter2", str(fields))

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_sensitive_exclusion_and_duplicates(self, _m, log_event):
        c = self._client()
        r = c.post("/agents/tutor/run", json={"task": "explain gravity"})
        self.assertEqual(r.status_code, 200)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertEqual(actions.count("run.started"), 1)
        self.assertEqual(actions.count("run.dispatched"), 1)
        self.assertEqual(actions.count("run.completed"), 1)
        for call in log_event.call_args_list:
            blob = str(call.kwargs)
            for bad in ("explain gravity", "hello", "password", "token", "secret", "api_key", "tenant"):
                self.assertNotIn(bad, blob)

    @patch("core.observability.log_event")
    def test_rejected_no_dispatched(self, log_event):
        c = self._client()
        r = c.post("/agents/nope/run", json={"task": "x"})
        self.assertEqual(r.status_code, 404)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertIn("run.rejected", actions)
        self.assertNotIn("run.dispatched", actions)


class TestRetryLogging(unittest.TestCase):
    def _client(self):
        return TestClient(app)

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_retry_requested_emitted(self, _m, log_event):
        c = self._client()
        r = c.post("/agents/tutor/run", json={"task": "explain gravity", "retry": True})
        self.assertEqual(r.status_code, 200)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertEqual(actions.count("run.retry_requested"), 1)
        rr = [cc for cc in log_event.call_args_list if cc.args and cc.args[0] == "run.retry_requested"][0]
        self.assertEqual(rr.kwargs.get("agent_id"), "tutor")
        # no sensitive fields
        self.assertNotIn("task", str(rr.kwargs))

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_no_retry_no_event(self, _m, log_event):
        c = self._client()
        r = c.post("/agents/tutor/run", json={"task": "explain gravity"})
        self.assertEqual(r.status_code, 200)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertNotIn("run.retry_requested", actions)


if __name__ == "__main__":
    unittest.main()
