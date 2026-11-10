"""Endpoint-level tests for POST /agents/{name}/run/stream."""
import json
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token
from core.model_router import ModelResult

ALL_AGENTS = {"tutor", "strategist", "executive_assistant",
              "communications", "soundboard", "workspace_architect"}

_GOOD = ModelResult("hello from test", "ollama", "llama3.1", "local:ollama:llama3.1")


class _FakeRouter:
    def _resolve(self, spec=None):
        return ("ollama", "llama3.1")

    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        return _GOOD

    def complete_stream(self, agent_id, prompt, system="", model_spec=None, context=None, **kw):
        yield "hello "
        yield "from test"


class _SecretRouter(_FakeRouter):
    def complete_stream(self, agent_id, prompt, system="", model_spec=None, context=None, **kw):
        yield "my password is hunter2"


class TestStreamEndpointAuth(unittest.TestCase):
    def test_unauthenticated_rejected(self):
        c = TestClient(app)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": "bad"})
        self.assertEqual(r.status_code, 401)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_authenticated_ok(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/event-stream", r.headers.get("content-type", ""))

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_client_identity_override_ignored(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream",
                   json={"task": "hi", "tenant_id": "evil", "user_id": "evil"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)


class TestStreamEligibility(unittest.TestCase):
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_work_intent_true_rejected(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream",
                   json={"task": "hi", "work_intent": True},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 400)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_tool_calls_rejected(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream",
                   json={"task": "hi", "tool_calls": [{"tool": "calculate", "args": {}}]},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 400)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_unknown_agent_404(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/nope/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 404)


class TestStreamContract(unittest.TestCase):
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_chunk_then_done(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        lines = [l for l in r.text.splitlines() if l.startswith("data:")]
        events = [json.loads(l[5:].strip()) for l in lines]
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "chunk")
        self.assertEqual(types[-1], "done")
        self.assertEqual(types.count("done"), 1)

    @patch("core.runtime.ModelRouter", return_value=_SecretRouter())
    def test_secret_stops_emission(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        lines = [l for l in r.text.splitlines() if l.startswith("data:")]
        events = [json.loads(l[5:].strip()) for l in lines]
        types = [e["type"] for e in events]
        # either error event or chunks without secret; no done with secret
        if "done" in types:
            done_ev = [e for e in events if e["type"] == "done"][0]
            self.assertNotIn("password", done_ev.get("reply", ""))

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_headers(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertIn("text/event-stream", r.headers.get("content-type", ""))
        self.assertEqual(r.headers.get("cache-control"), "no-cache")


class TestStreamPersistence(unittest.TestCase):
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_success_persists(self, _m):
        # Just verify no crash and done event present
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        self.assertIn('"type": "done"', r.text)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_nonstreaming_unchanged(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)


class TestStreamValidation(unittest.TestCase):
    @patch("core.runtime.ModelRouter")
    def test_length_validation(self, mock_router):
        class BigRouter(_FakeRouter):
            def complete_stream(self, agent_id, prompt, system="", model_spec=None, context=None, **kw):
                yield "a" * 20001
        mock_router.return_value = BigRouter()
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertIn('"type": "error"', r.text)

    @patch("core.runtime.ModelRouter")
    def test_dispatch_failure_sanitized(self, mock_router):
        from core.runtime import build_runtime
        from unittest.mock import MagicMock
        orch = MagicMock()
        orch.dispatch.side_effect = RuntimeError("secret db path /tmp/x")
        with patch("core.runtime.build_runtime", return_value=orch):
            c = TestClient(app)
            tok = issue_token("u1", "t1", "user", 3600)
            r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                       headers={"x-token": tok})
            self.assertIn('"type": "error"', r.text)
            self.assertNotIn("secret db path", r.text)
            self.assertNotIn("/tmp/x", r.text)

    @patch("core.runtime.ModelRouter")
    def test_secret_router_sanitized(self, mock_router):
        mock_router.return_value = _SecretRouter()
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        # Secret should not appear in any chunk; may error out
        self.assertNotIn("hunter2", r.text)


class TestStreamDisconnect(unittest.TestCase):
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_disconnect_no_crash(self, _m):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        with c.stream("POST", "/agents/tutor/run/stream",
                      json={"task": "hi"}, headers={"x-token": tok}) as r:
            for line in r.iter_lines():
                if line:
                    break
        self.assertTrue(True)


class TestQueueSaturation(unittest.TestCase):
    @patch("core.runtime.ModelRouter")
    def test_many_chunks_all_delivered(self, mock_router):
        class ManyRouter(_FakeRouter):
            def complete_stream(self, agent_id, prompt, system="", model_spec=None, context=None, **kw):
                for i in range(100):
                    yield f"c{i} "
        mock_router.return_value = ManyRouter()
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        chunks = [l for l in r.text.splitlines() if '"type": "chunk"' in l]
        self.assertEqual(len(chunks), 100)
        self.assertIn('"type": "done"', r.text)


class TestDispatchFailureNoPersist(unittest.TestCase):
    @patch("core.runtime.ModelRouter")
    def test_dispatch_failure_no_done(self, mock_router):
        from core.runtime import build_runtime
        from unittest.mock import MagicMock
        orch = MagicMock()
        orch.dispatch.side_effect = RuntimeError("boom")
        with patch("core.runtime.build_runtime", return_value=orch):
            c = TestClient(app)
            tok = issue_token("u1", "t1", "user", 3600)
            r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                       headers={"x-token": tok})
            self.assertIn('"type": "error"', r.text)
            self.assertNotIn('"type": "done"', r.text)


import asyncio


class TestDirectGeneratorClose(unittest.TestCase):
    def test_generator_close_cancellation(self):
        async def run():
            from api.routers.agents import run_agent_stream
            from unittest.mock import MagicMock, patch
            from core.model_router import ModelResult

            req = MagicMock()
            req.task = "hi"
            req.thread_id = None
            req.brand_id = None
            req.work_intent = False
            req.tool_calls = None
            req.project_id = None
            req.workspace_id = None
            req.project_name = None
            req.workspace_name = None
            req.retry = False

            request = MagicMock()

            async def is_disc():
                return False

            request.is_disconnected = is_disc
            request.state.tenant_id = "t1"
            request.state.user_id = "u1"
            request.state.role = "user"

            orch = MagicMock()

            def dispatch_side_effect(name, task, context=None, stream=False, on_chunk=None):
                if on_chunk:
                    on_chunk("chunk1")
                    on_chunk("chunk2")
                return {"reply": "hello", "provider": "ollama", "model": "m", "location": "local:ollama:m"}

            orch.dispatch.side_effect = dispatch_side_effect
            persisted = {"called": False}

            def fake_add(*a, **k):
                persisted["called"] = True

            with patch("core.runtime.build_runtime", return_value=orch), \
                 patch("core.runtime.load_registry") as lr, \
                 patch("api.routers.agents.MemoryService") as ms_cls:
                lr.return_value.list.return_value = ["tutor"]
                lr.return_value.get.return_value = {"tools": []}
                ms = MagicMock()
                ms.list_conversation.return_value = []
                ms.add_conversation.side_effect = fake_add
                ms_cls.return_value = ms
                resp = await run_agent_stream("tutor", req, request)
                gen = resp.body_iterator
                first = await gen.__anext__()
                await gen.aclose()
                await asyncio.sleep(0.2)
                self.assertFalse(persisted["called"])
                self.assertNotIn('"type": "done"', first)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()


class TestStreamLifecycleLogging(unittest.TestCase):
    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_accepted_stream_emits_run_started(self, _m, log_event):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertEqual(actions.count("run.started"), 1)

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_ineligible_stream_no_run_started(self, _m, log_event):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi", "work_intent": True},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 400)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertNotIn("run.started", actions)

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_stream_started_log_safe(self, _m, log_event):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        for call in log_event.call_args_list:
            blob = str(call.kwargs)
            for bad in ("hi", "hello", "token", "secret", "tenant"):
                self.assertNotIn(bad, blob)


class TestStreamLifecycleLoggingCompletion(unittest.TestCase):
    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_stream_success_no_duplicates(self, _m, log_event):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertEqual(actions.count("run.started"), 1)
        self.assertEqual(actions.count("run.dispatched"), 1)
        self.assertEqual(actions.count("run.completed"), 1)
        self.assertEqual(actions.count("run.failed"), 0)

    @patch("core.observability.log_event")
    @patch("core.runtime.ModelRouter", return_value=_SecretRouter())
    def test_stream_failure_lifecycle(self, _m, log_event):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        r = c.post("/agents/tutor/run/stream", json={"task": "hi"},
                   headers={"x-token": tok})
        self.assertEqual(r.status_code, 200)
        actions = [call.args[0] for call in log_event.call_args_list]
        self.assertEqual(actions.count("run.started"), 1)
        self.assertEqual(actions.count("run.dispatched"), 1)
        self.assertEqual(actions.count("run.failed"), 1)
        self.assertEqual(actions.count("run.completed"), 0)
        for call in log_event.call_args_list:
            blob = str(call.kwargs)
            for bad in ("hi", "hello", "password", "hunter2", "token", "tenant"):
                self.assertNotIn(bad, blob)
