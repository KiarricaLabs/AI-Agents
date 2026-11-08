"""Encrypted credential store. No plaintext fallback."""
from __future__ import annotations

import os
from typing import Optional

try:
    from config.settings import MASTER_KEY as _SETTINGS_MASTER_KEY
except Exception:  # pragma: no cover
    _SETTINGS_MASTER_KEY = ""

MASTER_KEY = _SETTINGS_MASTER_KEY

try:
    from cryptography.fernet import Fernet
except Exception as e:  # pragma: no cover
    Fernet = None
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


class CredentialStore:
    def __init__(self, db=None, tenant_id: str = None, user_id: str = None, key: Optional[str] = None):
        if key is None:
            k = os.getenv("PAT_MASTER_KEY", "") or MASTER_KEY
        else:
            k = key
        if not k:
            raise RuntimeError("PAT_MASTER_KEY is required; no plaintext fallback.")
        if Fernet is None:
            raise RuntimeError(f"cryptography unavailable: {_IMPORT_ERROR}")
        self._fernet = Fernet(k.encode() if isinstance(k, str) else k)
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()

    def _require_db(self):
        if self.db is None or not self.tenant_id or not self.user_id:
            raise RuntimeError("database and owner context required")

    def save(self, provider: str, value: str):
        self._require_db()
        enc = self.encrypt(value)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        # upsert
        rows = self.db.query("SELECT id FROM credentials WHERE tenant_id=? AND user_id=? AND provider=?",
                             (self.tenant_id, self.user_id, provider))
        if rows:
            self.db.execute("UPDATE credentials SET encrypted_payload=?, updated_at=? WHERE tenant_id=? AND user_id=? AND provider=?",
                            (enc, now, self.tenant_id, self.user_id, provider))
        else:
            import uuid
            self.db.execute("INSERT INTO credentials (id,tenant_id,user_id,provider,encrypted_payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()), self.tenant_id, self.user_id, provider, enc, now, now))

    def retrieve(self, provider: str) -> str:
        self._require_db()
        rows = self.db.query("SELECT encrypted_payload FROM credentials WHERE tenant_id=? AND user_id=? AND provider=?",
                             (self.tenant_id, self.user_id, provider))
        if not rows:
            raise KeyError("credential not found")
        return self.decrypt(rows[0]["encrypted_payload"])

    def update(self, provider: str, value: str):
        self.save(provider, value)

    def delete(self, provider: str):
        self._require_db()
        self.db.execute("DELETE FROM credentials WHERE tenant_id=? AND user_id=? AND provider=?",
                        (self.tenant_id, self.user_id, provider))

    def exists(self, provider: str) -> bool:
        if self.db is None:
            return False
        rows = self.db.query("SELECT id FROM credentials WHERE tenant_id=? AND user_id=? AND provider=?",
                             (self.tenant_id, self.user_id, provider))
        return bool(rows)