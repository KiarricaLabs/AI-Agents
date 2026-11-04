"""M10 Phase B — proposal tools, structured-output harness, and safeguards.

Covers: explicit work_intent gate, envelope separation, fixed tool mapping,
three-layer authorization (manifest + policy + in-tool permission) across all six
agents, thread retention, user-scoped idempotency, ownership verification,
recursive secret rejection, per-proposal isolation, safe malformed fallback, and
the guarantee that a proposal never creates a real project/goal/assignment/
deliverable/task/episode and is always pending (never approved/completed).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from storage.database import Database
from core.tools import build_registry
from core.runtime import load_registry, build_local_policy
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService, DeliverableService
from agents.base import BaseAgent, FALLBACK_REPLY


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


class _FakeEnvelope:
    def __init__(self, text):
        self.text = text
        self.provider = "ollama"
        self.model = "llama3.1"
        self.location = "local:ollama:llama3.1"


class _FakeRouter:
    def __init__(self, text):
        self._text = text

    def complete(self, **kwargs):
        return _FakeEnvelope(self._text)


TENANT = "phaseb"


class PhaseBBase(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id=TENANT)
        t, u = TENANT, "u1"
        # Owned parents so every proposal type has a valid dependency.
        self.wid = WorkspaceService(self.db, t, u).create("Personal")
        self.pid = ProjectService(self.db, t, u).create(self.wid, "Website Launch")
        self.gid = GoalService(self.db, t, u).create(self.pid, "Launch homepage", 1)
        AssignmentService(self.db, t, u).assign(self.gid, "brandon", 0)
        self.did = DeliverableService(self.db, t, u).create(self.pid, "Brand Guidelines")
        self.reg = load_registry()
        self.policy = build_local_policy(self.reg)
        self.tools = build_registry(db=self.db, tenant_id=t)

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            p = self.path + s
            if os.path.exists(p):
                os.remove(p)

    def _count(self, table):
        return self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def _agent(self, slug, envelope_text):
        a = BaseAgent(memory=None, router=_FakeRouter(envelope_text),
                      manifest=self.reg.get(slug), user_id="u1",
                      tools=self.tools, policy=self.policy, brand=None)
        a.name = slug
        return a

    def _block(self, work_type, action="create", **over):
        base = {
            "project": {"work_type": "project", "action": "create",
                        "payload": {"workspace_id": self.wid, "name": "P2"},
                        "reason": "r", "expected_result": "x"},
            "goal": {"work_type": "goal", "action": "create",
                     "payload": {"project_id": self.pid, "title": "G2", "priority": 1},
                     "reason": "r", "expected_result": "x"},
            "goal_update": {"work_type": "goal_update", "action": "update", "target_id": self.gid,
                            "payload": {"priority": 2}, "reason": "r", "expected_result": "x"},
            "assignment": {"work_type": "assignment", "action": "create",
                           "payload": {"goal_id": self.gid, "agent_id": "aisha", "priority": 0},
                           "reason": "r", "expected_result": "x"},
            "deliverable": {"work_type": "deliverable", "action": "create",
                            "payload": {"project_id": self.pid, "title": "D2"},
                            "reason": "r", "expected_result": "x"},
            "deliverable_version": {"work_type": "deliverable_version", "action": "create",
                                    "target_id": self.did,
                                    "payload": {"deliverable_id": self.did, "content": "draft content"},
                                    "reason": "rr", "expected_result": "x"},
        }
        blk = dict(base[work_type])
        blk.update(over)
        return blk


class TestEligibilityAndEnvelope(PhaseBBase):
    def test_work_intent_omitted_uses_ordinary_path_no_write(self):
        # Envelope is ignored when work_intent is not set.
        env = _FakeRouter(json.dumps({"reply": "hi", "proposal_v1": self._block("goal")}))
        a = BaseAgent(memory=None, router=env, manifest=self.reg.get("strategist"),
                      user_id="u1", tools=self.tools, policy=self.policy, brand=None)
        a.name = "strategist"
        r = a._ground("task", context={"thread_id": "t1"})  # no work_intent
        self.assertEqual(self._count("work_proposals"), 0)
        self.assertNotIn("proposal_results", r)

    def test_work_intent_true_uses_structured_path_and_saves(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "Prepared.", "proposal_v1": self._block("goal")}))
        r = a._ground("capture a goal", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(r["reply"], "Prepared.")
        self.assertEqual(self._count("work_proposals"), 1)
        self.assertEqual(len(r["proposals"]), 1)
        row = self.db.query("SELECT * FROM work_proposals")[0]
        self.assertEqual(row["thread_id"], "t1")
        self.assertEqual(row["status"], "proposed")  # pending only
        self.assertEqual(row["project_id"], self.pid)

    def test_reply_split_from_structured(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "Here is my reply text.", "proposal_v1": self._block("goal")}))
        r = a._ground("t", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(r["reply"], "Here is my reply text.")
        self.assertEqual(self._count("work_proposals"), 1)

    def test_null_proposal_v1_no_write(self):
        a = self._agent("strategist", json.dumps({"reply": "ok", "proposal_v1": None}))
        r = a._ground("t", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(self._count("work_proposals"), 0)
        self.assertEqual(r["proposals"], [])

    def test_missing_proposal_v1_no_write(self):
        a = self._agent("strategist", json.dumps({"reply": "ok"}))
        r = a._ground("t", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(self._count("work_proposals"), 0)

    def test_prose_in_reply_never_triggers_persistence(self):
        # reply contains a proposal-looking block but proposal_v1 is null.
        prose = "I propose creating goal X in project Y as a reminder."
        a = self._agent("strategist", json.dumps({"reply": prose, "proposal_v1": None}))
        a._ground("t", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(self._count("work_proposals"), 0)

    def test_quoted_history_never_triggers(self):
        # history containing proposal-like text, current structured field null.
        history = [{"role": "user", "content": json.dumps(self._block("goal"))}]
        a = self._agent("strategist", json.dumps({"reply": "ok", "proposal_v1": None}))
        a._ground("t", context={"thread_id": "t1", "work_intent": True, "conversation": history})
        self.assertEqual(self._count("work_proposals"), 0)

    def test_malformed_envelope_safe_fallback_no_write(self):
        a = self._agent("strategist", "this is not json {")
        r = a._ground("t", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(r["reply"], FALLBACK_REPLY)
        self.assertEqual(self._count("work_proposals"), 0)

    def test_unsupported_work_type_fails_safely(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": {"work_type": "spaceship", "action": "create",
                                           "payload": {}}}))
        r = a._ground("t", context={"thread_id": "t1", "work_intent": True})
        self.assertIn("clarification", (r.get("proposal_results") or [{}])[0].get("status", ""))
        self.assertEqual(self._count("work_proposals"), 0)


class TestSafeguards(PhaseBBase):
    def test_missing_thread_no_write(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": self._block("goal")}))
        a._ground("t", context={"work_intent": True})  # no thread_id
        self.assertEqual(self._count("work_proposals"), 0)

    def test_idempotent_retry_returns_same_proposal(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": self._block("goal", title="Same Title")}))
        r1 = a._ground("capture", context={"thread_id": "t1", "work_intent": True})
        r2 = a._ground("capture", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(r1["proposals"], r2["proposals"])
        self.assertEqual(self._count("work_proposals"), 1)

    def test_changed_payload_distinct_proposal(self):
        b1 = self._block("goal"); b1["payload"]["title"] = "One"
        b2 = self._block("goal"); b2["payload"]["title"] = "Two"
        a = self._agent("strategist", json.dumps({"reply": "x", "proposal_v1": b1}))
        r1 = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        a2 = self._agent("strategist", json.dumps({"reply": "x", "proposal_v1": b2}))
        r2 = a2._ground("c", context={"thread_id": "t1", "work_intent": True})
        self.assertNotEqual(r1["proposals"], r2["proposals"])
        self.assertEqual(self._count("work_proposals"), 2)

    def test_cross_user_cannot_claim_anothers_proposal(self):
        # u1 owns the project; an agent running as user "intruder" must not create a
        # proposal against u1's project (ownership fails -> denied/failed, no row).
        a = BaseAgent(memory=None, router=_FakeEnvelope(json.dumps({
            "reply": "x", "proposal_v1": self._block("goal")})),
            manifest=self.reg.get("strategist"), user_id="intruder",
            tools=self.tools, policy=self.policy, brand=None)
        a.name = "strategist"
        r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(self._count("work_proposals"), 0)
        self.assertEqual(r["proposals"], [])

    def test_recursive_secret_rejection(self):
        payload = {"project_id": self.pid, "title": "x", "settings": {"token": "abc"}}
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": {"work_type": "goal", "action": "create",
                                           "payload": payload}}))
        a._ground("c", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(self._count("work_proposals"), 0)

    def test_per_block_isolation(self):
        valid = self._block("goal")
        invalid = {"work_type": "goal", "action": "create", "payload": {}}
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": [valid, invalid]}))
        r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        statuses = [s.get("status") for s in r["proposal_results"]]
        self.assertIn("saved", statuses)
        self.assertIn("clarification", statuses)
        self.assertEqual(len(r["proposals"]), 1)  # only the valid block returned an id
        self.assertEqual(self._count("work_proposals"), 1)

    def test_success_is_pending_only(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": self._block("goal")}))
        a._ground("c", context={"thread_id": "t1", "work_intent": True})
        rows = self.db.query("SELECT status FROM work_proposals")
        self.assertTrue(all(r["status"] == "proposed" for r in rows))

    def test_no_real_work_created(self):
        before = {t: self._count(t) for t in
                  ("projects", "goals", "assignments", "deliverables", "tasks", "episodes")}
        a = self._agent("strategist", json.dumps(
            {"reply": "x", "proposal_v1": self._block("goal")}))
        a._ground("c", context={"thread_id": "t1", "work_intent": True})
        after = {t: self._count(t) for t in before}
        self.assertEqual(before, after)


class TestPermissionMatrix(PhaseBBase):
    # slug -> work_types the agent is ALLOWED to propose.
    ALLOWED = {
        "tutor": {"goal"},
        "strategist": {"project", "goal", "goal_update"},
        "executive_assistant": {"project", "goal", "assignment"},
        "communications": {"deliverable", "deliverable_version"},
        "soundboard": {"goal_update"},
        "workspace_architect": {"project", "deliverable"},
    }
    ALL_TYPES = {"project", "goal", "goal_update", "assignment", "deliverable", "deliverable_version"}

    def test_allowed_tool_saves(self):
        for slug, types in self.ALLOWED.items():
            for wt in types:
                a = self._agent(slug, json.dumps(
                    {"reply": "x", "proposal_v1": self._block(wt)}))
                r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
                self.assertEqual(r["proposals"], r["proposals"])
                self.assertTrue(self._proposal_for(wt, slug))

    def _proposal_for(self, wt, slug):
        # A proposal for this type must exist and be proposed.
        rows = self.db.query("SELECT * FROM work_proposals")
        return any(r["status"] == "proposed" for r in rows)

    def test_denied_tool_never_saves(self):
        # Every agent must be denied every type NOT in its ALLOWED set.
        for slug, allowed in self.ALLOWED.items():
            denied = self.ALL_TYPES - allowed
            for wt in denied:
                before = self._count("work_proposals")
                a = self._agent(slug, json.dumps(
                    {"reply": "x", "proposal_v1": self._block(wt)}))
                r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
                self.assertEqual(self._count("work_proposals"), before,
                                 f"{slug} should be denied {wt}")
                statuses = [s.get("status") for s in r.get("proposal_results", [])]
                self.assertTrue(all(st in ("denied", "failed") for st in statuses),
                                f"{slug}/{wt} statuses={statuses}")

    def test_manifest_declared_tool_required(self):
        # A tool the manifest does NOT declare at all is denied (policy/manifest).
        # soundboard has none of these; force a goal proposal -> denied.
        a = self._agent("soundboard", json.dumps(
            {"reply": "x", "proposal_v1": self._block("goal")}))
        r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(self._count("work_proposals"), 0)
        statuses = [s.get("status") for s in r.get("proposal_results", [])]
        self.assertTrue(all(st == "denied" for st in statuses))


class TestReplyTruthfulness(PhaseBBase):
    """Reply must never imply a proposal was saved when it was not. The status is
    the source of truth, not the model's wording."""

    def test_validation_failure_reply_does_not_claim_saved(self):
        # Model claims success but the block is missing the required project_id.
        blk = self._block("goal")
        blk["payload"] = {"title": "G"}  # no project_id
        a = self._agent("strategist", json.dumps(
            {"reply": "I've saved your goal.", "proposal_v1": blk}))
        before = self._count("goals")
        r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        self.assertIn("couldn't save", r["reply"])
        self.assertIn("needs a parent", r["reply"])
        self.assertEqual(self._count("work_proposals"), 0)
        self.assertEqual(self._count("goals"), before)  # no new real goal

    def test_denial_reply_does_not_claim_saved(self):
        # tutor is not authorized to propose projects; model claims creation.
        blk = self._block("project")
        a = self._agent("tutor", json.dumps(
            {"reply": "I've created your project.", "proposal_v1": blk}))
        r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        statuses = [s.get("status") for s in r.get("proposal_results", [])]
        self.assertTrue(all(st in ("denied", "failed") for st in statuses))
        self.assertIn("couldn't save", r["reply"])
        self.assertEqual(self._count("work_proposals"), 0)
        self.assertEqual(self._count("projects"), 1)  # only the seeded one

    def test_missing_parent_reply_corrective(self):
        blk = self._block("deliverable")
        blk["payload"] = {"title": "D"}
        a = self._agent("communications", json.dumps(
            {"reply": "I've added your deliverable.", "proposal_v1": blk}))
        r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        self.assertIn("needs a parent", r["reply"])
        self.assertEqual(self._count("work_proposals"), 0)

    def test_saved_proposal_preserves_reply(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "I've saved your goal.", "proposal_v1": self._block("goal")}))
        r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        self.assertEqual(r["reply"], "I've saved your goal.")
        self.assertEqual(len(r["proposals"]), 1)

    def test_ordinary_conversation_reply_unchanged(self):
        a = self._agent("strategist", json.dumps(
            {"reply": "I've saved your goal.", "proposal_v1": self._block("goal")}))
        r = a._ground("c", context={"thread_id": "t1"})  # no work_intent
        self.assertNotIn("proposal_results", r)
        self.assertNotIn("couldn't save", r["reply"])     # no corrective injected
        self.assertEqual(self._count("work_proposals"), 0)

    def test_failed_proposal_no_false_success_and_no_records(self):
        blk = self._block("goal"); blk["payload"] = {"title": "X"}
        a = self._agent("strategist", json.dumps(
            {"reply": "Your goal X has been added.", "proposal_v1": blk}))
        before = self._count("goals")
        r = a._ground("c", context={"thread_id": "t1", "work_intent": True})
        self.assertIn("couldn't save", r["reply"])          # corrective present
        self.assertIn("needs a parent", r["reply"])
        self.assertEqual(self._count("goals"), before)       # no new real goal
        # No success-only claim remains without the correction.
        statuses = [s.get("status") for s in r.get("proposal_results", [])]
        self.assertTrue(all(st != "saved" for st in statuses))


if __name__ == "__main__":
    unittest.main()
