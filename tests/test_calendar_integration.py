import json
import unittest
from unittest.mock import patch, MagicMock
from integrations.calendar import CalendarIntegration


class CalendarIntegrationTests(unittest.TestCase):
    def _creds(self):
        return {"access_token": "tok", "calendar_id": "primary", "timezone": "UTC"}

    def test_unapproved_blocked(self):
        c = CalendarIntegration()
        c.connect(self._creds())
        r = c.execute("create_event", {"title": "t", "start": "2024-01-01T10:00:00", "end": "2024-01-01T11:00:00"})
        self.assertTrue(r.get("gated"))

    def test_missing_title_rejected(self):
        c = CalendarIntegration()
        c.connect(self._creds())
        r = c.execute("create_event", {"start": "2024-01-01T10:00:00", "end": "2024-01-01T11:00:00"}, approved=True)
        self.assertFalse(r["ok"])

    def test_missing_creds_fail(self):
        c = CalendarIntegration()
        c.connect({})
        r = c.execute("create_event", {"title": "t", "start": "s", "end": "e"}, approved=True)
        self.assertFalse(r["ok"])

    def test_approved_calls_api(self):
        c = CalendarIntegration()
        c.connect(self._creds())
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": "evt1"}).encode()
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = c.execute("create_event", {"title": "t", "start": "2024-01-01T10:00:00", "end": "2024-01-01T11:00:00"}, approved=True)
            self.assertTrue(r["ok"])
            self.assertEqual(r["event"]["id"], "evt1")

    def test_health(self):
        c = CalendarIntegration()
        c.connect(self._creds())
        self.assertTrue(c.health()["connected"])

    def test_token_refresh(self):
        c = CalendarIntegration()
        creds = {"refresh_token": "rt", "client_id": "cid", "client_secret": "cs", "calendar_id": "primary"}
        c.connect(creds)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"access_token": "newtok"}).encode()
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            tok = c._refresh_token(creds)
            self.assertEqual(tok, "newtok")


if __name__ == "__main__":
    unittest.main()