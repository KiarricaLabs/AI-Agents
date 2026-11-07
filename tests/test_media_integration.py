import base64
import json
import unittest
from unittest.mock import patch, MagicMock
from integrations.media import MediaIntegration


class MediaIntegrationTests(unittest.TestCase):
    def _creds(self):
        return {"api_key": "sk-test", "model": "dall-e-3"}

    def test_unapproved_blocked(self):
        m = MediaIntegration()
        m.connect(self._creds())
        r = m.execute("generate", {"prompt": "a cat"})
        self.assertTrue(r.get("gated"))

    def test_missing_prompt_rejected(self):
        m = MediaIntegration()
        m.connect(self._creds())
        r = m.execute("generate", {"prompt": ""}, approved=True)
        self.assertFalse(r["ok"])

    def test_missing_creds_fail(self):
        m = MediaIntegration()
        m.connect({})
        r = m.execute("generate", {"prompt": "a cat"}, approved=True)
        self.assertFalse(r["ok"])

    def test_approved_generates(self):
        m = MediaIntegration()
        m.connect(self._creds())
        b64 = base64.b64encode(b"fakepng").decode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": [{"b64_json": b64}]}).encode()
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = m.execute("generate", {"prompt": "a cat"}, approved=True)
            self.assertTrue(r["ok"])
            self.assertEqual(r["asset"]["b64_length"], len(b64))

    def test_invalid_size_rejected(self):
        m = MediaIntegration()
        m.connect(self._creds())
        r = m.execute("generate", {"prompt": "a cat", "size": "999x999"}, approved=True)
        self.assertFalse(r["ok"])

    def test_provider_error_handled(self):
        import urllib.error
        m = MediaIntegration()
        m.connect(self._creds())
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", 400, "bad", {}, None)):
            r = m.execute("generate", {"prompt": "a cat"}, approved=True)
            self.assertFalse(r["ok"])

    def test_health(self):
        m = MediaIntegration()
        m.connect(self._creds())
        self.assertTrue(m.health()["connected"])

    def test_stores_file_when_output_dir(self):
        import tempfile, os
        d = tempfile.mkdtemp()
        m = MediaIntegration(output_dir=d)
        m.connect(self._creds())
        b64 = base64.b64encode(b"fakepng").decode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": [{"b64_json": b64}]}).encode()
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = m.execute("generate", {"prompt": "a cat"}, approved=True)
            self.assertTrue(r["ok"])
            self.assertTrue(os.path.exists(r["asset"]["path"]))


if __name__ == "__main__":
    unittest.main()