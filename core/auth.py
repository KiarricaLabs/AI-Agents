"""Simple HMAC-based auth (no external deps).

The token-signing secret is resolved from the ``PAT_AUTH_SECRET`` environment
variable through :func:`resolve_signing_secret`. There is no hardcoded secret.

- In production (``LOCAL_MODE`` off) a missing, placeholder, or insufficiently
  strong secret fails closed (raises), so tokens can never be signed or verified
  unsafely.
- In local development (``LOCAL_MODE`` on) an explicitly labelled fallback is
  used only when ``PAT_AUTH_SECRET`` is unset, with a warning that never reveals
  the secret value.

Secure generation (the real entropy source — the length/uniqueness checks below
are sanity floors, not entropy proofs)::

    python -c "import secrets; print(secrets.token_hex(32))"   # 64 hex chars
    openssl rand -hex 32
"""
from __future__ import annotations

import hmac, hashlib, json, base64, time, uuid, os, logging
from typing import Dict, Any, Optional

from config.settings import LOCAL_MODE

_logger = logging.getLogger("personal_ai_team.auth")

# Known-insecure values that must never be used to sign tokens.
_PLACEHOLDER_SECRETS = {
    "change-me-in-prod", "changeme", "change_me", "secret", "password",
    "your-secret-here", "your_secret_here", "not-a-secret", "replace-me",
    "changethis",
}

# Minimum key-material floor. NOT an entropy proof — see the module docstring for
# the secure generation method. A recommended 256-bit secret is 64 hex chars.
_MIN_KEY_CHARS = 32
_MIN_DISTINCT_CHARS = 8

# Explicit development-only fallback. Used ONLY when LOCAL_MODE is enabled and
# PAT_AUTH_SECRET is unset. Never used in production; clearly labelled so it is
# never mistaken for a real secret.
_DEV_FALLBACK_SECRET = "personal-ai-team-local-development-fallback-only"

_warned_fallback = False


def _secret_is_insecure(secret: str) -> bool:
    s = (secret or "").strip()
    if not s:
        return True
    if s.lower() in _PLACEHOLDER_SECRETS:
        return True
    if len(s) < _MIN_KEY_CHARS:
        return True
    if len(set(s)) < _MIN_DISTINCT_CHARS:
        return True
    return False


def resolve_signing_secret() -> str:
    """Resolve and validate the active token-signing secret (fail-closed).

    Returns a non-empty, non-placeholder secret, or raises RuntimeError. In local
    mode a labelled fallback is returned (with a one-time warning) only when
    ``PAT_AUTH_SECRET`` is unset.
    """
    raw = os.environ.get("PAT_AUTH_SECRET", "").strip()
    if raw:
        if _secret_is_insecure(raw):
            raise RuntimeError(
                "PAT_AUTH_SECRET is set but does not meet security requirements "
                "(placeholder, too short, or insufficient key material). Generate "
                'a strong secret with `python -c "import secrets; print(secrets.token_hex(32))"`.'
            )
        return raw
    # PAT_AUTH_SECRET unset.
    if LOCAL_MODE:
        global _warned_fallback
        if not _warned_fallback:
            _logger.warning(
                "AUTH: development-only signing secret in use (LOCAL_MODE enabled "
                "and PAT_AUTH_SECRET unset). Production requires a strong "
                "PAT_AUTH_SECRET."
            )
            _warned_fallback = True
        return _DEV_FALLBACK_SECRET
    raise RuntimeError(
        "AUTH: PAT_AUTH_SECRET is not configured; refusing to start in non-local "
        "mode."
    )


def validate_auth_secret() -> str:
    """Startup guard: resolve the secret (fail-closed) or raise."""
    return resolve_signing_secret()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(user_id: str, tenant_id: str, role: str = "user", ttl: int = 3600) -> str:
    secret = resolve_signing_secret()
    payload = {"sub": user_id, "tenant": tenant_id, "role": role, "exp": int(time.time()) + ttl, "jti": str(uuid.uuid4())}
    body = _b64(json.dumps(payload).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(tok: str) -> Optional[Dict[str, Any]]:
    secret = resolve_signing_secret()
    try:
        body, sig = tok.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()):
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