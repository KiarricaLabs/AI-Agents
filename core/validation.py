"""Minimal dependency-free structured-output validator.

Validates an agent's structured result before it is accepted by the
orchestrator/task flow. Enforces: dict result, required scalar fields,
no embedded secrets, and bounded field sizes. No external dependencies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

MAX_FIELD_LEN = 20_000

SECRET_PATTERNS = (
    "password", "secret", "token", "api_key", "api-key",
    "master_key", "private_key", "client_secret", "ssh-rsa",
)

# Per-agent required fields and their expected scalar types.
# Every agent returns a `reply` string; additional contracts can be added
# per agent without new dependencies.
AGENT_CONTRACTS: Dict[str, Dict[str, Any]] = {
    name: {"required": ["reply"], "scalar": {"reply": str}}
    for name in (
        "tutor", "strategist", "executive_assistant",
        "communications", "soundboard", "workspace_architect",
    )
}

DEFAULT_CONTRACT: Dict[str, Any] = {"required": ["reply"], "scalar": {"reply": str}}


def _contains_secret(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in SECRET_PATTERNS)


def validate_output(agent_id: str, result: Any) -> Tuple[bool, str]:
    """Return (ok, error). ok=False means the output must not be accepted."""
    if not isinstance(result, dict):
        return False, "output must be a dict"

    contract = AGENT_CONTRACTS.get(agent_id, DEFAULT_CONTRACT)
    required: List[str] = contract.get("required", [])
    scalar: Dict[str, type] = contract.get("scalar", {})

    for key in required:
        if key not in result:
            return False, f"missing required field '{key}'"
        value = result[key]
        expected = scalar.get(key)
        if expected is not None and not isinstance(value, expected):
            return False, f"field '{key}' must be {expected.__name__}"
        if isinstance(value, str):
            if len(value) > MAX_FIELD_LEN:
                return False, f"field '{key}' exceeds max length"
            if _contains_secret(value):
                return False, f"field '{key}' contains a secret"
    return True, ""
