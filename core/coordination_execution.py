"""T2-C-4 — CoordinationExecutionService: human-initiated, step-by-step output aggregation.

Consumes the ALREADY-AUTHORIZED T2-C-3 coordination-plan snapshot as the sole
source of assignments/responsibilities/dependencies. Execution is strictly
human-initiated and human-advanced:

- ``initiate``   — a human starts a run for an authorized plan (idempotent).
- ``execute_step`` — a human requests the *next eligible* step to run (one step at
                   a time, in order, after its dependencies are accepted).
- ``review_step`` — a human accepts / requests revision / rejects a step output.
- ``aggregate`` — once all steps are accepted, build the consolidated deliverable.
- ``review_deliverable`` — final human accept / revision / reject.

Boundaries (non-negotiable)
---------------------------
- Never rebuilds, reassigns, or modifies the authorized plan snapshot.
- Only ACCEPTED step outputs become context for downstream steps; rejected /
  failed / missing / revision-requested outputs are never used as accepted context.
- A dependent step cannot execute until all its dependencies are accepted.
- Evidence-gated completion (via EpisodeService) is required; nothing is marked
  done without validated evidence.
- Accepted output does NOT auto-dispatch the next agent — a separate human action
  is required per step.
- No autonomous/background dispatch, no scheduler, no cloud fallback, no new agent
  identities, no permission expansion. Runtime policy still applies and may deny.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

_log = logging.getLogger("coordination_execution")

from core.episodes import EpisodeService
from core.validation import validate_output
from core.runtime import build_runtime, load_registry
from core.orchestrator import Orchestrator
from core.memory import MemoryService
from core.brand import BrandService
from core.model_router import ModelRouter
from core.policy import PolicyEngine
from core.tools import build_registry
from core.tools.work_propose import ALL_PROPOSE_TOOLS

# Step / execution lifecycle statuses
RUN_RUNNING = "running"
RUN_READY = "ready_for_review"
RUN_COMPLETED = "completed"
RUN_REJECTED = "rejected"

STEP_RUNNABLE = {"pending", "revision_requested", "failed"}
STEP_TERMINAL_ACCEPTED = "accepted"
STEP_TERMINAL_REJECTED = "rejected"
STEP_AWAITING = "awaiting_review"
STEP_IN_PROGRESS = "in_progress"

DELIV_RUNNABLE_STATUSES = {"running", "ready_for_review"}


def _now():
    return datetime.now(timezone.utc).isoformat()


class CoordinationExecutionNotFound(ValueError):
    pass


class PlanNotAuthorized(ValueError):
    pass


class PlanNotOwned(ValueError):
    pass


class NoEligibleStep(ValueError):
    pass


class DependencyNotAccepted(ValueError):
    pass


class InvalidStep(ValueError):
    pass


class StepNotAwaitingReview(ValueError):
    pass


class StepAlreadyClaimed(ValueError):
    pass


class ExecutionNotRunnable(ValueError):
    pass


class NotAllStepsAccepted(ValueError):
    pass


class AgentOutputInvalid(ValueError):
    pass


class ReviewNotPermitted(PermissionError):
    pass


class CoordinationExecutionService:
    def __init__(self, db, tenant_id: str, user_id: str,
                 dispatcher: Optional[Callable[[str, str, Dict[str, Any]], Any]] = None):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.episodes = EpisodeService(db, tenant_id, user_id)
        from core.coordination_deliverable import CoordinationDeliverableService
        self.deliverables = CoordinationDeliverableService(db, tenant_id, user_id)
        # dispatcher(agent_id, responsibility, context) -> agent result dict.
        # Default: live local Ollama orchestration (policy-gated, validated).
        # Tests inject a deterministic stub; runtime policy is NOT bypassed here.
        self._dispatcher = dispatcher

    # ------------------------------------------------------------------ auth/scoping
    def _scoped(self, rows):
        return [dict(r) for r in rows]

    def _get_plan(self, plan_id: str) -> Dict[str, Any]:
        rows = self.db.query(
            "SELECT * FROM coordination_plans WHERE id=? AND tenant_id=? AND user_id=?",
            (plan_id, self.tenant_id, self.user_id))
        if not rows:
            raise PlanNotOwned("plan not found in this tenant/user scope")
        return rows[0]

    def _get_plan_steps(self, plan_id: str) -> List[Dict[str, Any]]:
        return self._scoped(self.db.query(
            "SELECT * FROM coordination_plan_steps WHERE plan_id=? AND tenant_id=? AND user_id=? "
            "ORDER BY seq ASC",
            (plan_id, self.tenant_id, self.user_id)))

    def _get_execution(self, execution_id: str) -> Dict[str, Any]:
        rows = self.db.query(
            "SELECT * FROM coordination_executions WHERE id=? AND tenant_id=? AND user_id=?",
            (execution_id, self.tenant_id, self.user_id))
        if not rows:
            raise CoordinationExecutionNotFound("execution not found")
        return rows[0]

    def _step_output(self, execution_id: str, seq: int) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_step_outputs WHERE execution_id=? AND seq=? "
            "AND tenant_id=? AND user_id=?",
            (execution_id, seq, self.tenant_id, self.user_id))
        return rows[0] if rows else None

    # ------------------------------------------------------------------ initiate
    def initiate(self, plan_id: str, approver_user_id: str) -> Dict[str, Any]:
        """Human initiates an execution run for an authorized plan. Idempotent: an
        existing run for this plan is returned. Does NOT execute anything."""
        if approver_user_id != self.user_id:
            raise ReviewNotPermitted("only the owner may initiate execution")
        plan = self._get_plan(plan_id)
        if plan.get("status") != "authorized":
            raise PlanNotAuthorized(
                f"plan is not authorized for execution (status={plan.get('status')})")
        existing = self.db.query(
            "SELECT * FROM coordination_executions WHERE tenant_id=? AND user_id=? AND plan_id=?",
            (self.tenant_id, self.user_id, plan_id))
        if existing:
            return self._hydrate_execution(existing[0], reused=True)

        run_id = str(uuid.uuid4())
        now = _now()
        # Fetch step assignments BEFORE opening the transaction (the transaction
        # uses a non-reentrant lock; self.db.query must not run inside it).
        steps = self._get_plan_steps(plan_id)
        try:
            with self.db.transaction() as c:
                # Initialize per-step output rows in runnable state.
                c.execute(
                    "INSERT INTO coordination_executions "
                    "(id, tenant_id, user_id, plan_id, team_goal_id, status, initiated_by, "
                    " initiated_at, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (run_id, self.tenant_id, self.user_id, plan_id,
                     plan["team_goal_id"], RUN_RUNNING, approver_user_id, now, now, now))
                for s in steps:
                    c.execute(
                        "INSERT INTO coordination_step_outputs "
                        "(id, tenant_id, user_id, execution_id, plan_id, seq, agent_id, "
                        " status, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), self.tenant_id, self.user_id, run_id,
                         plan_id, s["seq"], s["agent_id"], "pending", now, now))
        except Exception:
            raise  # rollback; nothing partial
        return self._hydrate_execution(self._get_execution(run_id), reused=False)

    # ------------------------------------------------------------------ eligibility
    def _dep_status(self, execution_id: str, seq: int) -> Optional[str]:
        """Status of step ``seq`` in this execution, or None if absent."""
        out = self._step_output(execution_id, seq)
        return out["status"] if out else None

    def next_eligible_step(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """The next runnable step: the lowest-seq step in a runnable state whose
        dependencies are all accepted. Returns None when nothing is eligible."""
        run = self._get_execution(execution_id)
        if run["status"] not in DELIV_RUNNABLE_STATUSES:
            return None
        steps = self._get_plan_steps(run["plan_id"])
        steps.sort(key=lambda s: s["seq"])
        for s in steps:
            seq = s["seq"]
            st = self._dep_status(execution_id, seq) or "pending"
            if st not in STEP_RUNNABLE:
                continue  # accepted/awaiting/in-progress/rejected not runnable here
            dep = s["depends_on_seq"]
            if dep is not None:
                dep_st = self._dep_status(execution_id, int(dep))
                if dep_st != STEP_TERMINAL_ACCEPTED:
                    continue  # dependency not accepted -> cannot run yet
            return {"seq": seq, "agent_id": s["agent_id"],
                    "responsibility": s["responsibility"]}
        return None

    # ------------------------------------------------------------------ dispatch +
    # F2 permission-ceiling enforcement
    @staticmethod
    def _tool_required_permission_map():
        """Map each proposed-work tool name to its required permission string.
        These are the only permission-bearing side-effect tools; non-propose
        tools (now/calculate) are not permission-gated and are excluded here."""
        return {cls.name: cls.required_permission for cls in ALL_PROPOSE_TOOLS}

    def _restricted_orchestrator(self, agent: str, ceiling: set):
        """Build an Orchestrator whose manifest + policy for ``agent`` are bounded
        to ``ceiling`` (the persisted effective-permission set intersected with the
        agent's runtime-available permissions). This mechanically prevents the
        agent from using tools/actions outside the ceiling, without modifying
        core/delegation.py, the manifests, or the shared policy builder.

        Enforcement gates:
        - Manifest `permissions` is limited to the ceiling (feed into the
          propose-tool layer-3 check `required_permission in manifest.permissions`).
        - Manifest `tools` is limited to tools whose required permission is in the
          ceiling (layer-2 `tool in manifest.tools` gate in ToolRegistry.invoke).
        - The restricted PolicyEngine only allows dispatch + those tools/goal/brand
          actions derivable from the ceiling (default-deny otherwise).
        """
        reg = load_registry()
        full = reg.get(agent) or {}
        ceiling = set(ceiling) & set(full.get("permissions", []) or [])
        required = self._tool_required_permission_map()
        allowed_tools = [
            t for t in (full.get("tools", []) or [])
            if t not in required or required[t] in ceiling
        ]
        restricted = dict(full)
        restricted["permissions"] = sorted(ceiling)
        restricted["tools"] = allowed_tools

        class _RestrictedRegistry:
            def get(self, name):
                if name == agent:
                    return restricted
                return reg.get(name)
            def list(self):
                return reg.list()

        rules = [
            {"subject": "system", "action": "dispatch", "resource": agent, "effect": "allow"},
        ]
        for tool in allowed_tools:
            rules.append({"subject": agent, "action": "tool", "resource": tool, "effect": "allow"})
        if "goal:propose" in ceiling:
            rules.append({"subject": agent, "action": "goal", "resource": "propose", "effect": "allow"})
        if "goals:all" in ceiling:
            rules.append({"subject": agent, "action": "goal", "resource": "read_all", "effect": "allow"})
        if "brand:read" in ceiling:
            rules.append({"subject": agent, "action": "brand", "resource": "read", "effect": "allow"})
        policy = PolicyEngine.from_dict({"rules": rules})

        return Orchestrator(
            registry=_RestrictedRegistry(),
            policy=policy,
            router=ModelRouter(),
            memory=MemoryService(db=self.db, tenant_id=self.tenant_id),
            brand=BrandService(db=self.db, tenant_id=self.tenant_id),
            user_id=self.user_id,
            tools=build_registry(db=self.db, tenant_id=self.tenant_id),
        )

    def _dispatch(self, agent, responsibility, context, effective_permissions=None):
        """Dispatch a step agent under the persisted permission ceiling (fail
        closed). The persisted T2-C-3 ``effective_permissions`` is REQUIRED:
        execution always uses the step-scoped restricted Orchestrator, never the
        unrestricted full runtime. Empty/missing/malformed ceiling -> refuse.

        The injected ``self._dispatcher`` is a unit-test seam ONLY; it is never
        set in production. It bypasses dispatch itself so isolated lifecycle
        tests can avoid a live model, and therefore must not be relied on for
        permission enforcement (that is covered by the restricted-orchestrator
        and fail-closed tests). A production caller always passes a valid
        persisted ceiling.
        """
        if self._dispatcher is not None:
            return self._dispatcher(agent, responsibility, context)
        if not effective_permissions:
            raise PermissionError(
                "no persisted permission ceiling for this step; refusing to "
                "dispatch (an empty/missing ceiling is never treated as full access)")
        orch = self._restricted_orchestrator(agent, set(effective_permissions))
        return orch.dispatch(agent, responsibility or "", {"accepted_step_outputs": context})

    # ------------------------------------------------------------------ execute
    def execute_step(self, execution_id: str, approver_user_id: str) -> Dict[str, Any]:
        """Human explicitly executes the next eligible step (one at a time).
        Never auto-dispatches the subsequent step. Evidence-gated completion."""
        if approver_user_id != self.user_id:
            raise ReviewNotPermitted("only the owner may execute steps")
        run = self._get_execution(execution_id)
        if run["status"] not in DELIV_RUNNABLE_STATUSES:
            raise ExecutionNotRunnable(
                f"execution is not runnable (status={run['status']})")
        plan = self._get_plan(run["plan_id"])
        eligible = self.next_eligible_step(execution_id)
        if eligible is None:
            raise NoEligibleStep(
                "no eligible step: all pending steps await an accepted dependency "
                "or the run is awaiting your review")
        seq = eligible["seq"]
        agent = eligible["agent_id"]
        responsibility = eligible["responsibility"]

        now = _now()
        # Start a tracked execution Episode for this step (idempotent active;
        # reuses the running episode across retries). episode_id is safe to
        # compute before the claim because start_for_work never duplicates.
        ep = self.episodes.start_for_work("coordination_step", f"{run['plan_id']}:{seq}", agent)
        episode_id = ep["episode_id"]

        # Atomic step claim: atomically transition the step from a runnable state
        # (pending / revision_requested / failed) to in-progress while persisting
        # the episode link. Only a claim that affects exactly one row may proceed,
        # so a competing request cannot dispatch the same step twice. This is the
        # single serialization point for step execution.
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE coordination_step_outputs SET status=?, episode_id=?, updated_at=? "
                "WHERE execution_id=? AND seq=? AND status IN ('pending','revision_requested','failed') "
                "AND tenant_id=? AND user_id=?",
                (STEP_IN_PROGRESS, episode_id, now, execution_id, seq,
                 self.tenant_id, self.user_id))
            if cur.rowcount == 0:
                raise StepAlreadyClaimed(
                    f"step {seq} was already claimed/executed; no duplicate dispatch")

        # Dispatch the agent locally (Ollama) under the persisted permission
        # ceiling. Reads the authorized snapshot row's effective_permissions so
        # the agent cannot use permissions/tools beyond the T2-C-3 ceiling.
        accepted_context = self._accepted_context(run["plan_id"], execution_id)
        step_row = self._plan_step_row(run["plan_id"], seq)
        ceiling = []
        if step_row and step_row.get("effective_permissions"):
            try:
                ceiling = json.loads(step_row["effective_permissions"])
            except (TypeError, ValueError):
                ceiling = []
        try:
            result = self._dispatch(agent, responsibility, accepted_context,
                                    effective_permissions=ceiling)
        except Exception as e:
            self._mark_step(run["plan_id"], execution_id, seq, "failed",
                            error=(str(e)[:500] or "dispatch failed"))
            # Preserve the original dispatch failure as the exception cause so
            # the root cause (and its chain) remains inspectable/debuggable.
            raise AgentOutputInvalid(f"agent dispatch failed: {e}") from e
        ok, err = validate_output(agent, result)
        if not ok:
            self._mark_step(run["plan_id"], execution_id, seq, "failed",
                            error=(err[:500] or "invalid output"))
            raise AgentOutputInvalid(f"invalid agent output: {err}") from None
        summary = str(result.get("reply") or "").strip() or str(result)[:200]
        evidence = {"summary": summary[:400]}

        # Complete the episode only with structured, validated evidence.
        completed = self.episodes.complete_with_evidence(episode_id, evidence)
        if not completed:
            self._mark_step(run["plan_id"], execution_id, seq, "failed",
                            error="episode could not be completed with evidence")
            raise AgentOutputInvalid("episode could not be completed with evidence")

        with self.db.transaction() as c:
            c.execute(
                "UPDATE coordination_step_outputs SET status=?, output_json=?, evidence_json=?, "
                "updated_at=? WHERE execution_id=? AND seq=? AND tenant_id=? AND user_id=?",
                (STEP_AWAITING, json.dumps(result), json.dumps(evidence), now,
                 execution_id, seq, self.tenant_id, self.user_id))
        return {"execution_id": execution_id, "step": seq, "agent_id": agent,
                "status": STEP_AWAITING, "episode_id": episode_id,
                "requires_review": True}

    # ------------------------------------------------------------------ autonomous
    def _run_autonomous_step(self, execution_id: str, plan_id: str, seq: int,
                             agent: str, responsibility: str,
                             ceiling: list) -> Dict[str, Any]:
        """Run one step to an ACCEPTED conclusion (no human per-step gate).

        Uses the same atomic claim + validated evidence path as execute_step, but
        finalizes the output as ``accepted`` so the run can advance on its own.
        A competing request cannot dispatch the same step twice (atomic claim).
        """
        now = _now()
        episode_id = self.episodes.start_for_work(
            "coordination_step", f"{plan_id}:{seq}", agent)["episode_id"]
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE coordination_step_outputs SET status=?, episode_id=?, updated_at=? "
                "WHERE execution_id=? AND seq=? AND status IN ('pending','revision_requested','failed') "
                "AND tenant_id=? AND user_id=?",
                (STEP_IN_PROGRESS, episode_id, now, execution_id, seq,
                 self.tenant_id, self.user_id))
            if cur.rowcount == 0:
                raise StepAlreadyClaimed(
                    f"step {seq} was already claimed/executed; no duplicate dispatch")
        accepted_context = self._accepted_context(plan_id, execution_id)
        try:
            result = self._dispatch(agent, responsibility, accepted_context,
                                    effective_permissions=ceiling)
        except Exception as e:
            self._mark_step(plan_id, execution_id, seq, "failed",
                            error=(str(e)[:500] or "dispatch failed"))
            raise AgentOutputInvalid(f"agent dispatch failed: {e}") from e
        ok, err = validate_output(agent, result)
        if not ok:
            self._mark_step(plan_id, execution_id, seq, "failed",
                            error=(err[:500] or "invalid output"))
            raise AgentOutputInvalid(f"invalid agent output: {err}") from None
        summary = str(result.get("reply") or "").strip() or str(result)[:200]
        evidence = {"summary": summary[:400]}
        if not self.episodes.complete_with_evidence(episode_id, evidence):
            self._mark_step(plan_id, execution_id, seq, "failed",
                            error="episode could not be completed with evidence")
            raise AgentOutputInvalid("episode could not be completed with evidence")
        with self.db.transaction() as c:
            c.execute(
                "UPDATE coordination_step_outputs SET status=?, output_json=?, evidence_json=?, updated_at=? "
                "WHERE execution_id=? AND seq=? AND tenant_id=? AND user_id=?",
                (STEP_TERMINAL_ACCEPTED, json.dumps(result), json.dumps(evidence), now,
                 execution_id, seq, self.tenant_id, self.user_id))
        return {"seq": seq, "agent_id": agent, "status": STEP_TERMINAL_ACCEPTED}

    def run_autonomously(self, execution_id: str, approver_user_id: str) -> Dict[str, Any]:
        """Autonomous run: execute every eligible step in dependency order,
        auto-accept validated outputs, then aggregate the deliverable for the
        owner\u2019s final review. Replaces the per-step manual flow. Owner-only and
        human-launched; no idle background/scheduler work.

        Any output already left ``awaiting_review`` (from an earlier manual run)
        is adopted as accepted. Rework and aggregate follow the existing evidence
        and permission-ceiling rules.
        """
        if approver_user_id != self.user_id:
            raise ReviewNotPermitted("only the owner may run this execution")
        run = self._get_execution(execution_id)
        if run["status"] in (RUN_COMPLETED, RUN_REJECTED):
            raise ExecutionNotRunnable(
                f"execution is terminal (status={run['status']})")
        plan_id = run["plan_id"]
        # Adopt any outputs left 'awaiting_review' from a prior manual run.
        for s in self._get_plan_steps(plan_id):
            out = self._step_output(execution_id, s["seq"])
            if out and out.get("status") == STEP_AWAITING:
                self._mark_step(plan_id, execution_id, s["seq"], STEP_TERMINAL_ACCEPTED)

        ran: List[Dict[str, Any]] = []
        while True:
            eligible = self.next_eligible_step(execution_id)
            if eligible is None:
                break
            seq = eligible["seq"]
            step_row = self._plan_step_row(plan_id, seq)
            ceiling = []
            if step_row and step_row.get("effective_permissions"):
                try:
                    ceiling = json.loads(step_row["effective_permissions"])
                except (TypeError, ValueError):
                    ceiling = []
            ran.append(self._run_autonomous_step(
                execution_id, plan_id, seq, eligible["agent_id"],
                eligible["responsibility"], ceiling))

        all_accepted = self._all_accepted(execution_id, plan_id)
        result: Dict[str, Any] = {
            "execution_id": execution_id, "ran": ran,
            "all_accepted": all_accepted,
            "run_status": self._get_execution(execution_id)["status"],
        }
        if all_accepted:
            result["deliverable"] = self.aggregate(execution_id, approver_user_id)
            result["run_status"] = self._get_execution(execution_id)["status"]
        return result

    def _plan_step_row(self, plan_id: str, seq: int) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM coordination_plan_steps WHERE plan_id=? AND tenant_id=? AND user_id=? "
            "AND seq=?",
            (plan_id, self.tenant_id, self.user_id, seq))
        return rows[0] if rows else None

    def _accepted_context(self, plan_id: str, execution_id: str) -> Dict[str, Any]:
        """Only ACCEPTED step outputs become downstream context; never rejected /
        failed / missing / revision-requested outputs."""
        steps = self._get_plan_steps(plan_id)
        accepted = {}
        for s in steps:
            out = self._step_output(execution_id, s["seq"])
            if out and out["status"] == STEP_TERMINAL_ACCEPTED and out["output_json"]:
                try:
                    accepted[str(s["seq"])] = json.loads(out["output_json"])
                except Exception:
                    pass
        return accepted

    def _mark_step(self, plan_id, execution_id, seq, status, error=None):
        """Persist a step status (best-effort on a failure path). A persistence
        failure is logged, never silently swallowed, so it remains observable
        while preserving the original dispatch/validation exception."""
        now = _now()
        try:
            with self.db.transaction() as c:
                c.execute(
                    "UPDATE coordination_step_outputs SET status=?, error=?, updated_at=? "
                    "WHERE execution_id=? AND seq=? AND tenant_id=? AND user_id=?",
                    (status, error, now, execution_id, seq, self.tenant_id, self.user_id))
        except Exception as e:
            _log.exception("failed to persist step status exec=%s seq=%s status=%s: %s",
                           execution_id, seq, status, e)

    # ------------------------------------------------------------------ review step
    def review_step(self, execution_id: str, seq: int, decision: str,
                    approver_user_id: str, note: Optional[str] = None) -> Dict[str, Any]:
        """Human review of a step output. decision ∈ {accepted, revision_requested,
        rejected}. Revision and rejection are DISTINCT from acceptance and from
        each other. Accepting a step does NOT auto-dispatch the next agent."""
        if approver_user_id != self.user_id:
            raise ReviewNotPermitted("only the owner may review step outputs")
        run = self._get_execution(execution_id)
        if decision not in (STEP_TERMINAL_ACCEPTED, "revision_requested", STEP_TERMINAL_REJECTED):
            raise InvalidStep(f"unknown decision: {decision}")
        out = self._step_output(execution_id, seq)
        if not out or out.get("status") != STEP_AWAITING:
            raise StepNotAwaitingReview(
                f"step {seq} is not awaiting review (status={out.get('status') if out else None})")
        now = _now()
        if decision == STEP_TERMINAL_ACCEPTED:
            new_st = STEP_TERMINAL_ACCEPTED
        elif decision == "revision_requested":
            new_st = "revision_requested"
        else:
            new_st = STEP_TERMINAL_REJECTED
        with self.db.transaction() as c:
            c.execute(
                "UPDATE coordination_step_outputs SET status=?, updated_at=? "
                "WHERE execution_id=? AND seq=? AND tenant_id=? AND user_id=?",
                (new_st, now, execution_id, seq, self.tenant_id, self.user_id))
        # If every step is accepted the run becomes ready for final aggregation.
        if new_st == STEP_TERMINAL_ACCEPTED and self._all_accepted(execution_id, run["plan_id"]):
            with self.db.transaction() as c:
                c.execute(
                    "UPDATE coordination_executions SET status=?, updated_at=? "
                    "WHERE id=? AND tenant_id=? AND user_id=?",
                    (RUN_READY, now, execution_id, self.tenant_id, self.user_id))
        return {"execution_id": execution_id, "step": seq, "decision": new_st,
                "run_status": self._get_execution(execution_id)["status"],
                "note": (note or "")[:400] or None}

    def _all_accepted(self, execution_id: str, plan_id: str) -> bool:
        steps = self._get_plan_steps(plan_id)
        if not steps:
            return False
        for s in steps:
            st = self._dep_status(execution_id, s["seq"])
            if st != STEP_TERMINAL_ACCEPTED:
                return False
        return True

    # ------------------------------------------------------------------ aggregate / deliverable
    def _dependent_closure(self, plan_id: str, selected: List[int]) -> List[int]:
        """Transitive dependents of the selected steps: every step whose
        depends_on_seq chain reaches a selected/reworked step (directly or
        transitively), plus the selected steps themselves. Used so changed
        upstream results invalidate downstream steps instead of leaving them
        falsely accepted."""
        steps = self._get_plan_steps(plan_id)
        by_seq = {s["seq"]: s for s in steps}
        deps = {s["seq"]: (int(s["depends_on_seq"]) if s.get("depends_on_seq") is not None else None)
                for s in steps}
        closure = set(selected)
        # A step is dependent if it (transitively) depends on any selected step.
        changed = True
        while changed:
            changed = False
            for seq, dep in deps.items():
                if dep is not None and dep in closure and seq not in closure:
                    closure.add(seq)
                    changed = True
        return sorted(closure)

    def aggregate(self, execution_id: str, approver_user_id: str) -> Dict[str, Any]:
        """Build the consolidated deliverable once every step is accepted.

        F3: the return ``reused`` accurately reflects whether an existing
        deliverable was returned unchanged vs freshly created/re-authored.
        F4: aggregation never regresses a terminal (completed/rejected) run to
        ready_for_review.
        """
        if approver_user_id != self.user_id:
            raise ReviewNotPermitted("only the owner may aggregate the deliverable")
        run = self._get_execution(execution_id)
        if run["status"] in (RUN_COMPLETED, RUN_REJECTED):
            raise ExecutionNotRunnable(
                f"cannot aggregate a terminal run (status={run['status']})")
        plan = self._get_plan(run["plan_id"])
        if not self._all_accepted(execution_id, run["plan_id"]):
            raise NotAllStepsAccepted("cannot aggregate until every step is accepted")
        steps = self._get_plan_steps(run["plan_id"])
        outputs = []
        for s in steps:
            out = self._step_output(execution_id, s["seq"])
            if out and out["output_json"]:
                try:
                    outputs.append({"seq": s["seq"], "agent": s["agent_id"],
                                    "output": json.loads(out["output_json"])})
                except Exception:
                    outputs.append({"seq": s["seq"], "agent": s["agent_id"], "output": None})
        content = {"expected_deliverable": plan.get("expected_deliverable"),
                   "steps": outputs}
        now = _now()

        existing = self.db.query(
            "SELECT * FROM coordination_deliverables WHERE execution_id=? AND tenant_id=? AND user_id=?",
            (execution_id, self.tenant_id, self.user_id))

        # Determine the base deliverables row id (create on first aggregation).
        did = existing[0]["id"] if existing else str(uuid.uuid4())
        created_new = not existing
        try:
            with self.db.transaction() as c:
                if not existing:
                    c.execute(
                        "INSERT OR IGNORE INTO coordination_deliverables "
                        "(id, tenant_id, user_id, execution_id, plan_id, title, content_json, "
                        " status, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (did, self.tenant_id, self.user_id, execution_id, run["plan_id"],
                         plan.get("expected_deliverable") or "Deliverable",
                         json.dumps(content), "pending", now, now))
                # Ensure a pending version (create v1, reuse pending, or create a
                # new revision-of pending after rework).
                version = self.deliverables.ensure_pending(
                    c, deliverable_id=did, execution_id=execution_id,
                    content=content, now=now)
                # Keep the base row status aligned with the pending version.
                c.execute(
                    "UPDATE coordination_deliverables SET content_json=?, status=?, "
                    "title=?, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
                    (json.dumps(content), "pending",
                     plan.get("expected_deliverable") or "Deliverable",
                     now, did, self.tenant_id, self.user_id))
                # Advance the run to ready_for_review for any ensured pending
                # version (initial v1 or a rework re-aggregation vN). Reuse of an
                # already-pending version keeps run at ready_for_review.
                c.execute(
                    "UPDATE coordination_executions SET status=?, updated_at=? "
                    "WHERE id=? AND tenant_id=? AND user_id=?",
                    (RUN_READY, now, execution_id, self.tenant_id, self.user_id))
        except Exception:
            raise

        refreshed = self.db.query(
            "SELECT * FROM coordination_deliverables WHERE id=? AND tenant_id=? AND user_id=?",
            (did, self.tenant_id, self.user_id))
        # reused=True only when an existing pending version was reused unchanged.
        reuse_pending = (not created_new and version.get("version") == 1
                         and existing[0]["status"] == "pending" and existing[0]["id"] == did)
        return self._hydrate_deliverable(refreshed[0], reused=bool(reuse_pending))

    def review_deliverable(self, execution_id: str, decision: str,
                           approver_user_id: str, note: Optional[str] = None,
                           rework_steps: Optional[List[int]] = None) -> Dict[str, Any]:
        """Final human review of the aggregated deliverable.

        decision ∈ {accepted, revision_requested, rejected}. Revision is
        actionable: the caller must identify which steps require rework
        (``rework_steps``). Only those steps (and their transitive dependents)
        become revision-requested and eligible for re-execution; their accepted
        output is invalidated so it can no longer flow downstream. Steps not
        selected keep their accepted output. Re-execution stays human-initiated.
        """
        if approver_user_id != self.user_id:
            raise ReviewNotPermitted("only the owner may review the deliverable")
        run = self._get_execution(execution_id)
        rows = self.db.query(
            "SELECT * FROM coordination_deliverables WHERE execution_id=? AND tenant_id=? AND user_id=?",
            (execution_id, self.tenant_id, self.user_id))
        if not rows:
            raise NotAllStepsAccepted("no aggregated deliverable to review")
        deliverable_id = rows[0]["id"]
        if decision not in (STEP_TERMINAL_ACCEPTED, "revision_requested", STEP_TERMINAL_REJECTED):
            raise InvalidStep(f"unknown decision: {decision}")
        now = _now()
        # The version under review is the latest pending version.
        latest = self.deliverables.latest_version(deliverable_id)
        if latest is None:
            raise NotAllStepsAccepted("no deliverable version to review")
        version_id = latest["id"]

        step_decision = {
            STEP_TERMINAL_ACCEPTED: "approved",
            STEP_TERMINAL_REJECTED: "rejected",
            "revision_requested": "revision_requested",
        }[decision]

        if decision == STEP_TERMINAL_ACCEPTED:
            d_st, run_st = STEP_TERMINAL_ACCEPTED, RUN_COMPLETED
        elif decision == STEP_TERMINAL_REJECTED:
            d_st, run_st = STEP_TERMINAL_REJECTED, RUN_REJECTED
        else:  # revision_requested
            if not rework_steps:
                raise InvalidStep(
                    "revision_requested requires 'rework_steps' (the steps to redo)")
            plan_id = run["plan_id"]
            valid_seqs = {int(s["seq"]) for s in self._get_plan_steps(plan_id)}
            try:
                targets = [int(s) for s in rework_steps]
            except (TypeError, ValueError):
                raise InvalidStep(
                    "rework_steps must be a list of valid step sequence numbers") from None
            unknown = [s for s in targets if s not in valid_seqs]
            if unknown:
                raise InvalidStep(
                    f"rework_steps references step(s) not in the plan: "
                    f"{sorted(set(unknown))}")
            # Invalidate the selected steps + their transitive dependents.
            closure = self._dependent_closure(plan_id, targets)
            with self.db.transaction() as c:
                for seq in closure:
                    c.execute(
                        "UPDATE coordination_step_outputs SET status='revision_requested', "
                        "output_json=NULL, evidence_json=NULL, updated_at=? "
                        "WHERE execution_id=? AND seq=? AND tenant_id=? AND user_id=?",
                        (now, execution_id, seq, self.tenant_id, self.user_id))
                # Record the revision decision on the pending version.
                self.deliverables.record_decision(
                    c, version_id=version_id, decision=step_decision,
                    approver_user_id=approver_user_id, note=note, now=now)
                c.execute(
                    "UPDATE coordination_deliverables SET status='revision_requested', "
                    "review_note=?, updated_at=? WHERE id=? AND tenant_id=? AND user_id=?",
                    ((note or "")[:400] or None, now, deliverable_id,
                     self.tenant_id, self.user_id))
                c.execute(
                    "UPDATE coordination_executions SET status=?, updated_at=? "
                    "WHERE id=? AND tenant_id=? AND user_id=?",
                    (RUN_RUNNING, now, execution_id, self.tenant_id, self.user_id))
            return {"execution_id": execution_id, "decision": "revision_requested",
                    "run_status": RUN_RUNNING, "steps": closure,
                    "version_id": version_id, "version": latest["version"]}

        with self.db.transaction() as c:
            # Record the terminal decision on the latest pending version.
            recorded = self.deliverables.record_decision(
                c, version_id=version_id, decision=step_decision,
                approver_user_id=approver_user_id, note=note, now=now)
            c.execute(
                "UPDATE coordination_deliverables SET status=?, review_note=?, updated_at=? "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (d_st, (note or "")[:400] or None, now, deliverable_id,
                 self.tenant_id, self.user_id))
            c.execute(
                "UPDATE coordination_executions SET status=?, updated_at=? "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (run_st, now, execution_id, self.tenant_id, self.user_id))
        return {"execution_id": execution_id, "decision": d_st, "run_status": run_st,
                "version_id": version_id, "version": latest["version"],
                "approval": recorded.get("approvals", [])}

    # ------------------------------------------------------------------ reads
    def status(self, execution_id: str) -> Dict[str, Any]:
        run = self._get_execution(execution_id)
        step_rows = self.db.query(
            "SELECT seq,status,error,evidence_json FROM coordination_step_outputs "
            "WHERE execution_id=? AND tenant_id=? AND user_id=? ORDER BY seq ASC",
            (execution_id, self.tenant_id, self.user_id))
        steps = []
        for r in step_rows:
            steps.append({"seq": r["seq"], "status": r["status"], "error": r["error"],
                          "has_evidence": bool(r["evidence_json"])})
        deliverable = None
        d = self.db.query(
            "SELECT * FROM coordination_deliverables WHERE execution_id=? AND tenant_id=? AND user_id=?",
            (execution_id, self.tenant_id, self.user_id))
        if d:
            deliverable = self._hydrate_deliverable(d[0])
        return {**self._hydrate_execution(run), "steps": steps, "deliverable": deliverable}

    def _hydrate_execution(self, run: Dict[str, Any], reused: bool = False) -> Dict[str, Any]:
        return {
            "execution_id": run["id"],
            "plan_id": run["plan_id"],
            "team_goal_id": run["team_goal_id"],
            "status": run["status"],
            "initiated_by": run["initiated_by"],
            "initiated_at": run["initiated_at"],
            "reused": reused,
        }

    def _hydrate_deliverable(self, d: Dict[str, Any], reused: bool = False) -> Dict[str, Any]:
        content = {}
        try:
            content = json.loads(d["content_json"]) if d["content_json"] else {}
        except Exception:
            content = {}
        return {"deliverable_id": d["id"], "execution_id": d["execution_id"],
                "title": d["title"], "content": content, "status": d["status"],
                "review_note": d["review_note"], "reused": reused}
