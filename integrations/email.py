"""Email integration (Phase D2) — SMTP sending, human-gated."""
from __future__ import annotations
import smtplib
import ssl
from email.message import EmailMessage
from integrations import Integration
from typing import Any, Dict, List


class EmailIntegration(Integration):
    name = "email"

    def __init__(self, credential_store=None, tenant_id=None, user_id=None):
        self._connected = False
        self._creds = None
        self._store = credential_store
        self._tenant = tenant_id
        self._user = user_id

    def connect(self, credentials):
        self._creds = credentials or {}
        self._connected = True
        return True

    def disconnect(self):
        self._connected = False
        self._creds = None

    def health(self):
        return {"connected": self._connected}

    def requires_approval(self, action):
        return action in ("send", "reply", "forward")

    def _resolve_creds(self):
        if self._creds:
            return self._creds
        if self._store is not None:
            try:
                import json
                raw = self._store.retrieve("email")
                return json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                return None
        return None

    def _validate_recipients(self, recipients):
        if isinstance(recipients, str):
            recipients = [recipients]
        if not recipients:
            raise ValueError("no recipients")
        for r in recipients:
            if "@" not in str(r) or not str(r).strip():
                raise ValueError(f"invalid recipient: {r}")
        return [str(r).strip() for r in recipients]

    def execute(self, action, params, *, approved=False):
        if not self._connected and self._creds is None and self._store is None:
            # allow execution if creds resolvable
            pass
        if action == "draft":
            return {"ok": True, "draft": params.get("body", "")}
        if action != "send":
            return {"ok": False, "error": f"unknown action {action}"}
        if self.requires_approval(action) and not approved:
            return {"ok": False, "error": "human approval required", "gated": True}
        # resolve creds
        creds = self._resolve_creds()
        if not creds:
            return {"ok": False, "error": "missing credentials"}
        host = creds.get("host")
        port = int(creds.get("port", 587))
        username = creds.get("username")
        password = creds.get("password")
        sender = creds.get("sender") or username
        use_tls = bool(creds.get("use_tls", False))
        use_starttls = bool(creds.get("use_starttls", True))
        timeout = int(creds.get("timeout", 30))
        if not host or not sender:
            return {"ok": False, "error": "missing smtp host/sender"}
        try:
            recipients = self._validate_recipients(params.get("to"))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        subject = params.get("subject", "")
        body = params.get("body", "")
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            if use_tls:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx) as server:
                    if username and password:
                        server.login(username, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=timeout) as server:
                    server.ehlo()
                    if use_starttls:
                        ctx = ssl.create_default_context()
                        server.starttls(context=ctx)
                        server.ehlo()
                    if username and password:
                        server.login(username, password)
                    server.send_message(msg)
            return {"ok": True, "sent": True, "to": recipients}
        except smtplib.SMTPAuthenticationError:
            return {"ok": False, "error": "authentication failed"}
        except smtplib.SMTPException as exc:
            return {"ok": False, "error": f"smtp error: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"send failed: {exc}"}