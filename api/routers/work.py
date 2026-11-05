"""M10 Phase A + Phase C — work proposal API.

Phase A: authenticated, tenant/user-scoped read-only list/detail of proposals.
Phase C adds human-controlled approval and rejection endpoints. Identities
always come from ``request.state`` (set by security middleware); never from
request bodies or headers. Human-only actions require ``request.state.role`` in
``{"user","admin"}`` (fail closed). Approval/rejection never returns internal
exception details or leaks the existence of another user's proposal.
"""
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from core.work_proposals import (
    WorkProposalService,
    ProposalNotFound,
    ProposalAlreadyDecided,
    StaleProposal,
    ApprovalNotPermitted,
    ProposalExecutionFailed,
    ProposalValidationError,
    TransientApprovalError,
    AGENT_SLUGS,
)
from core.episodes import EpisodeService
from core.execution import (
    ApprovedExecutionService,
    AssignmentNotFound,
    AssignmentNotApproved,
    InvalidAgent,
    AgentMismatch,
    SelfExecution,
)
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/work", tags=["work"])

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)

# Verified human roles allowed to approve/reject work proposals. Agents have no
# API surface with these roles; fail closed for anything else.
_HUMAN_ROLES = {"user", "admin"}


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


def _require_human(request: Request):
    role = getattr(request.state, "role", "user")
    if role not in _HUMAN_ROLES:
        raise HTTPException(status_code=403, detail="human approval required")


def _svc(t: str, u: str):
    return WorkProposalService(_db, t, u)


# Work types that can be explicitly executed (lifecycle-tracked) by a human.
_EXEC_TYPES = {"assignment", "goal"}


class ExecuteBody(BaseModel):
    agent_id: str


@router.post("/assignment/{assignment_id}/execute-approved")
def execute_approved_assignment(assignment_id: str, body: ExecuteBody, request: Request, response: Response):
    """Human-only execution tracking of an APPROVED assignment. Independently
    verifies ownership + genuine approval before starting/reusing the Episode.
    Lifecycle tracking only; no worker/dispatch/autonomy."""
    t, u = _identity(request)
    _require_human(request)
    try:
        result = ApprovedExecutionService(db=_db, tenant_id=t, user_id=u).execute_approved_assignment(
            assignment_id, u, body.agent_id)
    except AssignmentNotFound:
        raise HTTPException(status_code=404, detail="assignment not found")
    except AssignmentNotApproved:
        raise HTTPException(status_code=403, detail="assignment is not approved for execution")
    except (InvalidAgent, AgentMismatch) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except SelfExecution:
        raise HTTPException(status_code=403, detail="an agent cannot start its own execution")
    response.status_code = 201 if not result["already_active"] else 200
    return result


@router.post("/{work_type}/{work_id}/execute")
def execute_work(work_type: str, work_id: str, body: ExecuteBody, request: Request, response: Response):
    """Human-only, owner-scoped start of a tracked execution Episode for an
    approved assignment or goal. Idempotent: an existing active episode is
    returned. Lifecycle tracking only; never runs or dispatches an agent."""
    t, u = _identity(request)
    _require_human(request)
    agent = (body.agent_id or "").strip()
    if work_type not in _EXEC_TYPES:
        raise HTTPException(status_code=422, detail="unsupported work type for execution")
    if agent not in AGENT_SLUGS:
        raise HTTPException(status_code=422, detail="invalid agent")
    if agent == u:
        raise HTTPException(status_code=403, detail="an agent cannot start its own execution")
    # Revalidate ownership of the approved work record (server-scoped ids).
    if work_type == "assignment":
        rows = _db.query(
            "SELECT id, agent_id FROM assignments WHERE id=? AND tenant_id=? AND user_id=?",
            (work_id, t, u))
        if not rows:
            raise HTTPException(status_code=404, detail="assignment not found")
        if agent != rows[0]["agent_id"]:
            raise HTTPException(status_code=422, detail="agent does not match the assignment")
    else:  # goal
        rows = _db.query(
            "SELECT id FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
            (work_id, t, u))
        if not rows:
            raise HTTPException(status_code=404, detail="goal not found")
    es = EpisodeService(db=_db, tenant_id=t, user_id=u)
    try:
        result = es.start_for_work(work_type, work_id, agent)
    except Exception:
        raise HTTPException(status_code=503, detail="could not start execution")
    payload = {**result, "work_type": work_type, "work_id": work_id, "agent_id": agent}
    response.status_code = 201 if not result["already_active"] else 200
    return payload


