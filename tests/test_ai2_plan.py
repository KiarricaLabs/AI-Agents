"""AI Team 2.0 (T2-A) — plan-as-proposal lifecycle + revision preservation.

Covers, on an isolated DB (never production):
- Propose a coordinated plan -> ONE work_proposals row, no records created.
- Idempotency: duplicate propose returns the reused proposal.
- Revision creates a NEW proposal, version+1, revision_of set, original preserved
  byte-for-byte.
- Reject is terminal and preserved with reason.
- Lineage validation: cannot revise a rejected plan; revision_of must reference
  an owned plan; cross-user / cross-tenant rejection.
- Malformed payload -> rejected cleanly (no partial writes).
- Reuses the existing work_proposals state machine; no plan_proposals table.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from storage.database import Database
from core.work_proposals import WorkProposalService, ProposalNotFound

TENANT = "ai2plans"


def _fresh():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


def _plan(title="Launch On Us", milestones=None, tasks=None):
    return {
        "title": title,
        "description": "coordinated plan",
        "version": 1,
        "milestones": milestones if milestones is not None else
            [{"title": "M1", "order": 1}],
        "tasks": tasks if tasks is not None else
            [{"title": "T1", "goal": "G1", "agent": "communications"}],
        "success_criteria": ["crit"],
        "coordinator_agent": "strategist",
    }


class PlanProposalTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh()
        self.db = Database(path=self.path, tenant_id=TENANT)
        self.svc = WorkProposalService(db=self.db, tenant_id=TENANT, user_id="u1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_propose_creates_one_proposal_no_records(self):
        before_ws = len(self.db.query("SELECT id FROM work_proposals"))
        r = self.svc.propose("plan", "strategist", action="propose", payload=_plan(),
                             idempotency_key="k1")
        self.assertEqual(r["status"], "proposed")
        rows = self.db.query(
            "SELECT id FROM work_proposals WHERE idempotency_key='k1' AND tenant_id=?",
            (TENANT,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(self.db.query("SELECT id FROM work_proposals")), before_ws + 1)
        # No workspace/project/goal/assignment/episode created
        self.assertEqual(len(self.db.query("SELECT id FROM workspaces")), 0)
        self.assertEqual(len(self.db.query("SELECT id FROM goals")), 0)
        self.assertEqual(len(self.db.query("SELECT id FROM assignments")), 0)

    def test_idempotent_duplicate_propose(self):
        r1 = self.svc.propose("plan", "strategist", action="propose", payload=_plan(),
                              idempotency_key="dupkey")
        r2 = self.svc.propose("plan", "strategist", action="propose", payload=_plan(),
                              idempotency_key="dupkey")
        self.assertTrue(r2["reused"])
        self.assertEqual(r1["proposal_id"], r2["proposal_id"])

    def test_revision_increments_version_and_preserves_original(self):
        r1 = self.svc.propose("plan", "strategist", action="propose", payload=_plan(),
                              idempotency_key="base")
        before = self.db.query(
            "SELECT payload_json FROM work_proposals WHERE id=? AND tenant_id=?",
            (r1["proposal_id"], TENANT))[0]["payload_json"]
        r2 = self.svc.revision_plan(
            r1["proposal_id"], "strategist",
            payload_updates={"title": "Launch On Us v2"},
            idempotency_key="rev1")
        self.assertNotEqual(r1["proposal_id"], r2["proposal_id"])
        after = self.db.query(
            "SELECT payload_json FROM work_proposals WHERE id=? AND tenant_id=?",
            (r1["proposal_id"], TENANT))[0]["payload_json"]
        # Original preserved byte-for-byte
        self.assertEqual(before, after)
        new_payload = json.loads(self.db.query(
            "SELECT payload_json FROM work_proposals WHERE id=? AND tenant_id=?",
            (r2["proposal_id"], TENANT))[0]["payload_json"])
        self.assertEqual(new_payload["version"], 2)
        self.assertEqual(new_payload["revision_of"], r1["proposal_id"])
        self.assertEqual(new_payload["title"], "Launch On Us v2")

    def test_revision_preserves_original_payload_field_unchanged(self):
        r1 = self.svc.propose("plan", "strategist", action="propose",
                              payload=_plan(milestones=[{"title": "M1", "order": 1}]),
                              idempotency_key="base2")
        orig = self.db.query(
            "SELECT payload_json FROM work_proposals WHERE id=? AND tenant_id=?",
            (r1["proposal_id"], TENANT))[0]["payload_json"]
        self.svc.revision_plan(r1["proposal_id"], "strategist",
                               payload_updates={"success_criteria": ["new"]},
                               idempotency_key="rev2")
        # Original row byte-for-byte unchanged (milestone content intact)
        self.assertEqual(
            self.db.query("SELECT payload_json FROM work_proposals WHERE id=? AND tenant_id=?",
                          (r1["proposal_id"], TENANT))[0]["payload_json"],
            orig)

    def test_reject_terminal_with_reason(self):
        r1 = self.svc.propose("plan", "strategist", action="propose", payload=_plan(),
                              idempotency_key="rej")
        self.svc.reject(r1["proposal_id"], "u1", reason="scope mismatch")
        row = self.db.query(
            "SELECT status, rejection_reason FROM work_proposals WHERE id=? AND tenant_id=?",
            (r1["proposal_id"], TENANT))[0]
        self.assertEqual(row["status"], "rejected")
        self.assertEqual(row["rejection_reason"], "scope mismatch")

    def test_cannot_revise_rejected_plan(self):
        r1 = self.svc.propose("plan", "strategist", action="propose", payload=_plan(),
                              idempotency_key="rej2")
        self.svc.reject(r1["proposal_id"], "u1", reason="no")
        with self.assertRaises(ValueError):
            self.svc.revision_plan(r1["proposal_id"], "strategist",
                                   idempotency_key="shouldfail")

    def test_revision_of_must_be_owned_plan_proposal(self):
        with self.assertRaises(ProposalNotFound):
            self.svc.revision_plan("nope", "strategist", idempotency_key="x")

        # revision_of pointing to a non-plan proposal type -> rejected on propose
        other = self.svc.propose("workspace", "workspace_architect",
                                 action="create", payload={"name": "WS"},
                                 idempotency_key="nonplan")
        bad_payload = _plan()
        bad_payload["revision_of"] = other["proposal_id"]  # a workspace proposal, not a plan
        with self.assertRaises(ValueError):
            self.svc.propose("plan", "strategist", action="propose",
                             payload=bad_payload, idempotency_key="lineagebad")

        # unknown revision_of id -> rejected
        bad_payload2 = _plan()
        bad_payload2["revision_of"] = "unknown-id"
        with self.assertRaises(ValueError):
            self.svc.propose("plan", "strategist", action="propose",
                             payload=bad_payload2, idempotency_key="lineagebad2")

    def test_malformed_payload_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.propose("plan", "strategist", action="propose",
                             payload={"title": ""}, idempotency_key="bad1")
        with self.assertRaises(ValueError):
            self.svc.propose("plan", "strategist", action="propose",
                             payload={"title": "T", "version": "x"},
                             idempotency_key="bad2")

    def test_no_plan_proposals_table_exists(self):
        # Confirms we did NOT introduce a second state machine/table.
        tables = [r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertNotIn("plan_proposals", tables)

    def test_cross_tenant_lineage_blocked(self):
        r1 = self.svc.propose("plan", "strategist", action="propose", payload=_plan(),
                              idempotency_key="cten")
        svc_b = WorkProposalService(db=self.db, tenant_id="tenantB", user_id="u1")
        # tenantB cannot see/manipulate tenantA's proposal lineage
        with self.assertRaises(ProposalNotFound):
            svc_b.revision_plan(r1["proposal_id"], "strategist", idempotency_key="ctenB")


if __name__ == "__main__":
    unittest.main()
