"""Security-hardening tests for environment-driven auth secret resolution.

Covers fail-closed startup validation (missing / placeholder / weak / valid),
token round-trips, sign/verify correctness across differing secrets, and
secret-leakage guards. Uses a dedicated test secret so it never relies on the
local-mode development fallback.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.auth as auth
from core.auth import (
    _secret_is_insecure,
    resolve_signing_secret,
    validate_auth_secret,
    issue_token,
    verify_token,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Clearly-valid 64-hex test secrets (distinct from the suite default in tests/__init__.py).
VALID = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"


class TestSecretValidation(unittest.TestCase):
    def test_empty_is_insecure(self):
        self.assertTrue(_secret_is_insecure(""))
        self.assertTrue(_secret_is_insecure("   "))

    def test_known_placeholders_rejected(self):
        for s in auth._PLACEHOLDER_SECRETS:
            self.assertTrue(_secret_is_insecure(s), s)

    def test_short_secret_rejected(self):
        self.assertTrue(_secret_is_insecure("a" * 31))

    def test_low_variety_secret_rejected(self):
        self.assertTrue(_secret_is_insecure("a" * 64))

    def test_valid_secret_accepted(self):
        self.assertFalse(_secret_is_insecure(VALID))


class TestSecretResolution(unittest.TestCase):
    def setUp(self):
        auth._warned_fallback = False

    def tearDown(self):
        auth._warned_fallback = False

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("core.auth.LOCAL_MODE", False)
    def test_prod_missing_secret_fails_closed(self):
        with self.assertRaises(RuntimeError):
            resolve_signing_secret()

    @mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": VALID}, clear=True)
    @mock.patch("core.auth.LOCAL_MODE", False)
    def test_prod_valid_secret_ok(self):
        self.assertEqual(resolve_signing_secret(), VALID)
        self.assertEqual(validate_auth_secret(), VALID)

    @mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": "change-me-in-prod"}, clear=True)
    @mock.patch("core.auth.LOCAL_MODE", False)
    def test_prod_placeholder_secret_fails_closed(self):
        with self.assertRaises(RuntimeError):
            resolve_signing_secret()

    @mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": "tooshort"}, clear=True)
    @mock.patch("core.auth.LOCAL_MODE", False)
    def test_prod_weak_secret_fails_closed(self):
        with self.assertRaises(RuntimeError):
            resolve_signing_secret()

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("core.auth.LOCAL_MODE", True)
    def test_local_missing_secret_uses_labeled_fallback(self):
        with self.assertLogs("personal_ai_team.auth", level="WARNING") as cm:
            secret = resolve_signing_secret()
        self.assertEqual(secret, auth._DEV_FALLBACK_SECRET)
        joined = " ".join(cm.output)
        # The warning must never reveal the fallback value.
        self.assertNotIn(auth._DEV_FALLBACK_SECRET, joined)

    @mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": VALID}, clear=True)
    @mock.patch("core.auth.LOCAL_MODE", True)
    def test_local_explicit_secret_wins_over_fallback(self):
        self.assertEqual(resolve_signing_secret(), VALID)


class TestTokenRoundTrip(unittest.TestCase):
    def setUp(self):
        auth._warned_fallback = False

    def tearDown(self):
        auth._warned_fallback = False

    @mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": VALID}, clear=True)
    def test_issue_and_verify_roundtrip(self):
        tok = issue_token("u1", "t1", "admin")
        claims = verify_token(tok)
        self.assertEqual(claims["sub"], "u1")
        self.assertEqual(claims["tenant"], "t1")
        self.assertEqual(claims["role"], "admin")

    @mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": VALID}, clear=True)
    def test_token_from_different_secret_is_rejected(self):
        tok = issue_token("u1", "t1")
        with mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": OTHER}):
            self.assertIsNone(verify_token(tok))


class TestSecretLeakage(unittest.TestCase):
    def setUp(self):
        auth._warned_fallback = False

    def tearDown(self):
        auth._warned_fallback = False

    @mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": "change-me-in-prod"}, clear=True)
    @mock.patch("core.auth.LOCAL_MODE", False)
    def test_error_message_does_not_leak_configured_secret(self):
        with self.assertRaises(RuntimeError) as ctx:
            resolve_signing_secret()
        self.assertNotIn("change-me-in-prod", str(ctx.exception))

    def test_api_401_does_not_leak_secret(self):
        from fastapi.testclient import TestClient
        from api.app import app

        client = TestClient(app)
        with mock.patch.dict(os.environ, {"PAT_AUTH_SECRET": VALID}):
            r = client.get("/workspaces", headers={"x-token": "bad.token"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn(VALID, r.text)


class TestAppStartupFailClosed(unittest.TestCase):
    def test_app_import_fails_closed_when_prod_secret_missing(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(db)
        env = dict(os.environ)
        env["PAT_LOCAL_MODE"] = "0"
        env.pop("PAT_AUTH_SECRET", None)
        env["PAT_DB_PATH"] = db
        try:
            proc = subprocess.run(
                [sys.executable, "-c", "import api.app"],
                env=env,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
        finally:
            for suffix in ("", "-wal", "-shm"):
                p = Path(db + suffix)
                if p.exists():
                    p.unlink()
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PAT_AUTH_SECRET", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
