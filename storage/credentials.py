"""Encrypted credential store. No plaintext fallback."""
from __future__ import annotations

import os
from typing import Optional

from config.settings import MASTER_KEY

try:
    from cryptography.fernet import Fernet
except Exception as e:  # pragma: no cover
    Fernet = None
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


class CredentialStore:
    def __init__(self, key: Optional[str] = None):
        k = key or MASTER_KEY
        if not k:
            raise RuntimeError("PAT_MASTER_KEY is required; no plaintext fallback.")
        if Fernet is None:
            raise RuntimeError(f"cryptography unavailable: {_IMPORT_ERROR}")
        self._fernet = Fernet(k.encode() if isinstance(k, str) else k)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()