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


class IncrementalValidator:
    """Stateful sliding-window validator for streamed text chunks.

    Prevents secret-pattern substrings from crossing chunk boundaries and
    enforces the cumulative MAX_FIELD_LEN limit. Patterns are checked
    case-insensitively against a window of (max_pattern_len - 1) trailing
    characters combined with each incoming chunk.

    Assumptions (review if validation rules change):
    - Secret patterns are simple case-insensitive substrings.
    - MAX_FIELD_LEN is a cumulative character count.
    - Patterns are never longer than the window can cover.
    - If SECRET_PATTERNS is empty, no pattern checks are performed.
    """

    def __init__(self):
        self._total = 0
        self._window = ""
        self._max_pattern_len = max((len(p) for p in SECRET_PATTERNS), default=0)
        self._window_size = max(0, self._max_pattern_len - 1)

    @property
    def max_pattern_len(self) -> int:
        return self._max_pattern_len

    @property
    def total(self) -> int:
        return self._total

    def check_chunk(self, chunk: str) -> Tuple[bool, str]:
        if not isinstance(chunk, str):
            return False, "chunk must be str"
        # Cumulative length check: reject first char that would exceed limit.
        if self._total + len(chunk) > MAX_FIELD_LEN:
            return False, f"field 'reply' exceeds max length"
        combined = (self._window + chunk).lower()
        for p in SECRET_PATTERNS:
            if p.lower() in combined:
                return False, f"field 'reply' contains a secret"
        self._total += len(chunk)
        tail = self._window + chunk
        if self._window_size > 0:
            self._window = tail[-self._window_size:]
        else:
            self._window = ""
        return True, ""


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
