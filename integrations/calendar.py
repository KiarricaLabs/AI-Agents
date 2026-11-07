"""Calendar integration (Phase D3) — Google Calendar event creation, human-gated."""
from __future__ import annotations
import json
import urllib.request
import urllib.error
import urllib.parse
from integrations import Integration
from typing import Any, Dict


class CalendarIntegration(Integration):
    name = "calendar"

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
        return action in ("create_event", "update_event", "delete_event")

    def _resolve_creds(self):
        if self._creds:
            return self._creds
        if self._store is not None:
            try:
                raw = self._store.retrieve("calendar")
                return json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                return None
        return None

    def _refresh_token(self, creds):
        refresh = creds.get("refresh_token")
        if not refresh:
            return creds.get("access_token")
        client_id = creds.get("client_id")
        client_secret = creds.get("client_secret")
        token_uri = creds.get("token_uri", "https://oauth2.googleapis.com/token")
        data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(token_uri, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            new_token = payload.get("access_token")
            if new_token:
                creds["access_token"] = new_token
            return new_token
        except Exception:
            return creds.get("access_token")

    def _validate_event(self, params):
        title = (params.get("title") or "").strip()
        if not title:
            raise ValueError("title required")
        start = params.get("start")
        end = params.get("end")
        if not start or not end:
            raise ValueError("start and end required")
        return title, start, end

    def execute(self, action, params, *, approved=False):
        if action == "list":
            return {"ok": True, "events": []}
        if action != "create_event":
            return {"ok": False, "error": f"unknown action {action}"}
        if self.requires_approval(action) and not approved:
            return {"ok": False, "error": "human approval required", "gated": True}
        creds = self._resolve_creds()
        if not creds:
            return {"ok": False, "error": "missing credentials"}
        try:
            title, start, end = self._validate_event(params or {})
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        access_token = self._refresh_token(creds)
        if not access_token:
            return {"ok": False, "error": "missing access token"}
        tz = params.get("timezone", "UTC")
        event = {
            "summary": title,
            "description": params.get("description", ""),
            "start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz},
        }
        if params.get("location"):
            event["location"] = params["location"]
        calendar_id = creds.get("calendar_id", "primary")
        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
        data = json.dumps(event).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                    headers={"Authorization": f"Bearer {access_token}",
                                             "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            return {"ok": True, "event": {"id": payload.get("id"), "title": title}}
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode()).get("error", {}).get("message", "")
            except Exception:
                detail = str(exc)
            return {"ok": False, "error": f"calendar error: {detail}"}
        except Exception as exc:
            return {"ok": False, "error": f"request failed: {exc}"}