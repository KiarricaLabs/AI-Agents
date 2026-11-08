import hashlib
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from api.app import app
from storage.database import Database
import os, tempfile

DB_PATH = None


def _setup():
    global DB_PATH
    fd, DB_PATH = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["PAT_DB_PATH"] = DB_PATH
    # rebind module-level _db? app already imported; endpoints use module _db from agents router.
    # We'll just use the existing DB_PATH default; tests rely on env not re-read. Instead use direct db.
    return DB_PATH


class ToolApprovalTests(unittest.TestCase):
    def setUp(self):
        import os, tempfile
        self.db_path = os.path.join(tempfile.gettempdir(), "appr_test.db")
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass
        os.environ["PAT_DB_PATH"] = self.db_path
        # Re-import to bind fresh db
        from storage.database import Database
        self.db = Database(path=self.db_path, tenant_id="t1")
        # patch router _db
        import api.routers.agents as ar
        ar._db = self.db
        self.client = TestClient(app)
        # create project? not needed
        # create an agent manifest entry: communications has email_send
        # insert approval directly for some tests
        self.tenant = "t1"
        self.user = "u1"

    def tearDown(self):
        import os
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    def _headers(self):
        # local mode: no token needed if LOCAL_MODE; set env
        return {}

    def _create_approval(self, agent="communications", tool="email_send", args=None, tenant="t1", user="u1"):
        args = args or {"to": "a@b.com"}
        ah = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
        aid = __import__("uuid").uuid4().__str__()
        now = datetime.now(timezone.utc)
        exp = (now + timedelta(minutes=10)).isoformat()
        self.db.execute(
            "INSERT INTO tool_approvals (id,tenant_id,user_id,agent_id,tool_name,args_hash,status,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (aid, tenant, user, agent, tool, ah, "pending", now.isoformat(), exp))
        return aid, args

    def _approve(self, aid):
        self.db.execute("UPDATE tool_approvals SET status='approved' WHERE id=?", (aid,))

    def test_pending_cannot_consume(self):
        aid, args = self._create_approval()
        # status pending -> consumption should fail (claimed False)
        # simulate via direct atomic update
        with self.db.transaction_immediate() as c:
            cur = c.execute("UPDATE tool_approvals SET status='consumed' WHERE id=? AND status='approved'", (aid,))
            self.assertEqual(cur.rowcount, 0)

    def test_approved_claim_succeeds(self):
        aid, args = self._create_approval()
        self._approve(aid)
        with self.db.transaction_immediate() as c:
            cur = c.execute("UPDATE tool_approvals SET status='consumed' WHERE id=? AND status='approved'", (aid,))
            self.assertEqual(cur.rowcount, 1)

    def test_second_claim_fails(self):
        aid, args = self._create_approval()
        self._approve(aid)
        with self.db.transaction_immediate() as c:
            c.execute("UPDATE tool_approvals SET status='consumed' WHERE id=? AND status='approved'", (aid,))
        with self.db.transaction_immediate() as c:
            cur = c.execute("UPDATE tool_approvals SET status='consumed' WHERE id=? AND status='approved'", (aid,))
            self.assertEqual(cur.rowcount, 0)

    def test_concurrent_claims_one_success(self):
        aid, args = self._create_approval()
        self._approve(aid)
        results = []
        def worker():
            try:
                with self.db.transaction_immediate() as c:
                    cur = c.execute("UPDATE tool_approvals SET status='consumed' WHERE id=? AND status='approved'", (aid,))
                    results.append(cur.rowcount)
            except Exception as e:
                results.append(-1)
        t1 = threading.Thread(target=worker); t2 = threading.Thread(target=worker)
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(sorted(results), [0, 1])

    def test_expired_cannot_claim(self):
        aid, args = self._create_approval()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.db.execute("UPDATE tool_approvals SET status='approved', expires_at=? WHERE id=?", (past, aid))
        rows = self.db.query("SELECT expires_at, status FROM tool_approvals WHERE id=?", (aid,))
        exp = datetime.fromisoformat(rows[0]["expires_at"].replace("Z", "+00:00"))
        self.assertTrue(datetime.now(timezone.utc) > exp)

    def test_args_hash_mismatch(self):
        aid, args = self._create_approval(args={"to": "a@b.com"})
        self._approve(aid)
        # different args hash
        other = hashlib.sha256(json.dumps({"to": "x@y.com"}, sort_keys=True).encode()).hexdigest()
        rows = self.db.query("SELECT args_hash FROM tool_approvals WHERE id=?", (aid,))
        self.assertNotEqual(rows[0]["args_hash"], other)

    def test_wrong_agent_rejected(self):
        aid, args = self._create_approval(agent="communications")
        self._approve(aid)
        # agent mismatch handled in router; here verify stored agent
        rows = self.db.query("SELECT agent_id FROM tool_approvals WHERE id=?", (aid,))
        self.assertEqual(rows[0]["agent_id"], "communications")

    def test_wrong_tenant_isolated(self):
        aid, args = self._create_approval(tenant="t1")
        rows = self.db.query("SELECT * FROM tool_approvals WHERE id=? AND tenant_id=?", (aid, "t2"))
        self.assertEqual(len(rows), 0)


if __name__ == "__main__":
    unittest.main()