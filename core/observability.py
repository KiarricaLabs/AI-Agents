"""Structured logging helper (no secrets)."""
from __future__ import annotations

import json, logging, time

logger = logging.getLogger("pat")


def log_event(action: str, **fields):
    # strip sensitive keys
    safe = {k: v for k, v in fields.items() if k not in ("password", "token", "secret", "api_key")}
    logger.info(json.dumps({"action": action, "ts": time.time(), **safe}))