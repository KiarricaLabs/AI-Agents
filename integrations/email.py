"""Email integration (Phase D2) — stub, human-gated sends."""
from __future__ import annotations
from integrations import Integration
from typing import Any, Dict


class EmailIntegration(Integration):
    name = "email"

    def __init__(self):
        self._connected = False
        self._creds = None

    def connect(self, credentials):
        self._creds = credentials
        self._connected = True
        return True

    def disconnect(self):
        self._connected = False
        self._creds = None

    def health(self):
        return {"connected": self._connected}

    def requires_approval(self, action):
        return action in ("send", "reply", "forward")

    def execute(self, action, params, *, approved=False):
        if not self._connected:
            return {"ok": False, "error": "not connected"}
        if self.requires_approval(action) and not approved:
            return {"ok": False, "error": "human approval required", "gated": True}
        if action == "draft":
            return {"ok": True, "draft": params.get("body", "")}
        if action == "send":
            return {"ok": True, "sent": True, "to": params.get("to")}
        return {"ok": False, "error": f"unknown action {action}"}