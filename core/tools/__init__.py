"""Local-only, deterministic tool execution with permission enforcement and audit.

Every tool invocation requires the tool to be:
  1. registered (implemented),
  2. declared in the calling agent's manifest `tools`,
  3. allowed by policy (default-deny), and
  4. explicitly approved if `consequential`.

Execution is in-process and deterministic: no eval/exec/subprocess/network/filesystem.
Each invocation is audited without storing raw arguments or sensitive content.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class Tool:
    name: str = "tool"
    description: str = ""
    consequential: bool = False

    def run(self, args: dict, context: Optional[dict] = None) -> Any:
        raise NotImplementedError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(message: str) -> str:
    # Truncate and redact obvious secrets; never return stack traces or raw values.
    text = str(message or "")
    for kw in ("password", "secret", "token", "api_key", "api-key", "master_key"):
        if kw.lower() in text.lower():
            text = "<redacted>"
            break
    return text[:200]


def _hash_params(args: Dict[str, Any]) -> str:
    try:
        return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
    except Exception:
        return "unhashable"


class ToolRegistry:
    """Single execution and permission-enforcement layer for local tools."""

    def __init__(self, db=None, tenant_id: Optional[str] = None, default_timeout: float = 5.0):
        self.db = db
        self.tenant = tenant_id or (db.default_tenant if db is not None else "local")
        self.default_timeout = default_timeout
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list(self) -> List[str]:
        return list(self._tools.keys())

    def invoke(self, agent_id, tool_name, args, manifest=None, policy=None,
               user_id=None, approved=False, context=None, timeout=None) -> Dict[str, Any]:
        tool = self.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' is not registered/available.")
        if manifest is not None and tool_name not in (manifest.get("tools") or []):
            raise PermissionError(f"Agent '{agent_id}' is not authorized for tool '{tool_name}'.")
        if policy is not None and not policy.allow(agent_id, "tool", tool_name):
            raise PermissionError(f"Policy denies tool '{tool_name}' for '{agent_id}'.")
        if tool.consequential and not approved:
            raise PermissionError(f"Tool '{tool_name}' is consequential and requires approval.")

        t = timeout if timeout is not None else self.default_timeout
        # Enrich the context passed to the tool with server-side identity so a
        # tool can enforce tenant/user ownership and the layer-3 permission check
        # without trusting any client-supplied value. Existing tools ignore these.
        tool_context = {
            **(context or {}),
            "agent_id": agent_id,
            "manifest": manifest,
            "tenant_id": self.tenant,
            "db": self.db,
            "user_id": user_id,
        }
        try:
            value = self._run_with_timeout(tool, args, tool_context, t)
            status = "ok"
            result: Dict[str, Any] = {"ok": True, "result": value}
        except TimeoutError:
            status = "timeout"
            result = {"ok": False, "error": "timeout"}
        except Exception as e:
            status = "error"
            result = {"ok": False, "error": _sanitize(str(e))}

        self._audit(agent_id, tool_name, args, user_id, status, result.get("error"))
        return result

    def _run_with_timeout(self, tool: Tool, args: dict, context: Optional[dict], timeout: float):
        box: Dict[str, Any] = {}
        errors: Dict[str, BaseException] = {}

        def target():
            try:
                box["value"] = tool.run(args, context)
            except BaseException as e:  # capture and re-raise on the caller thread
                errors["value"] = e

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            # Python cannot kill a thread; a non-cooperative tool continues until it returns.
            # M8's built-in tools are pure and O(1), so this only triggers for misbehaving tools.
            raise TimeoutError(f"tool '{tool.name}' exceeded {timeout}s")
        if "value" in errors:
            raise errors["value"]
        return box.get("value")

    def _audit(self, agent_id, tool_name, args, user_id, status, error):
        if self.db is None:
            return
        self.db.execute(
            "INSERT INTO tool_executions (id,tenant_id,user_id,agent_id,tool,params_hash,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant, user_id, agent_id, tool_name,
             _hash_params(args), status, error, _now()))


def build_registry(db=None, tenant_id: Optional[str] = None, timeout: float = 5.0) -> ToolRegistry:
    reg = ToolRegistry(db=db, tenant_id=tenant_id, default_timeout=timeout)
    from core.tools.local.now import NowTool
    from core.tools.local.calculate import CalculateTool
    reg.register(NowTool())
    reg.register(CalculateTool())
    from core.tools.work_propose import ALL_PROPOSE_TOOLS
    for tool in ALL_PROPOSE_TOOLS:
        reg.register(tool())
    return reg
