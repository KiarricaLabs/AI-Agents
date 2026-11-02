"""M10 Phase B — fixed proposal-writing tools.

Each tool persists a proposal via WorkProposalService ONLY — it never creates or
mutates a real project/goal/assignment/deliverable/task/episode and never
approves. Every tool:

- is non-consequential (persisting a *proposal* is not an execution/approval),
- requires a valid originating ``thread_id`` or refuses to write,
- requires the agent's explicit ``work:propose:*`` permission (third auth layer),
- recursively rejects sensitive/credential fields,
- uses a deterministic, user-scoped idempotency key,
- verifies post-write ownership (fail closed on mismatch).

Authorization (layers 1+2: manifest tools + default-deny PolicyEngine) is
enforced by ToolRegistry.invoke before any of these run.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from core.tools import Tool
from core.work_proposals import WorkProposalService


# Sensitive/credential field tokens (case-insensitive, substring on snake key).
_CRED_TOKENS = (
    "password", "secret", "token", "api_key", "api-key", "apikey",
    "client_secret", "master_key", "private_key", "credential",
)


def _reject_secret(obj: Any, path: str = "payload"):
    """Recursively reject proposal data containing credential-bearing fields."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            low = str(k).replace(" ", "_").lower()
            if any(t in low for t in _CRED_TOKENS):
                raise ValueError("proposal contains a sensitive field and was not saved")
            _reject_secret(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            _reject_secret(x, f"{path}[{i}]")


def _canonical(obj: Any) -> str:
    """Deterministic, stable JSON serialization for canonical payloads."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _make_key(tenant_id: str, user_id: str, thread_id: str, work_type: str,
              action: str, payload: Dict[str, Any]) -> str:
    material = "|".join([
        str(tenant_id), str(user_id), str(thread_id),
        work_type, action, _canonical(payload),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class _ProposeTool(Tool):
    consequential = False
    work_type: str = ""
    action: str = "create"
    required_permission: str = ""

    def run(self, args: dict, context: Optional[dict] = None) -> Any:
        ctx = context or {}
        manifest = ctx.get("manifest") or {}
        agent_id = ctx.get("agent_id") or ""
        db = ctx.get("db")
        tenant_id = ctx.get("tenant_id")
        # Identity always comes from the server-side tool context, never from
        # client/model-supplied arguments.
        user_id = ctx.get("user_id")
        if not tenant_id or not user_id:
            raise ValueError("server-side identity is required to save a proposal")

        # Layer 3: explicit in-tool permission.
        perms = set(manifest.get("permissions", []) or [])
        if self.required_permission not in perms:
            raise PermissionError(
                f"Agent '{agent_id}' lacks '{self.required_permission}' to create this proposal")

        # Thread retention: a valid originating thread is mandatory.
        thread_id = (args.get("thread_id") or "").strip()
        if not thread_id:
            raise ValueError("a valid originating conversation thread is required")

        payload = dict(args.get("payload") or {})
        # Goal-update version capture (approved Phase C addition): read the
        # target goal's current version at propose time so approval can enforce a
        # version guard. Never trust a model-supplied value; always server-read.
        if self.work_type == "goal_update" and self.action == "update":
            gid = args.get("target_id") or payload.get("target_id")
            if not gid:
                raise ValueError("target_id (goal) is required to propose a goal update")
            gv = db.query(
                "SELECT version FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
                (gid, tenant_id, user_id))
            if not gv:
                raise ValueError("goal not found in this tenant/user scope")
            payload["_base_version"] = int(gv[0]["version"])
        reason = (args.get("reason") or "").strip()
        context_text = (args.get("context") or "").strip()
        # Sensitive-data protection (recursive).
        _reject_secret(payload, "payload")
        _reject_secret({"reason": reason, "context": context_text}, "meta")

        # User-scoped deterministic idempotency key; always supplied.
        key = args.get("idempotency_key") or _make_key(
            tenant_id, user_id, thread_id, self.work_type, self.action, payload)

        svc = WorkProposalService(db=db, tenant_id=tenant_id, user_id=user_id)
        target_id = args.get("target_id") or payload.get("target_id")
        result = svc.propose(
            self.work_type, agent_id,
            action=self.action,
            payload=payload,
            thread_id=thread_id,
            reason=reason or None,
            context=context_text or None,
            confidence=float(args.get("confidence", 0.5)),
            idempotency_key=key,
            target_id=target_id,
        )
        # Ownership verification after persistence: fail closed if it is not ours.
        row = svc.get(result["proposal_id"])
        if not row or row["tenant_id"] != tenant_id or row["user_id"] != user_id:
            raise ValueError("proposal ownership verification failed")
        return {
            "proposal_id": result["proposal_id"],
            "status": row["status"],
            "reused": bool(result.get("reused", False)),
        }


def _T(work_type: str, action: str, permission: str, description: str):
    return type(
        f"Tool_{work_type}_{action}".replace(" ", "_"),
        (_ProposeTool,),
        {
            "name": f"work_propose_{work_type}" if action == "create" else f"work_propose_{work_type}",
            "description": description,
            "work_type": work_type,
            "action": action,
            "required_permission": permission,
        },
    )


# The six fixed proposal tools. Tool name is keyed by work_type (action encoded
# in the class). Only these are registered; the harness can never run an
# arbitrary tool name.
ALL_PROPOSE_TOOLS = [
    _T("project", "create", "work:propose:project", "Propose a new project inside an existing workspace."),
    _T("goal", "create", "work:propose:goal", "Propose a new goal inside an existing project."),
    _T("goal_update", "update", "work:propose:goal_update", "Propose an update to an existing goal."),
    _T("assignment", "create", "work:propose:assignment", "Propose assigning an agent to an existing goal."),
    _T("deliverable", "create", "work:propose:deliverable", "Propose a new deliverable inside an existing project."),
    _T("deliverable_version", "create", "work:propose:deliverable_version", "Propose deliverable content (draft proposal only)."),
]

# Fixed mapping the harness uses: (work_type, action) -> tool name.
WORK_TOOL_MAP: Dict[tuple, str] = {
    ("project", "create"): "work_propose_project",
    ("goal", "create"): "work_propose_goal",
    ("goal_update", "update"): "work_propose_goal_update",
    ("assignment", "create"): "work_propose_assignment",
    ("deliverable", "create"): "work_propose_deliverable",
    ("deliverable_version", "create"): "work_propose_deliverable_version",
}
