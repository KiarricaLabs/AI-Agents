import os, tempfile, unittest
from storage.database import Database
from core.auth import issue_refresh, rotate_refresh, revoke_refresh, hash_refresh
from core.policy import PolicyEngine
from core.policy_enforcer import PolicyEnforcer
from core.ratelimit import RateLimiter


class TestPhase1(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")

    def tearDown(self):
        try: os.remove(self.path)
        except OSError: pass

    def test_refresh_issue_rotate(self):
        raw, fam = issue_refresh(self.db, "t1", "u1")
        new_raw, status = rotate_refresh(self.db, raw, "t1", "u1")
        self.assertEqual(status, "ok")
        self.assertIsNotNone(new_raw)

    def test_refresh_reuse_detection(self):
        raw, fam = issue_refresh(self.db, "t1", "u1")
        rotate_refresh(self.db, raw, "t1", "u1")  # first rotation
        # reuse old token
        _, status = rotate_refresh(self.db, raw, "t1", "u1")
        self.assertEqual(status, "reuse_detected")

    def test_refresh_revoked(self):
        raw, fam = issue_refresh(self.db, "t1", "u1")
        revoke_refresh(self.db, raw, "t1", "u1")
        _, status = rotate_refresh(self.db, raw, "t1", "u1")
        self.assertEqual(status, "reuse_detected")

    def test_rate_limiter(self):
        rl = RateLimiter(max_calls=2, window=60)
        self.assertTrue(rl.allow("k"))
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_policy_enforcer(self):
        pe = PolicyEngine.from_dict({"rules": [{"subject": "a", "action": "r", "resource": "m", "effect": "allow"}]})
        en = PolicyEnforcer(pe)
        en.check("a", "r", "m")
        with self.assertRaises(PermissionError):
            en.check("b", "r", "m")

    def test_default_deny_missing_policy(self):
        pe = PolicyEngine.from_dict({})
        self.assertFalse(pe.allow("a", "r", "m"))


if __name__ == "__main__":
    unittest.main()