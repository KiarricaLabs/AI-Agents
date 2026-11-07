"""Media integration (Phase E1) — image generation, human-gated."""
from __future__ import annotations
import base64
import json
import urllib.request
import urllib.error
from integrations import Integration
from typing import Any, Dict


class MediaIntegration(Integration):
    name = "media"

    def __init__(self, credential_store=None, tenant_id=None, user_id=None, output_dir=None):
        self._connected = False
        self._creds = None
        self._store = credential_store
        self._tenant = tenant_id
        self._user = user_id
        self._output_dir = output_dir

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
        return action in ("generate", "edit")

    def _resolve_creds(self):
        if self._creds:
            return self._creds
        if self._store is not None:
            try:
                raw = self._store.retrieve("media")
                return json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                return None
        return None

    def _validate(self, params):
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt required")
        size = params.get("size", "1024x1024")
        if size not in ("256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"):
            raise ValueError("invalid size")
        return prompt, size

    def execute(self, action, params, *, approved=False):
        if action != "generate":
            return {"ok": False, "error": f"unknown action {action}"}
        if self.requires_approval(action) and not approved:
            return {"ok": False, "error": "human approval required", "gated": True}
        creds = self._resolve_creds()
        if not creds:
            return {"ok": False, "error": "missing credentials"}
        api_key = creds.get("api_key")
        if not api_key:
            return {"ok": False, "error": "missing api key"}
        model = creds.get("model", "dall-e-3")
        try:
            prompt, size = self._validate(params or {})
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        url = "https://api.openai.com/v1/images/generations"
        payload = {"model": model, "prompt": prompt, "size": size, "n": 1, "response_format": "b64_json"}
        quality = (params or {}).get("quality")
        if quality:
            payload["quality"] = quality
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                    headers={"Authorization": f"Bearer {api_key}",
                                             "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
            items = body.get("data") or []
            if not items:
                return {"ok": False, "error": "no image returned"}
            b64 = items[0].get("b64_json")
            if not b64:
                return {"ok": False, "error": "no image data"}
            # store to output_dir if provided
            path = None
            if self._output_dir:
                import os
                os.makedirs(self._output_dir, exist_ok=True)
                import uuid
                path = os.path.join(self._output_dir, f"{uuid.uuid4()}.png")
                with open(path, "wb") as f:
                    f.write(base64.b64decode(b64))
            return {"ok": True, "asset": {"prompt": prompt, "size": size, "path": path, "b64_length": len(b64)}}
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode()).get("error", {}).get("message", "")
            except Exception:
                detail = str(exc)
            return {"ok": False, "error": f"provider error: {detail}"}
        except Exception as exc:
            return {"ok": False, "error": f"request failed: {exc}"}