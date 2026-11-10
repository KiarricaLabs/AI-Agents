"""V1.3.1 — LLM streaming interface tests (mocked, no live Ollama)."""
import io
import json
import socket
import unittest
from unittest.mock import patch, MagicMock

from core.llm_client import LLMClient
from core.model_router import ModelRouter


def _ndjson(lines):
    return "".join(json.dumps(l) + "\n" for l in lines).encode()


class TestLLMClientStream(unittest.TestCase):
    def _mock_urlopen(self, data, side_effect=None):
        cm = MagicMock()
        resp = MagicMock()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.__iter__ = MagicMock(return_value=iter(data.splitlines(keepends=True)))
        if side_effect:
            cm.side_effect = side_effect
        else:
            cm.return_value = resp
        return cm, resp

    def test_multi_chunk_stream(self):
        payload = _ndjson([
            {"response": "Hello", "done": False},
            {"response": " world", "done": True},
        ])
        cm, resp = self._mock_urlopen(payload)
        with patch("urllib.request.urlopen", cm):
            client = LLMClient(provider="ollama", model="m", base_url="http://x")
            chunks = list(client.complete_stream("hi", system="sys"))
        self.assertEqual(chunks, ["Hello", " world"])
        resp.__exit__.assert_called()

    def test_empty_final_response(self):
        payload = _ndjson([{"response": "", "done": True}])
        cm, resp = self._mock_urlopen(payload)
        with patch("urllib.request.urlopen", cm):
            client = LLMClient(provider="ollama", model="m", base_url="http://x")
            chunks = list(client.complete_stream("hi"))
        self.assertEqual(chunks, [])

    def test_malformed_ndjson_skipped(self):
        raw = b'{"response": "ok", "done": false}\nnot json\n{"response": "!", "done": true}\n'
        cm, resp = self._mock_urlopen(raw)
        with patch("urllib.request.urlopen", cm):
            client = LLMClient(provider="ollama", model="m", base_url="http://x")
            chunks = list(client.complete_stream("hi"))
        self.assertEqual(chunks, ["ok", "!"])

    def test_http_error_propagates(self):
        import urllib.error
        cm = MagicMock()
        cm.side_effect = urllib.error.HTTPError("u", 500, "err", {}, None)
        with patch("urllib.request.urlopen", cm):
            client = LLMClient(provider="ollama", model="m", base_url="http://x")
            with self.assertRaises(Exception):
                list(client.complete_stream("hi"))

    def test_connection_error_propagates(self):
        cm = MagicMock()
        cm.side_effect = ConnectionError("refused")
        with patch("urllib.request.urlopen", cm):
            client = LLMClient(provider="ollama", model="m", base_url="http://x")
            with self.assertRaises(ConnectionError):
                list(client.complete_stream("hi"))

    def test_timeout_propagates(self):
        cm = MagicMock()
        cm.side_effect = socket.timeout("timed out")
        with patch("urllib.request.urlopen", cm):
            client = LLMClient(provider="ollama", model="m", base_url="http://x")
            with self.assertRaises(Exception):
                list(client.complete_stream("hi"))

    def test_generator_closure_closes_response(self):
        payload = _ndjson([
            {"response": "a", "done": False},
            {"response": "b", "done": True},
        ])
        cm, resp = self._mock_urlopen(payload)
        with patch("urllib.request.urlopen", cm):
            client = LLMClient(provider="ollama", model="m", base_url="http://x")
            gen = client.complete_stream("hi")
            first = next(gen)
            self.assertEqual(first, "a")
            gen.close()
        resp.__exit__.assert_called()

    def test_error_field_raises(self):
        payload = _ndjson([{"error": "boom", "done": True}])
        cm, resp = self._mock_urlopen(payload)
        with patch("urllib.request.urlopen", cm):
            client = LLMClient(provider="ollama", model="m", base_url="http://x")
            with self.assertRaises(RuntimeError):
                list(client.complete_stream("hi"))

    def test_no_api_key_cloud_raises(self):
        client = LLMClient(provider="openai", model="gpt-4", api_key=None)
        with self.assertRaises(RuntimeError):
            list(client.complete_stream("hi"))


class TestModelRouterStream(unittest.TestCase):
    def test_forwards_chunks_and_model(self):
        router = ModelRouter(retries=1)
        with patch.object(router, "_resolve", return_value=("ollama", "llama3.1")):
            with patch("core.llm_client.LLMClient.complete_stream", return_value=iter(["x", "y"])):
                chunks = list(router.complete_stream("tutor", "hi", model_spec={"provider": "ollama", "model": "llama3.1"}))
        self.assertEqual(chunks, ["x", "y"])

    def test_non_ollama_raises(self):
        router = ModelRouter(retries=1)
        with self.assertRaises(RuntimeError):
            list(router.complete_stream("tutor", "hi", model_spec={"provider": "openai", "model": "gpt-4"}))

    def test_mock_mode(self):
        import os
        os.environ["PAT_MOCK_AGENTS"] = "1"
        try:
            router = ModelRouter()
            chunks = list(router.complete_stream("tutor", "hi"))
            self.assertEqual(len(chunks), 1)
        finally:
            os.environ.pop("PAT_MOCK_AGENTS", None)


if __name__ == "__main__":
    unittest.main()