@router.get("/proposals")
def list_proposals(request: Request, status: Optional[str] = None):
    t, u = _identity(request)
    return {"items": _svc(t, u).list(status)}


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, request: Request):
    t, u = _identity(request)
    p = _svc(t, u).get(proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return p


@router.get("/feed")
def get_feed(request: Request):
    """Consolidated proposal/decision feed (read-only)."""
    t, u = _identity(request)
    return {"items": _svc(t, u).list_feed()}


@router.get("/links")
def links_for_thread(request: Request, thread_id: Optional[str] = None):
    """Conversation thread -> approved linked work (read-only)."""
    t, u = _identity(request)
    return {"items": _svc(t, u).links_for_thread(thread_id)}


@router.get("/{work_type}/{work_id}/execution")
def work_execution(work_type: str, work_id: str, request: Request):
    """Read-only execution summary for a goal/assignment (active + completed
    episodes, progress, latest evidence summary, apply state). Owner-scoped and
    sanitized; never exposes raw evidence or credentials."""
    t, u = _identity(request)
    try:
        return EpisodeService(db=_db, tenant_id=t, user_id=u).execution_summary(work_type, work_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="unsupported work type")


@router.get("/links/work/{work_type}/{work_id}")
def links_to_thread(work_type: str, work_id: str, request: Request):
    """Work record -> originating conversation thread(s) (read-only)."""
    t, u = _identity(request)
    try:
        threads = _svc(t, u).threads_for_work(work_type, work_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="unsupported work type")
    return {"work_type": work_type, "work_id": work_id, "threads": threads}


class RejectBody(BaseModel):
    reason: Optional[str] = None


class WorkspaceProposalReq(BaseModel):
    name: str
    thread_id: Optional[str] = None


class ExtractWorkReq(BaseModel):
    """Human-gated draft extraction from a conversation message.

    DRAFT ONLY: returns an editable assignment/deliverable draft. Nothing is
    persisted here; the human proposes it through ``POST /work/proposals`` and
    approves it before any real record is created.
    """
    kind: str
    message: str
    subject_agent: Optional[str] = None  # used as the assignment subject fallback
    owner_agent: Optional[str] = None    # used as the deliverable owner fallback


class ProposeWorkReq(BaseModel):
    """Deterministic proposal creation for any supported work type.

    Only a proposal row is stored; a human must still approve it before any real
    workspace record is created. This is the reliable path for all proposal
    types and does not depend on AI-model JSON output.
    """
    work_type: str
    action: str = "create"
    payload: dict = {}
    target_id: Optional[str] = None
    thread_id: Optional[str] = None
    agent_id: Optional[str] = None


@router.post("/extract")
def extract_work(req: ExtractWorkReq, request: Request):
    """Return an editable, validated assignment/deliverable DRAFT from a message.

    Human-gated. Drafts persist nothing; creating real work still requires the
    human-only ``POST /work/proposals`` flow plus explicit approval.
    """
    from core.message_work_extractor import EXTRACTORS

    t, u = _identity(request)
    _require_human(request)
    extract = EXTRACTORS.get((req.kind or "").strip().lower())
    if not extract:
        raise HTTPException(status_code=400, detail=f"unsupported kind: {req.kind}")
    try:
        kwargs = {}
        if req.kind == "assignment":
            kwargs["subject_agent"] = req.subject_agent
        elif req.kind == "deliverable":
            kwargs["owner_agent"] = req.owner_agent
        draft = extract(req.message, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"kind": draft["kind"], "draft": draft, "persisted": False}


@router.post("/proposals")
def create_proposal(req: ProposeWorkReq, request: Request):
    t, u = _identity(request)
    _require_human(request)
    from core.tools.work_propose import _reject_secret

    work_type = (req.work_type or "").strip()
    action = (req.action or "create").strip()
    agent = (req.agent_id or "workspace_architect").strip().lower()
    if agent not in AGENT_SLUGS:
        raise HTTPException(status_code=422, detail="unknown agent")
    payload = dict(req.payload or {})
    try:
        _reject_secret(payload, "payload")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # goal_update: capture the goal's version server-side so approval's
    # optimistic version guard is enforced (never trust a client-supplied value).
    if work_type == "goal_update" and action == "update":
        gid = req.target_id or payload.get("target_id")
        if not gid:
            raise HTTPException(status_code=422, detail="target goal is required")
        rows = _db.query(
            "SELECT version FROM goals WHERE id=? AND tenant_id=? AND user_id=?",
            (gid, t, u))
        if not rows:
            raise HTTPException(status_code=404, detail="goal not found")
        payload["_base_version"] = int(rows[0]["version"])

    key = hashlib.sha256(
        f"{t}|{u}|{work_type}|{action}|{json.dumps(payload, sort_keys=True, default=str)}".encode("utf-8")
    ).hexdigest()
    try:
        r = _svc(t, u).propose(
            work_type, agent, action=action, payload=payload,
            thread_id=req.thread_id, target_id=req.target_id,
            idempotency_key=key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"proposal_id": r["proposal_id"], "status": r["status"],
            "work_type": work_type, "action": action,
            "reused": bool(r.get("reused", False))}


@router.post("/proposals/workspace")
def propose_workspace(req: WorkspaceProposalReq, request: Request):
    """Deterministically create a *proposed* workspace (Option A).

    Only a proposal row is stored; a human must still approve it in the
    Work/Approvals feed before any real workspace is created. This does not
    depend on AI-model JSON output, so it is a reliable creation path while
    keeping workspace creation behind human approval. Idempotent on the name.
    """
    t, u = _identity(request)
    _require_human(request)
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="workspace name is required")
    key = f"manual-ws:{t}:{u}:{name.lower()}"
    try:
        r = _svc(t, u).propose(
            "workspace", "workspace_architect", payload={"name": name},
            thread_id=req.thread_id, idempotency_key=key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"proposal_id": r["proposal_id"], "status": r["status"],
            "work_type": "workspace", "name": name,
            "reused": bool(r.get("reused", False))}


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, request: Request):
    t, u = _identity(request)
    _require_human(request)
    try:
        result = _svc(t, u).approve(proposal_id, u)
    except ProposalNotFound:
        raise HTTPException(status_code=404, detail="proposal not found")
    except ApprovalNotPermitted:
        raise HTTPException(status_code=403, detail="not permitted to approve this proposal")
    except ProposalAlreadyDecided:
        raise HTTPException(status_code=409, detail="proposal already decided")
    except StaleProposal:
        raise HTTPException(status_code=422, detail="proposal is no longer valid; a parent record changed or is missing")
    except ProposalValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ProposalExecutionFailed:
        raise HTTPException(status_code=409, detail="proposal could not be executed")
    except TransientApprovalError:
        raise HTTPException(status_code=503, detail="approval temporarily unavailable; try again")
    return result


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, body: RejectBody = None, request: Request = None):
    t, u = _identity(request)
    _require_human(request)
    try:
        _svc(t, u).reject(proposal_id, u, reason=(body.reason if body else None))
    except ProposalNotFound:
        raise HTTPException(status_code=404, detail="proposal not found")
    except ProposalAlreadyDecided:
        raise HTTPException(status_code=409, detail="proposal already decided")
    return {"ok": True, "status": "rejected"}
