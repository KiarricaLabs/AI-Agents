"""Simple HMAC-based auth (no external deps)."""
from __future__ import annotations

import hmac, hashlib, json, base64, time, uuid
from typing import Dict, Any, Optional

SECRET = "change-me-in-prod"


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(user_id: str, tenant_id: str, role: str = "user", ttl: int = 3600) -> str:
    payload = {"sub": user_id, "tenant": tenant_id, "role": role, "exp": int(time.time()) + ttl, "jti": str(uuid.uuid4())}
    body = _b64(json.dumps(payload).encode())
    sig = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(tok: str) -> Optional[Dict[str, Any]]:
    try:
        body, sig = tok.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()