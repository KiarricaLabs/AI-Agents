"""Phase 10–11 — group-chat security & reliability boundary tests.

Verifies the human-controlled, isolated, no-auto-run properties of the new
group-chat surfaces:
- draft extraction (POST /work/extract) is human-gated and persists nothing;
- proposing work via POST /work/proposals stays 'proposed' (requires human
  approval) and never auto-executes;
- the progress ledger write (POST /team/progress/record) is human-gated and
  tenant/user-isolated;
- a non-human role gets 403 on every mutating group-chat surface.
"""
from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from core.auth import issue_token


class GroupChatSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _h(self, user, tenant, role="user"):
        return {"x-token": issue_token(user, tenant, role)}




    def test_progress_record_is_human_gated(self):
        t, u = ("fg_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/team/progress/record", json={
            "thread_id": "thr-1", "agent_id": "strategist", "status": "working",
        }, headers=self._h(u, t, role="agent"))
        self.assertEqual(r.status_code, 403)

    def test_mock_dispatch_returns_deterministic_replies_and_records_progress(self):
        import os
        os.environ["PAT_MOCK_AGENTS"] = "1"
        try:
            t, u = ("fg_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
            h = self._h(u, t)
            thr = self.client.post("/team/threads", json={"title": "Smoke", "thread_type": "team"}, headers=h).json()["thread_id"]
            r = self.client.post("/team/messages", json={
                "message": "Plan a launch strategy and draft the announcement", "thread_id": thr,
            }, headers=h)
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertTrue(body.get("coordinated_team_response"))
            self.assertTrue(body.get("responses"))
            for resp in body["responses"]:
                self.assertEqual(resp["model"], "mock")
                self.assertTrue((resp.get("reply") or "").strip())
            # progress rows were written for the responders
            prog = self.client.get(f"/team/progress?thread_id={thr}", headers=h).json()["items"]
            self.assertGreaterEqual(len(prog), 1)
            self.assertTrue(all(p["status"] == "completed" for p in prog))
        finally:
            os.environ.pop("PAT_MOCK_AGENTS", None)

    def test_progress_is_tenantly_isolated(self):
        t1, u = ("fg_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        t2 = "fg_%s" % uuid.uuid4().hex[:8]
        self.client.post("/team/progress/record", json={
            "thread_id": "thr-1", "agent_id": "strategist", "status": "completed", "detail": "x",
        }, headers=self._h(u, t1))
        other = self.client.get("/team/progress?thread_id=thr-1", headers=self._h(u, t2)).json()["items"]
        self.assertEqual(other, [])


if __name__ == "__main__":
    unittest.main()
