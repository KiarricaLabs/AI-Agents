"""Agent execution API: list agents and run them against the local runtime."""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.memory import MemoryService
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/agents", tags=["agents"])

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)

# Number of most-recent conversation messages injected for grounding.
HISTORY_WINDOW = 12


class RunReq(BaseModel):
    task: str
    thread_id: Optional[str] = None


def _identity(request: Request):
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="identity required")
    return tenant, user


@router.get("")
def list_agents():
    from core.runtime import available_agents
    return {"agents": available_agents()}


@router.post("/{name}/run")
def run_agent(name: str, req: RunReq, request: Request):
    t, u = _identity(request)
    from core.runtime import build_runtime, load_registry

    reg = load_registry()
    if name not in reg.list():
        raise HTTPException(status_code=404, detail=f"unknown agent: {name}")

    task = (req.task or "").strip()
    if not task:
        raise HTTPException(status_code=422, detail="task must not be empty")

    svc = MemoryService(db=_db, tenant_id=t)

    # Thread identity is an opaque key; tenant/user identity comes from request.state
    # only. A foreign/unknown thread id simply yields empty history (no cross-user leak).
    thread_id = req.thread_id
    history = []
    if thread_id:
        history = svc.list_conversation(u, thread_id)
    else:
        thread_id = str(uuid.uuid4())

    # Bound the injected history to the approved window (most recent messages).
    context_history = history[-HISTORY_WINDOW:] if history else []

    orch = build_runtime(_db, t, u)
    try:
        result = orch.dispatch(name, task, context={"thread_id": thread_id, "conversation": context_history})
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        # Ollama unreachable or provider error (no cloud fallback).
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        # Invalid structured output was rejected before acceptance.
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="agent execution failed")

    # Persist both turns. A write failure must not silently lose a successful reply.
    try:
        svc.add_conversation(u, task, "user", thread_id)
        svc.add_conversation(u, result.get("reply", ""), "assistant", thread_id)
    except Exception as e:
        result["history_warning"] = (
            f"reply generated but conversation history failed to save ({type(e).__name__})"
        )

    result["thread_id"] = thread_id
    result["context_messages"] = len(context_history)
    return result
