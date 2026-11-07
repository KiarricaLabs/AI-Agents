import unittest
from unittest.mock import patch, MagicMock
from integrations.email import EmailIntegration


class EmailIntegrationTests(unittest.TestCase):
    def _creds(self):
        return {"host": "smtp.example.com", "port": 587, "username": "u",
                "password": "secret", "sender": "u@example.com", "use_starttls": True, "timeout": 5}

    def test_unapproved_blocked(self):
        e = EmailIntegration()
        e.connect(self._creds())
        r = e.execute("send", {"to": "a@b.com", "subject": "s", "body": "b"})
        self.assertTrue(r.get("gated"))

    def test_approved_sends(self):
        e = EmailIntegration()
        e.connect(self._creds())
        with patch("smtplib.SMTP") as m:
            srv = MagicMock()
            m.return_value.__enter__.return_value = srv
            r = e.execute("send", {"to": "a@b.com", "subject": "s", "body": "b"}, approved=True)
            self.assertTrue(r["ok"])
            srv.send_message.assert_called_once()

    def test_invalid_recipient_rejected(self):
        e = EmailIntegration()
        e.connect(self._creds())
        r = e.execute("send", {"to": "notanemail", "subject": "s", "body": "b"}, approved=True)
        self.assertFalse(r["ok"])

    def test_missing_creds_fail(self):
        e = EmailIntegration()
        e.connect({})
        r = e.execute("send", {"to": "a@b.com", "subject": "s", "body": "b"}, approved=True)
        self.assertFalse(r["ok"])

    def test_auth_failure_handled(self):
        import smtplib
        e = EmailIntegration()
        e.connect(self._creds())
        with patch("smtplib.SMTP") as m:
            srv = MagicMock()
            m.return_value.__enter__.return_value = srv
            srv.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth fail")
            r = e.execute("send", {"to": "a@b.com", "subject": "s", "body": "b"}, approved=True)
            self.assertFalse(r["ok"])
            self.assertNotIn("secret", str(r))

    def test_starttls_used(self):
        e = EmailIntegration()
        e.connect(self._creds())
        with patch("smtplib.SMTP") as m:
            srv = MagicMock()
            m.return_value.__enter__.return_value = srv
            e.execute("send", {"to": "a@b.com", "subject": "s", "body": "b"}, approved=True)
            srv.starttls.assert_called_once()

    def test_health(self):
        e = EmailIntegration()
        e.connect(self._creds())
        self.assertTrue(e.health()["connected"])


if __name__ == "__main__":
    unittest.main()