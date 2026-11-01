"""Agent execution API: list agents and run them against the local runtime."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

router = APIRouter(prefix="/agents", tags=["agents"])

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)


class RunReq(BaseModel):
    task: str


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

    if not req.task or not req.task.strip():
        raise HTTPException(status_code=422, detail="task must not be empty")

    orch = build_runtime(_db, t, u)
    try:
        result = orch.dispatch(name, req.task.strip())
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        # Ollama unreachable or provider error (no cloud fallback).
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        # Invalid structured output was rejected before acceptance.
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="agent execution failed")
    return result
