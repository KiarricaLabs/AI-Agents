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


def issue_refresh(db, tenant_id, user_id, ttl=86400*7):
    import uuid
    from datetime import datetime, timezone, timedelta
    raw = str(uuid.uuid4())
    family = str(uuid.uuid4())
    h = hash_refresh(raw)
    exp = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
    db.execute(
        "INSERT INTO refresh_tokens (id,tenant_id,user_id,token_hash,family_id,expires_at,created_at) VALUES (?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), tenant_id, user_id, h, family, exp, datetime.now(timezone.utc).isoformat()))
    return raw, family


def rotate_refresh(db, old_raw, tenant_id, user_id):
    h = hash_refresh(old_raw)
    rows = db.query("SELECT * FROM refresh_tokens WHERE token_hash=? AND tenant_id=? AND user_id=?", (h, tenant_id, user_id))
    if not rows:
        return None, "not_found"
    r = rows[0]
    if r["revoked"] or r["reused"]:
        # reuse detected: revoke entire family
        db.execute("UPDATE refresh_tokens SET revoked=1 WHERE family_id=?", (r["family_id"],))
        return None, "reuse_detected"
    from datetime import datetime, timezone
    if r["expires_at"] < datetime.now(timezone.utc).isoformat():
        return None, "expired"
    # mark old as reused
    db.execute("UPDATE refresh_tokens SET reused=1 WHERE id=?", (r["id"],))
    # issue new in same family
    import uuid
    new_raw = str(uuid.uuid4())
    new_h = hash_refresh(new_raw)
    from datetime import timedelta
    exp = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    db.execute(
        "INSERT INTO refresh_tokens (id,tenant_id,user_id,token_hash,family_id,expires_at,created_at) VALUES (?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), tenant_id, user_id, new_h, r["family_id"], exp, datetime.now(timezone.utc).isoformat()))
    return new_raw, "ok"


def revoke_refresh(db, raw, tenant_id, user_id):
    h = hash_refresh(raw)
    db.execute("UPDATE refresh_tokens SET revoked=1 WHERE token_hash=? AND tenant_id=? AND user_id=?", (h, tenant_id, user_id))
    return True