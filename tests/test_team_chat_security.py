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

    def test_extract_is_human_gated_and_non_human_gets_403(self):
        t, u = ("fg_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "project", "message": "project: Launch an app",
        }, headers=self._h(u, t, role="agent"))
        self.assertEqual(r.status_code, 403)

    def test_extract_persists_nothing(self):
        t, u = ("fg_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/work/extract", json={
            "kind": "project", "message": "project: Launch an app",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["persisted"], False)
        # no proposal row was created by extraction alone
        lst = self.client.get("/work/proposals", headers=self._h(u, t)).json()
        self.assertEqual(lst.get("items", []), [])

    def test_propose_stays_proposed_and_never_auto_executes(self):
        t, u = ("fg_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        ws = self.client.post("/work/proposals/workspace", json={"name": "SafeCo"}, headers=self._h(u, t))
        self.assertEqual(ws.status_code, 200, ws.text)
        pid = ws.json()["proposal_id"]
        detail = self.client.get(f"/work/proposals/{pid}", headers=self._h(u, t)).json()
        self.assertEqual(detail["status"], "proposed")
        # Not executed: an unapproved proposal must not create a workspace.
        lst = self.client.get("/workspaces", headers=self._h(u, t)).json()["items"]
        self.assertFalse(any(w["name"] == "SafeCo" for w in lst))

    def test_progress_record_is_human_gated(self):
        t, u = ("fg_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/team/progress/record", json={
            "thread_id": "thr-1", "agent_id": "strategist", "status": "working",
        }, headers=self._h(u, t, role="agent"))
        self.assertEqual(r.status_code, 403)

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
